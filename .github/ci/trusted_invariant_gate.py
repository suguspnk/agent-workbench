#!/usr/bin/env python3
"""Validate security-critical invariants without executing candidate code."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CANDIDATE_ROOT = "/workspace"
POLICY_KEYS = {
    "schema_version", "max_file_bytes", "policy_markers", "policy_rows",
    "authorization_by_role", "codex_profiles", "claude_profiles",
    "pinned_candidate_files", "workflow_sha256", "checkout_action", "validation_images",
}
CONTROL_PATHS = {
    "gate": ".github/ci/trusted_invariant_gate.py",
    "policy": ".github/ci/trusted_validation_policy.json",
    "launcher": ".github/ci/run_sandboxed_validation.py",
    "workflow": ".github/workflows/validate.yml",
}
CODEX_KEYS = {
    "name", "description", "model", "model_reasoning_effort", "sandbox_mode", "developer_instructions",
}
CLAUDE_KEYS = {"name", "description", "tools", "model", "effort"}
PROFILE_KEYS = {
    "path", "description", "model", "effort", "sandbox", "tools", "body_sha256", "policy_sha256",
}
PINNED_PATHS = {
    "scripts/verify_repository.py",
    "skills/orchestrate-task/scripts/route_subagent.py",
    "skills/orchestrate-task/tests/routing-cases.json",
}
CODEX_DIRECTORY = "adapters/codex/.codex/agents"
CLAUDE_DIRECTORY = "agents"
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
SAFE_COMPONENT = re.compile(r"[A-Za-z0-9._-]+\Z")
MAX_POLICY_BYTES = 262_144
MAX_JSON_DEPTH = 64
MAX_JSON_NODES = 20_000


class GateError(RuntimeError):
    """A fail-closed trusted invariant violation."""


def diagnostic(value: Any) -> str:
    rendered = json.dumps(value, ensure_ascii=True, sort_keys=True, default=str)
    return rendered[1:-1] if isinstance(value, str) else rendered


def fail(message: str) -> None:
    raise GateError(message)


def exact_keys(label: str, value: dict[str, Any], expected: set[str]) -> None:
    missing = sorted(expected - set(value))
    unknown = sorted(set(value) - expected)
    if missing or unknown:
        fail(f"{label} has invalid keys (missing={diagnostic(missing)}, unknown={diagnostic(unknown)})")


def duplicate_rejector(label: str):
    def hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                fail(f"{label} has duplicate JSON key: {diagnostic(key)}")
            result[key] = value
        return result
    return hook


def check_json_bounds(text: str) -> None:
    depth = 0
    in_string = False
    escaped = False
    for character in text:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
        elif character == '"':
            in_string = True
        elif character in "[{":
            depth += 1
            if depth > MAX_JSON_DEPTH:
                fail(f"JSON exceeds {MAX_JSON_DEPTH} nesting levels")
        elif character in "]}":
            depth -= 1
            if depth < 0:
                fail("JSON has unbalanced delimiters")


def check_json_nodes(value: Any) -> None:
    pending = [value]
    count = 0
    while pending:
        item = pending.pop()
        count += 1
        if count > MAX_JSON_NODES:
            fail(f"JSON exceeds {MAX_JSON_NODES} nodes")
        if isinstance(item, dict):
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)


def load_json_bytes(label: str, content: bytes, *, require_object: bool = True) -> Any:
    try:
        text = content.decode("utf-8", "strict")
        check_json_bounds(text)
        value = json.loads(text, object_pairs_hook=duplicate_rejector(label))
        check_json_nodes(value)
    except GateError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, MemoryError) as error:
        fail(f"{label} is not strict UTF-8 JSON: {diagnostic(str(error))}")
    if require_object and not isinstance(value, dict):
        fail(f"{label} must contain a JSON object")
    return value


def literal_components(relative_path: str) -> tuple[str, ...]:
    if not isinstance(relative_path, str) or not relative_path or relative_path.startswith("/"):
        fail("candidate path must be a non-empty relative literal")
    components = tuple(relative_path.split("/"))
    if any(component in {"", ".", ".."} or not SAFE_COMPONENT.fullmatch(component) for component in components):
        fail(f"candidate path has an unsafe component: {diagnostic(relative_path)}")
    return components


@dataclass
class CandidateReader:
    root_fd: int
    root_identity: tuple[int, int]
    max_file_bytes: int

    @classmethod
    def open(cls, root: str, max_file_bytes: int) -> "CandidateReader":
        if root != CANDIDATE_ROOT:
            fail(f"candidate root must be exactly {CANDIDATE_ROOT}")
        required = ("O_DIRECTORY", "O_NOFOLLOW", "O_NONBLOCK")
        if any(not isinstance(getattr(os, name, None), int) for name in required):
            fail("trusted candidate reading requires POSIX secure-open flags")
        if os.open not in getattr(os, "supports_dir_fd", ()):
            fail("trusted candidate reading requires os.open dir_fd support")
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
        try:
            descriptor = os.open(root, flags)
        except OSError:
            fail("candidate root is missing, inaccessible, or a symlink")
        metadata = os.fstat(descriptor)
        if not stat.S_ISDIR(metadata.st_mode):
            os.close(descriptor)
            fail("candidate root must be a directory")
        return cls(descriptor, (metadata.st_dev, metadata.st_ino), max_file_bytes)

    def close(self) -> None:
        if self.root_fd >= 0:
            os.close(self.root_fd)
            self.root_fd = -1

    def open_directory(self, components: tuple[str, ...]) -> int:
        descriptor = os.dup(self.root_fd)
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
        try:
            for component in components:
                try:
                    child = os.open(component, flags, dir_fd=descriptor)
                except OSError:
                    fail(f"candidate directory is missing, inaccessible, or a symlink: {diagnostic('/'.join(components))}")
                os.close(descriptor)
                descriptor = child
            return descriptor
        except BaseException:
            os.close(descriptor)
            raise

    def list_names(self, relative_directory: str) -> set[str]:
        descriptor = self.open_directory(literal_components(relative_directory))
        try:
            try:
                names = os.listdir(descriptor)
            except OSError:
                fail(f"candidate directory cannot be enumerated: {diagnostic(relative_directory)}")
            if any(not SAFE_COMPONENT.fullmatch(name) for name in names):
                fail(f"candidate directory contains an unsafe name: {diagnostic(relative_directory)}")
            return set(names)
        finally:
            os.close(descriptor)

    def read(self, relative_path: str, *, limit: int | None = None) -> bytes:
        components = literal_components(relative_path)
        directory = self.open_directory(components[:-1])
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)
        try:
            try:
                descriptor = os.open(components[-1], flags, dir_fd=directory)
            except OSError:
                fail(f"candidate file is missing, inaccessible, or a symlink: {diagnostic(relative_path)}")
        finally:
            os.close(directory)
        maximum = self.max_file_bytes if limit is None else min(limit, self.max_file_bytes)
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode):
                fail(f"candidate path must be a regular file: {diagnostic(relative_path)}")
            if before.st_size > maximum:
                fail(f"candidate file exceeds {maximum} bytes: {diagnostic(relative_path)}")
            chunks: list[bytes] = []
            remaining = maximum + 1
            while remaining:
                chunk = os.read(descriptor, min(65_536, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            content = b"".join(chunks)
            after = os.fstat(descriptor)
            before_identity = (before.st_dev, before.st_ino, before.st_mode, before.st_size)
            after_identity = (after.st_dev, after.st_ino, after.st_mode, after.st_size)
            if before_identity != after_identity or len(content) != before.st_size:
                fail(f"candidate file changed while being read: {diagnostic(relative_path)}")
            if len(content) > maximum:
                fail(f"candidate file exceeds {maximum} bytes: {diagnostic(relative_path)}")
            return content
        finally:
            os.close(descriptor)

    def assert_root_stable(self) -> None:
        metadata = os.fstat(self.root_fd)
        if (metadata.st_dev, metadata.st_ino) != self.root_identity:
            fail("candidate root inode changed during trusted validation")


def read_trusted_file(path: str, limit: int) -> bytes:
    target = Path(path)
    try:
        before = target.lstat()
    except OSError:
        fail(f"trusted control is missing: {diagnostic(path)}")
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode) or before.st_size > limit:
        fail(f"trusted control must be a bounded regular non-symlink file: {diagnostic(path)}")
    try:
        content = target.read_bytes()
        after = target.lstat()
    except OSError:
        fail(f"trusted control cannot be read: {diagnostic(path)}")
    if (before.st_dev, before.st_ino, before.st_size) != (after.st_dev, after.st_ino, after.st_size):
        fail(f"trusted control changed while being read: {diagnostic(path)}")
    if len(content) != before.st_size:
        fail(f"trusted control changed while being read: {diagnostic(path)}")
    return content


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def string_map(label: str, value: Any, expected_keys: set[str] | None = None) -> dict[str, str]:
    if not isinstance(value, dict) or any(not isinstance(key, str) or not isinstance(item, str) for key, item in value.items()):
        fail(f"{label} must be an object of strings")
    result = dict(value)
    if expected_keys is not None:
        exact_keys(label, result, expected_keys)
    return result


def load_policy(content: bytes) -> dict[str, Any]:
    policy = load_json_bytes("trusted validation policy", content)
    exact_keys("trusted validation policy", policy, POLICY_KEYS)
    if policy["schema_version"] != 1:
        fail("trusted validation policy schema_version must be 1")
    maximum = policy["max_file_bytes"]
    if not isinstance(maximum, int) or isinstance(maximum, bool) or not 1 <= maximum <= 8_388_608:
        fail("trusted validation policy max_file_bytes is invalid")
    string_map("policy_markers", policy["policy_markers"], {"begin", "end"})
    string_map(
        "policy_rows", policy["policy_rows"],
        {"trust", "command", "isolation", "secrets", "evidence", "identity", "independent_identity"},
    )
    authorizations = string_map("authorization_by_role", policy["authorization_by_role"])
    if len(authorizations) != 11:
        fail("authorization_by_role must contain exactly 11 roles")
    for family in ("codex_profiles", "claude_profiles"):
        profiles = policy[family]
        if not isinstance(profiles, dict) or len(profiles) != 11:
            fail(f"{family} must contain exactly 11 profiles")
        if set(profiles) != set(authorizations):
            fail(f"{family} role names must exactly match authorization_by_role")
        for role, expectation in profiles.items():
            if not isinstance(expectation, dict):
                fail(f"{family}.{role} must be an object")
            exact_keys(f"{family}.{role}", expectation, PROFILE_KEYS)
            for key in ("path", "description", "model", "effort", "sandbox", "body_sha256", "policy_sha256"):
                if not isinstance(expectation[key], str):
                    fail(f"{family}.{role}.{key} must be a string")
            if not isinstance(expectation["tools"], list) or any(not isinstance(item, str) for item in expectation["tools"]):
                fail(f"{family}.{role}.tools must be a string list")
            for key in ("body_sha256", "policy_sha256"):
                if not SHA256.fullmatch(expectation[key]):
                    fail(f"{family}.{role}.{key} must be lowercase SHA256")
            literal_components(expectation["path"])
    pins = string_map("pinned_candidate_files", policy["pinned_candidate_files"], PINNED_PATHS)
    if any(not SHA256.fullmatch(value) for value in pins.values()):
        fail("pinned_candidate_files values must be lowercase SHA256")
    if not isinstance(policy["workflow_sha256"], str) or not SHA256.fullmatch(policy["workflow_sha256"]):
        fail("workflow_sha256 must be lowercase SHA256")
    checkout = policy["checkout_action"]
    if not isinstance(checkout, str) or not re.fullmatch(r"actions/checkout@[0-9a-f]{40}", checkout):
        fail("checkout_action must pin a full lowercase commit SHA")
    images = string_map("validation_images", policy["validation_images"], {"3.11", "3.12"})
    if any("@sha256:" not in value or not SHA256.fullmatch(value.rsplit("@sha256:", 1)[-1]) for value in images.values()):
        fail("validation_images must contain exact digest references")
    return policy


def decode_utf8(label: str, content: bytes) -> str:
    try:
        return content.decode("utf-8", "strict")
    except UnicodeDecodeError as error:
        fail(f"{label} must be UTF-8: {diagnostic(str(error))}")


def extract_policy_block(label: str, body: str, policy: dict[str, Any], role: str) -> str:
    markers = policy["policy_markers"]
    begin, end = markers["begin"], markers["end"]
    if body.count(begin) != 1 or body.count(end) != 1:
        fail(f"{label} must contain exactly one trusted policy block")
    start = body.index(begin)
    finish = body.index(end, start) + len(end)
    rows = policy["policy_rows"]
    identity = rows["independent_identity"] if role in {"awb_verifier", "awb_reviewer", "awb_security_reviewer"} else rows["identity"]
    expected = "\n".join((
        begin, f"trust={rows['trust']}", f"command={rows['command']}",
        f"isolation={rows['isolation']}", f"authorization={policy['authorization_by_role'][role]}",
        f"secrets={rows['secrets']}", f"evidence={rows['evidence']}", f"identity={identity}", end,
    ))
    actual = body[start:finish]
    if actual != expected:
        fail(f"{label} trusted policy block differs from the immutable policy")
    return actual


def parse_frontmatter(label: str, text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        fail(f"{label} must start with frontmatter")
    raw, separator, body = text[4:].partition("\n---\n")
    if not separator:
        fail(f"{label} has unterminated frontmatter")
    values: dict[str, str] = {}
    for line in raw.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, marker, value = line.partition(":")
        key = key.strip()
        if not marker or not key or not value.strip() or key in values:
            fail(f"{label} has unsupported or duplicate frontmatter")
        if key not in CLAUDE_KEYS:
            fail(f"{label} has unknown frontmatter key: {diagnostic(key)}")
        values[key] = value.strip().strip('"')
    exact_keys(label, values, CLAUDE_KEYS)
    return values, body


def validate_profiles(reader: CandidateReader, policy: dict[str, Any]) -> None:
    codex_names = {Path(item["path"]).name for item in policy["codex_profiles"].values()}
    claude_names = {Path(item["path"]).name for item in policy["claude_profiles"].values()}
    if reader.list_names(CODEX_DIRECTORY) != codex_names:
        fail("candidate Codex profile filenames differ from the exact trusted set")
    if reader.list_names(CLAUDE_DIRECTORY) != claude_names:
        fail("candidate Claude profile filenames differ from the exact trusted set")
    for role, expectation in policy["codex_profiles"].items():
        label = expectation["path"]
        try:
            parsed = tomllib.loads(decode_utf8(label, reader.read(label)))
        except tomllib.TOMLDecodeError as error:
            fail(f"{label} is not strict TOML: {diagnostic(str(error))}")
        if not isinstance(parsed, dict):
            fail(f"{label} must contain a TOML table")
        exact_keys(label, parsed, CODEX_KEYS)
        if any(not isinstance(parsed.get(key), str) for key in CODEX_KEYS):
            fail(f"{label} profile values must all be strings")
        body = parsed["developer_instructions"]
        actual = {
            "path": label, "description": parsed["description"], "model": parsed["model"],
            "effort": parsed["model_reasoning_effort"], "sandbox": parsed["sandbox_mode"], "tools": [],
            "body_sha256": sha256(body.encode()),
            "policy_sha256": sha256(extract_policy_block(label, body, policy, role).encode()),
        }
        if parsed["name"] != role or actual != expectation:
            fail(f"{label} complete trusted profile expectation differs")
    for role, expectation in policy["claude_profiles"].items():
        label = expectation["path"]
        frontmatter, body = parse_frontmatter(label, decode_utf8(label, reader.read(label)))
        tools = sorted(item.strip() for item in frontmatter["tools"].split(",") if item.strip())
        actual = {
            "path": label, "description": frontmatter["description"], "model": frontmatter["model"],
            "effort": frontmatter["effort"], "sandbox": "", "tools": tools,
            "body_sha256": sha256(body.encode()),
            "policy_sha256": sha256(extract_policy_block(label, body, policy, role).encode()),
        }
        if frontmatter["name"].replace("-", "_") != role or actual != expectation:
            fail(f"{label} complete trusted profile expectation differs")


def validate(*, candidate_root: str, policy_path: str, trusted_gate_path: str,
             trusted_launcher_path: str, trusted_workflow_path: str) -> None:
    trusted_policy = read_trusted_file(policy_path, MAX_POLICY_BYTES)
    policy = load_policy(trusted_policy)
    reader = CandidateReader.open(candidate_root, policy["max_file_bytes"])
    try:
        controls = {
            "gate": read_trusted_file(trusted_gate_path, policy["max_file_bytes"]),
            "policy": trusted_policy,
            "launcher": read_trusted_file(trusted_launcher_path, policy["max_file_bytes"]),
            "workflow": read_trusted_file(trusted_workflow_path, policy["max_file_bytes"]),
        }
        for name, relative_path in CONTROL_PATHS.items():
            if reader.read(relative_path) != controls[name]:
                fail(f"candidate trusted control differs from the base branch: {diagnostic(relative_path)}")
        if sha256(controls["workflow"]) != policy["workflow_sha256"]:
            fail("trusted workflow does not match workflow_sha256")
        for relative_path, expected_hash in policy["pinned_candidate_files"].items():
            content = reader.read(relative_path)
            if sha256(content) != expected_hash:
                fail(f"pinned candidate file differs: {diagnostic(relative_path)}")
            if relative_path.endswith(".json"):
                load_json_bytes(relative_path, content, require_object=False)
        validate_profiles(reader, policy)
        reader.assert_root_stable()
    finally:
        reader.close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-root", required=True)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--trusted-gate", required=True)
    parser.add_argument("--trusted-launcher", required=True)
    parser.add_argument("--trusted-workflow", required=True)
    arguments = parser.parse_args(argv)
    try:
        validate(
            candidate_root=arguments.candidate_root, policy_path=arguments.policy,
            trusted_gate_path=arguments.trusted_gate, trusted_launcher_path=arguments.trusted_launcher,
            trusted_workflow_path=arguments.trusted_workflow,
        )
    except GateError as error:
        print(f"ERROR: {diagnostic(str(error))}", file=sys.stderr)
        raise SystemExit(1)
    print("Trusted repository invariants passed.")


if __name__ == "__main__":
    main()
