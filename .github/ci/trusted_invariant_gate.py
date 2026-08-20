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
POLICY_KEYS_V1 = {
    "schema_version", "max_file_bytes", "policy_markers", "policy_rows",
    "authorization_by_role", "codex_profiles", "claude_profiles",
    "pinned_candidate_files", "workflow_sha256", "checkout_action", "validation_images",
}
POLICY_KEYS_V2 = POLICY_KEYS_V1 | {
    "policy_version", "protected_document_contracts", "protected_set_digest",
    "protected_surface_inventory", "protected_surface_roots", "recognized_surface_rules",
    "policy_input_sha256", "trusted_copy_sha256",
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
CLAUDE_REQUIRED_KEYS = {"name", "description", "tools", "model", "effort"}
CLAUDE_KEYS = CLAUDE_REQUIRED_KEYS | {"skills"}
PROFILE_KEYS = {
    "path", "description", "model", "effort", "sandbox", "tools", "body_sha256", "policy_sha256",
}
EXPECTED_ROLE_COUNT = 12
OWNERSHIP_PROBE_ROLE = "awb_ownership_probe"
OWNERSHIP_PROBE_AUTHORIZATION = (
    "deny network, credentials, messages, push, deploy, global configuration, destructive actions, and external actions"
)
OWNERSHIP_PROBE_PROFILES = {
    "codex_profiles": {
        "description": "Bounded path-metadata ownership probe for three closed deployment artifact classes.",
        "effort": "low",
        "model": "gpt-5.6-luna",
        "path": "adapters/codex/.codex/agents/awb-ownership-probe.toml",
        "sandbox": "read-only",
        "tools": [],
    },
    "claude_profiles": {
        "description": "Bounded path-metadata ownership probe for three closed deployment artifact classes.",
        "effort": "low",
        "model": "haiku",
        "path": "agents/awb-ownership-probe.md",
        "sandbox": "",
        "tools": ["Glob"],
    },
}
PINNED_PATHS = {
    "scripts/verify_repository.py",
    "skills/orchestrate-task/scripts/route_subagent.py",
    "skills/orchestrate-task/tests/routing-cases.json",
    "tests/test_ci_sandbox.py",
    "tests/test_code_review_scope.py",
    "tests/test_verify_repository.py",
}
PROTECTED_ROOTS = (
    ".agents",
    ".claude-plugin",
    ".codex-plugin",
    ".github",
    "adapters/codex/.codex",
    "agents",
    "scripts",
    "skills",
    "tests",
)
CODEX_DIRECTORY = "adapters/codex/.codex/agents"
CLAUDE_DIRECTORY = "agents"
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
SAFE_COMPONENT = re.compile(r"[A-Za-z0-9._-]+\Z")
MAX_POLICY_BYTES = 262_144
MAX_JSON_DEPTH = 64
MAX_JSON_NODES = 20_000
MAX_SURFACE_NODES = 4_096
MAX_SURFACE_DEPTH = 32
SURFACE_RULE_KEYS = {
    "adapter_exceptions", "ignored_root_paths", "instruction_directory_names",
    "instruction_file_names", "max_depth", "max_nodes",
}
EXPECTED_SURFACE_RULES = {
    "adapter_exceptions": ["adapters/codex/.codex"],
    "ignored_root_paths": [".git"],
    "instruction_directory_names": [
        ".agents", ".claude", ".codex", ".github", "agents", "commands", "hooks", "skills", "workflows",
    ],
    "instruction_file_names": [".mcp.json", "AGENTS.md", "AGENTS.override.md", "CLAUDE.md", "SKILL.md"],
    "max_depth": MAX_SURFACE_DEPTH,
    "max_nodes": MAX_SURFACE_NODES,
}
TRUSTED_COPY_SHA256_PATHS = {
    ".github/ci/trusted_invariant_gate.py",
    ".github/ci/run_sandboxed_validation.py",
    ".github/workflows/validate.yml",
}
POLICY_INPUT_KEYS = (
    "authorization_by_role", "checkout_action", "max_file_bytes", "policy_markers",
    "policy_rows", "validation_images",
)


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


def policy_input_sha256(policy: dict[str, Any]) -> str:
    try:
        payload = {key: policy[key] for key in POLICY_INPUT_KEYS}
    except KeyError as error:
        fail(f"trusted policy input is missing {diagnostic(error.args[0])}")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return sha256(canonical)


def string_map(label: str, value: Any, expected_keys: set[str] | None = None) -> dict[str, str]:
    if not isinstance(value, dict) or any(not isinstance(key, str) or not isinstance(item, str) for key, item in value.items()):
        fail(f"{label} must be an object of strings")
    result = dict(value)
    if expected_keys is not None:
        exact_keys(label, result, expected_keys)
    return result


def validate_surface_rules(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        fail("recognized_surface_rules must be an object")
    exact_keys("recognized_surface_rules", value, SURFACE_RULE_KEYS)
    if value != EXPECTED_SURFACE_RULES:
        fail("recognized_surface_rules differ from the immutable trusted contract")
    for key in ("adapter_exceptions", "ignored_root_paths", "instruction_directory_names", "instruction_file_names"):
        if any(not isinstance(item, str) for item in value[key]):
            fail(f"recognized_surface_rules.{key} must contain strings")
    if not isinstance(value["max_depth"], int) or not isinstance(value["max_nodes"], int):
        fail("recognized_surface_rules bounds must be integers")
    return value


def load_policy(content: bytes) -> dict[str, Any]:
    policy = load_json_bytes("trusted validation policy", content)
    schema_version = policy.get("schema_version")
    if schema_version not in {1, 2}:
        fail("trusted validation policy schema_version must be 1 or 2")
    exact_keys("trusted validation policy", policy, POLICY_KEYS_V2 if schema_version == 2 else POLICY_KEYS_V1)
    if schema_version == 2:
        if not isinstance(policy.get("policy_version"), int) or not 2 <= policy["policy_version"] <= 1_000_000:
            fail("trusted validation policy policy_version is invalid")
        inventory = policy.get("protected_surface_inventory")
        roots = policy.get("protected_surface_roots")
        rules = policy.get("recognized_surface_rules")
        contracts = policy.get("protected_document_contracts")
        digest = policy.get("protected_set_digest")
        if not isinstance(inventory, list) or not inventory or len(inventory) > MAX_SURFACE_NODES:
            fail("protected_surface_inventory is invalid")
        if not isinstance(roots, list) or not roots or any(not isinstance(item, str) for item in roots):
            fail("protected_surface_roots is invalid")
        if roots != list(PROTECTED_ROOTS):
            fail("protected_surface_roots differ from the immutable trusted contract")
        if not isinstance(contracts, list) or not isinstance(digest, str) or not SHA256.fullmatch(digest):
            fail("trusted surface rules or document contracts are invalid")
        validate_surface_rules(rules)
        seen: set[str] = set()
        canonical = hashlib.sha256()
        for entry in sorted(inventory, key=lambda item: item.get("path", "")):
            if not isinstance(entry, dict) or set(entry) - {"binding", "executable", "kind", "path", "sha256"}:
                fail("protected inventory entry has invalid keys")
            path = entry.get("path")
            kind = entry.get("kind")
            binding = entry.get("binding")
            executable = entry.get("executable")
            if not isinstance(path, str) or path in seen:
                fail("protected inventory has duplicate or invalid path")
            literal_components(path)
            if kind not in {"file", "directory"} or binding not in {"sha256", "trusted-copy", "inventory"} or not isinstance(executable, bool):
                fail("protected inventory entry is invalid")
            if kind == "file" and binding == "sha256":
                value = entry.get("sha256")
                if not isinstance(value, str) or not SHA256.fullmatch(value):
                    fail("protected inventory file hash is invalid")
            elif "sha256" in entry:
                fail("only sha256-bound files may contain a hash")
            seen.add(path)
            canonical.update("\0".join((path, kind, binding, entry.get("sha256", ""), "true" if executable else "false")).encode())
        if canonical.hexdigest() != digest:
            fail("protected_set_digest does not match the canonical inventory")
        input_hash = policy.get("policy_input_sha256")
        if not isinstance(input_hash, str) or not SHA256.fullmatch(input_hash) or input_hash != policy_input_sha256(policy):
            fail("policy_input_sha256 does not match the canonical trusted inputs")
        trusted_hashes = policy.get("trusted_copy_sha256")
        if not isinstance(trusted_hashes, dict) or set(trusted_hashes) != TRUSTED_COPY_SHA256_PATHS:
            fail("trusted_copy_sha256 must contain the exact trusted controls")
        if any(not isinstance(value, str) or not SHA256.fullmatch(value) for value in trusted_hashes.values()):
            fail("trusted_copy_sha256 values must be lowercase SHA256")
    maximum = policy["max_file_bytes"]
    if not isinstance(maximum, int) or isinstance(maximum, bool) or not 1 <= maximum <= 8_388_608:
        fail("trusted validation policy max_file_bytes is invalid")
    string_map("policy_markers", policy["policy_markers"], {"begin", "end"})
    string_map(
        "policy_rows", policy["policy_rows"],
        {"trust", "command", "isolation", "secrets", "evidence", "identity", "independent_identity"},
    )
    authorizations = string_map("authorization_by_role", policy["authorization_by_role"])
    if len(authorizations) != EXPECTED_ROLE_COUNT:
        fail(f"authorization_by_role must contain exactly {EXPECTED_ROLE_COUNT} roles")
    if authorizations.get(OWNERSHIP_PROBE_ROLE) != OWNERSHIP_PROBE_AUTHORIZATION:
        fail("ownership probe must retain the exact non-operator authorization denial")
    for family in ("codex_profiles", "claude_profiles"):
        profiles = policy[family]
        if not isinstance(profiles, dict) or len(profiles) != EXPECTED_ROLE_COUNT:
            fail(f"{family} must contain exactly {EXPECTED_ROLE_COUNT} profiles")
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
        ownership_probe = profiles.get(OWNERSHIP_PROBE_ROLE)
        expected_probe = OWNERSHIP_PROBE_PROFILES[family]
        if not isinstance(ownership_probe, dict) or {
            key: ownership_probe.get(key) for key in expected_probe
        } != expected_probe:
            fail(f"{family} ownership probe must retain the exact least-privilege profile")
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
    missing = sorted(CLAUDE_REQUIRED_KEYS - set(values))
    unknown = sorted(set(values) - CLAUDE_KEYS)
    if missing or unknown:
        fail(f"{label} has invalid keys (missing={diagnostic(missing)}, unknown={diagnostic(unknown)})")
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


def _surface_walk(reader: CandidateReader, relative_directory: str, *, nodes: list[tuple[str, str, bool]]) -> None:
    """Enumerate one protected tree without following symlinks or specials."""
    if len(nodes) > MAX_SURFACE_NODES:
        fail("protected surface exceeds the bounded node limit")
    directory = reader.open_directory(literal_components(relative_directory))
    try:
        try:
            names = sorted(os.listdir(directory))
        except OSError:
            fail(f"protected surface directory cannot be enumerated: {diagnostic(relative_directory)}")
        for name in names:
            if not SAFE_COMPONENT.fullmatch(name):
                fail(f"protected surface contains an unsafe name: {diagnostic(name)}")
            path = f"{relative_directory}/{name}" if relative_directory else name
            components = literal_components(path)
            if len(components) > MAX_SURFACE_DEPTH:
                fail("protected surface exceeds the bounded depth limit")
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)
            try:
                descriptor = os.open(name, flags, dir_fd=directory)
            except OSError:
                fail(f"protected surface entry cannot be opened safely: {diagnostic(path)}")
            try:
                metadata = os.fstat(descriptor)
                executable = bool(metadata.st_mode & 0o111)
                if stat.S_ISDIR(metadata.st_mode):
                    nodes.append((path, "directory", executable))
                    _surface_walk(reader, path, nodes=nodes)
                elif stat.S_ISREG(metadata.st_mode):
                    if metadata.st_size > reader.max_file_bytes:
                        fail(f"protected surface file is oversized: {diagnostic(path)}")
                    nodes.append((path, "file", executable))
                else:
                    fail(f"protected surface contains a special file: {diagnostic(path)}")
            finally:
                os.close(descriptor)
            if len(nodes) > MAX_SURFACE_NODES:
                fail("protected surface exceeds the bounded node limit")
    finally:
        os.close(directory)


def validate_protected_surfaces(reader: CandidateReader, policy: dict[str, Any]) -> None:
    if policy.get("schema_version") != 2:
        return
    expected = {
        entry["path"]: (entry["kind"], entry["executable"], entry.get("binding"), entry.get("sha256"))
        for entry in policy["protected_surface_inventory"]
    }
    actual: list[tuple[str, str, bool]] = []
    for root in policy["protected_surface_roots"]:
        root_descriptor = reader.open_directory(literal_components(root))
        try:
            root_mode = bool(os.fstat(root_descriptor).st_mode & 0o111)
        finally:
            os.close(root_descriptor)
        actual.append((root, "directory", root_mode))
        _surface_walk(reader, root, nodes=actual)
    actual_map = {path: (kind, executable) for path, kind, executable in actual}
    expected_map = {path: kind for path, (kind, _, _, _) in expected.items()}
    actual_kinds = {path: kind for path, (kind, _) in actual_map.items()}
    if actual_kinds != expected_map:
        missing = sorted(set(expected_map) - set(actual_map))
        extra = sorted(set(actual_map) - set(expected_map))
        fail(f"protected surface inventory differs (missing={diagnostic(missing)}, extra={diagnostic(extra)})")
    for path, expected_kind in expected_map.items():
        if expected_kind != actual_map[path][0]:
            fail(f"protected surface kind differs: {diagnostic(path)}")
        expected_executable = expected[path][1]
        actual_executable = actual_map[path][1]
        if expected_executable != actual_executable:
            fail(f"protected surface executable mode differs: {diagnostic(path)}")
    for path, (_, _, binding, expected_hash) in expected.items():
        if binding == "sha256":
            if sha256(reader.read(path)) != expected_hash:
                fail(f"protected surface hash differs: {diagnostic(path)}")

    # Reject newly introduced harness-recognized authority surfaces anywhere else in the tree.
    rules = validate_surface_rules(policy["recognized_surface_rules"])
    forbidden_files = set(rules["instruction_file_names"])
    forbidden_dirs = set(rules["instruction_directory_names"])
    ignored_root_paths = set(rules["ignored_root_paths"])
    allowed_directory_prefixes = set(policy["protected_surface_roots"]) | set(rules["adapter_exceptions"])
    allowed_paths = set(expected)
    queue = [""]
    seen = 0
    while queue:
        directory = queue.pop()
        descriptor = reader.open_directory(literal_components(directory) if directory else ())
        try:
            try:
                names = sorted(os.listdir(descriptor))
            except OSError:
                fail("candidate tree cannot be enumerated for recognized surfaces")
            for name in names:
                if directory == "" and name in ignored_root_paths:
                    continue
                if not SAFE_COMPONENT.fullmatch(name):
                    fail(f"candidate tree contains an unsafe name: {diagnostic(name)}")
                path = f"{directory}/{name}" if directory else name
                components = literal_components(path)
                if len(components) > MAX_SURFACE_DEPTH:
                    fail("candidate recognized-surface scan exceeds the bounded depth limit")
                seen += 1
                if seen > MAX_SURFACE_NODES:
                    fail("candidate recognized-surface scan exceeds the bounded node limit")
                if name in forbidden_files and path not in allowed_paths:
                    fail(f"unallowlisted instruction surface: {diagnostic(path)}")
                if name in forbidden_dirs and not any(path == root or path.startswith(root + "/") for root in allowed_directory_prefixes):
                    fail(f"unallowlisted instruction directory: {diagnostic(path)}")
                flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)
                try:
                    child = os.open(name, flags, dir_fd=descriptor)
                except OSError:
                    fail(f"candidate tree entry cannot be opened safely: {diagnostic(path)}")
                try:
                    metadata = os.fstat(child)
                    if stat.S_ISDIR(metadata.st_mode):
                        queue.append(path)
                    elif not stat.S_ISREG(metadata.st_mode):
                        fail(f"candidate tree contains a special file: {diagnostic(path)}")
                finally:
                    os.close(child)
        finally:
            os.close(descriptor)

    for contract in policy.get("protected_document_contracts", []):
        if not isinstance(contract, dict) or set(contract) != {"begin", "content", "end", "id", "path"}:
            fail("protected document contract is malformed")
        body = decode_utf8(contract["path"], reader.read(contract["path"]))
        begin, end = contract["begin"], contract["end"]
        if body.count(begin) != 1 or body.count(end) != 1:
            fail(f"protected document contract markers missing: {diagnostic(contract['path'])}")
        start = body.index(begin) + len(begin)
        finish = body.index(end, start)
        if body[start:finish] != "\n" + contract["content"] + "\n":
            fail(f"protected document contract differs: {diagnostic(contract['path'])}")


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
        for name, relative_path in {
            "gate": ".github/ci/trusted_invariant_gate.py",
            "launcher": ".github/ci/run_sandboxed_validation.py",
            "workflow": ".github/workflows/validate.yml",
        }.items():
            if sha256(controls[name]) != policy["trusted_copy_sha256"][relative_path]:
                fail(f"trusted {name} does not match its protected policy hash")
        if sha256(controls["workflow"]) != policy["workflow_sha256"]:
            fail("trusted workflow does not match workflow_sha256")
        for relative_path, expected_hash in policy["pinned_candidate_files"].items():
            content = reader.read(relative_path)
            if sha256(content) != expected_hash:
                fail(f"pinned candidate file differs: {diagnostic(relative_path)}")
            if relative_path.endswith(".json"):
                load_json_bytes(relative_path, content, require_object=False)
        validate_profiles(reader, policy)
        validate_protected_surfaces(reader, policy)
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
