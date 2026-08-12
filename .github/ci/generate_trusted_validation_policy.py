#!/usr/bin/env python3
"""Generate a deterministic trusted-validation policy proposal on stdout.

This tool is deliberately non-authoritative.  It reads a checkout, emits one
proposal to stdout, and never writes files or uses the network.  A protected
base update still requires review of the complete generated policy and digest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import tomllib
from pathlib import Path
from typing import Any


MAX_POLICY_BYTES = 262_144
MAX_SURFACE_NODES = 4_096
MAX_SURFACE_DEPTH = 32
SAFE_COMPONENT = re.compile(r"[A-Za-z0-9._-]+\Z")
SHA256_HEX = re.compile(r"[0-9a-f]{64}\Z")
PROTECTED_ROOTS = (
    ".agents",
    ".claude-plugin",
    ".codex-plugin",
    ".github",
    "adapters/codex/.codex",
    "agents",
    "scripts",
    "skills",
)
TRUSTED_COPY_PATHS = {
    ".github/ci/run_sandboxed_validation.py",
    ".github/ci/trusted_invariant_gate.py",
    ".github/ci/trusted_validation_policy.json",
    ".github/workflows/validate.yml",
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
RECOGNIZED_SURFACE_RULES = {
    "adapter_exceptions": ["adapters/codex/.codex"],
    "ignored_root_paths": [".git"],
    "instruction_directory_names": [
        ".agents", ".claude", ".codex", ".github", "agents", "commands", "hooks", "skills", "workflows"
    ],
    "instruction_file_names": [".mcp.json", "AGENTS.md", "AGENTS.override.md", "CLAUDE.md", "SKILL.md"],
    "max_depth": MAX_SURFACE_DEPTH,
    "max_nodes": MAX_SURFACE_NODES,
}
CONTRACT_MARKERS = {
    "README.md": (
        ("trust-summary", "<!-- BEGIN TRUSTED VALIDATION SUMMARY -->", "<!-- END TRUSTED VALIDATION SUMMARY -->"),
    ),
    "CONTRIBUTING.md": (
        ("protected-set", "<!-- BEGIN TRUSTED PROTECTED SET -->", "<!-- END TRUSTED PROTECTED SET -->"),
        ("initial-bootstrap", "<!-- BEGIN TRUSTED INITIAL BOOTSTRAP -->", "<!-- END TRUSTED INITIAL BOOTSTRAP -->"),
        ("protected-update", "<!-- BEGIN TRUSTED PROTECTED UPDATE -->", "<!-- END TRUSTED PROTECTED UPDATE -->"),
        ("emergency-recovery", "<!-- BEGIN TRUSTED EMERGENCY RECOVERY -->", "<!-- END TRUSTED EMERGENCY RECOVERY -->"),
    ),
}
SURFACE_RULE_KEYS = {
    "adapter_exceptions", "ignored_root_paths", "instruction_directory_names",
    "instruction_file_names", "max_depth", "max_nodes",
}


class ProposalError(RuntimeError):
    """A deterministic policy proposal cannot be produced safely."""


def fail(message: str) -> None:
    raise ProposalError(message)


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def policy_input_sha256(policy: dict[str, Any]) -> str:
    try:
        payload = {key: policy[key] for key in POLICY_INPUT_KEYS}
    except KeyError as error:
        fail(f"trusted policy input is missing {error.args[0]!r}")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return sha256(canonical)


def relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def safe_components(path: str) -> None:
    components = path.split("/")
    if not path or path.startswith("/") or any(
        component in {"", ".", ".."} or not SAFE_COMPONENT.fullmatch(component) for component in components
    ):
        fail(f"unsafe protected path: {path!r}")
    if len(components) > MAX_SURFACE_DEPTH:
        fail(f"protected path exceeds {MAX_SURFACE_DEPTH} components: {path!r}")


def strict_file(root: Path, path: Path, maximum: int) -> tuple[bytes, os.stat_result]:
    label = relative(root, path)
    safe_components(label)
    try:
        before = path.lstat()
    except OSError as error:
        fail(f"cannot inspect {label!r}: {error}")
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        fail(f"protected file must be a regular non-symlink: {label!r}")
    if before.st_size > maximum:
        fail(f"protected file exceeds {maximum} bytes: {label!r}")
    try:
        content = path.read_bytes()
        after = path.lstat()
        content.decode("utf-8", "strict")
    except (OSError, UnicodeDecodeError) as error:
        fail(f"protected file is unreadable or not UTF-8: {label!r}: {error}")
    identity_before = (before.st_dev, before.st_ino, before.st_mode, before.st_size)
    identity_after = (after.st_dev, after.st_ino, after.st_mode, after.st_size)
    if identity_before != identity_after or len(content) != before.st_size:
        fail(f"protected file changed while being read: {label!r}")
    return content, before


def collect_inventory(root: Path, maximum: int) -> list[dict[str, Any]]:
    inventory: list[dict[str, Any]] = []
    nodes = 0
    for root_name in PROTECTED_ROOTS:
        root_path = root / root_name
        safe_components(root_name)
        try:
            root_metadata = root_path.lstat()
        except OSError as error:
            fail(f"protected root is missing: {root_name!r}: {error}")
        if stat.S_ISLNK(root_metadata.st_mode) or not stat.S_ISDIR(root_metadata.st_mode):
            fail(f"protected root must be an ordinary directory: {root_name!r}")
        pending = [root_path]
        while pending:
            directory = pending.pop()
            directory_label = relative(root, directory)
            directory_metadata = directory.lstat()
            nodes += 1
            if nodes > MAX_SURFACE_NODES:
                fail(f"protected inventory exceeds {MAX_SURFACE_NODES} nodes")
            inventory.append({
                "binding": "inventory",
                "executable": bool(directory_metadata.st_mode & 0o111),
                "kind": "directory",
                "path": directory_label,
            })
            try:
                children = sorted(directory.iterdir(), key=lambda item: item.name)
            except OSError as error:
                fail(f"protected directory cannot be enumerated: {directory_label!r}: {error}")
            child_directories: list[Path] = []
            for child in children:
                label = relative(root, child)
                safe_components(label)
                metadata = child.lstat()
                if stat.S_ISLNK(metadata.st_mode):
                    fail(f"protected inventory cannot contain a symlink: {label!r}")
                if stat.S_ISDIR(metadata.st_mode):
                    child_directories.append(child)
                    continue
                if not stat.S_ISREG(metadata.st_mode):
                    fail(f"protected inventory cannot contain a special file: {label!r}")
                nodes += 1
                if nodes > MAX_SURFACE_NODES:
                    fail(f"protected inventory exceeds {MAX_SURFACE_NODES} nodes")
                content, stable = strict_file(root, child, maximum)
                binding = "trusted-copy" if label in TRUSTED_COPY_PATHS else "sha256"
                entry: dict[str, Any] = {
                    "binding": binding,
                    "executable": bool(stable.st_mode & 0o111),
                    "kind": "file",
                    "path": label,
                }
                if binding == "sha256":
                    entry["sha256"] = sha256(content)
                inventory.append(entry)
            pending.extend(reversed(child_directories))
    return sorted(inventory, key=lambda entry: entry["path"])


def protected_set_digest(inventory: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for entry in sorted(inventory, key=lambda item: item["path"]):
        fields = (
            entry["path"], entry["kind"], entry["binding"], entry.get("sha256", ""),
            "true" if entry["executable"] else "false",
        )
        digest.update("\0".join(fields).encode("utf-8"))
    return digest.hexdigest()


def extract_policy_block(body: str, begin: str, end: str) -> str:
    if body.count(begin) != 1 or body.count(end) != 1:
        fail("profile must contain exactly one canonical trusted policy block")
    start = body.index(begin)
    finish = body.index(end, start) + len(end)
    return body[start:finish]


def parse_claude(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        fail("Claude profile must start with frontmatter")
    raw, separator, body = text[4:].partition("\n---\n")
    if not separator:
        fail("Claude profile frontmatter is unterminated")
    values: dict[str, str] = {}
    for line in raw.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, marker, value = line.partition(":")
        key = key.strip()
        if not marker or not key or not value.strip() or key in values:
            fail("Claude profile contains unsupported or duplicate frontmatter")
        values[key] = value.strip().strip('"')
    return values, body


def derive_profiles(root: Path, seed: dict[str, Any], maximum: int) -> tuple[dict[str, Any], dict[str, Any]]:
    markers = seed["policy_markers"]
    authorizations = seed["authorization_by_role"]
    codex: dict[str, Any] = {}
    claude: dict[str, Any] = {}
    for role in sorted(authorizations):
        codex_path = root / "adapters/codex/.codex/agents" / f"{role.replace('_', '-')}.toml"
        codex_content, _ = strict_file(root, codex_path, maximum)
        try:
            parsed = tomllib.loads(codex_content.decode("utf-8"))
        except tomllib.TOMLDecodeError as error:
            fail(f"invalid Codex profile {relative(root, codex_path)!r}: {error}")
        body = parsed["developer_instructions"]
        block = extract_policy_block(body, markers["begin"], markers["end"])
        codex[role] = {
            "body_sha256": sha256(body.encode()),
            "description": parsed["description"],
            "effort": parsed["model_reasoning_effort"],
            "model": parsed["model"],
            "path": relative(root, codex_path),
            "policy_sha256": sha256(block.encode()),
            "sandbox": parsed["sandbox_mode"],
            "tools": [],
        }

        claude_path = root / "agents" / f"{role.replace('_', '-')}.md"
        claude_content, _ = strict_file(root, claude_path, maximum)
        frontmatter, body = parse_claude(claude_content.decode("utf-8"))
        block = extract_policy_block(body, markers["begin"], markers["end"])
        claude[role] = {
            "body_sha256": sha256(body.encode()),
            "description": frontmatter["description"],
            "effort": frontmatter["effort"],
            "model": frontmatter["model"],
            "path": relative(root, claude_path),
            "policy_sha256": sha256(block.encode()),
            "sandbox": "",
            "tools": sorted(item.strip() for item in frontmatter["tools"].split(",") if item.strip()),
        }
    return codex, claude


def inventory_listing(inventory: list[dict[str, Any]]) -> str:
    lines = []
    for entry in inventory:
        lines.append(
            f"{entry['kind']} {entry['binding']} executable={'true' if entry['executable'] else 'false'} {entry['path']}"
        )
    return "\n".join(lines)


def document_contracts_match(root: Path, contracts: Any, maximum: int) -> bool:
    """Return whether the checkout still contains the policy's exact marked blocks."""
    if not isinstance(contracts, list):
        return False
    for contract in contracts:
        if not isinstance(contract, dict) or set(contract) != {"begin", "content", "end", "id", "path"}:
            return False
        try:
            content, _ = strict_file(root, root / contract["path"], maximum)
            body = content.decode("utf-8", "strict")
        except (KeyError, UnicodeDecodeError, ProposalError):
            return False
        begin, end = contract["begin"], contract["end"]
        if not isinstance(begin, str) or not isinstance(end, str) or body.count(begin) != 1 or body.count(end) != 1:
            return False
        start = body.index(begin)
        finish = body.index(end, start) + len(end)
        if body[start:finish] != begin + "\n" + contract["content"] + "\n" + end:
            return False
    return True


def document_contracts(
    inventory: list[dict[str, Any]], policy_version: int, set_digest: str
) -> list[dict[str, str]]:
    # Keep the protected documentation concise and mechanically reproducible.
    # The trusted gate compares these exact marked blocks; surrounding prose may evolve.
    concise = {
        ("README.md", "trust-summary"): "\n".join((
            "## Trusted validation boundary", "",
            f"The authoritative pull-request gate uses reviewed base-branch controls and policy version `{policy_version}` with protected-set digest `{set_digest}`. It binds the complete exported skill, both profile families, manifests, validator, router, replay data, CI controls, generator, file types, and executable bits; it also rejects unallowlisted repository instruction and automation surfaces.", "",
            "There is no preceding trusted invariant gate for the initial activation because GitHub reads the `pull_request_target` workflow from the base branch. Initial activation and every later protected-set update therefore use the separately authorized procedure in [CONTRIBUTING.md](CONTRIBUTING.md); local checks never prove live activation.",
        )),
        ("CONTRIBUTING.md", "protected-set"): "\n".join((
            "### Complete protected validation set", "",
            f"The authoritative policy is version `{policy_version}` and its `protected_set_digest` is `{set_digest}`. The exact protected roots are `.agents`, `.claude-plugin`, `.codex-plugin`, `.github`, `adapters/codex/.codex`, `agents`, `scripts`, and `skills`. The trusted inventory binds every file and directory below those roots, including manifests, CI controls, generator, skills/references/scripts/tests, validator/router/replay data, and all 22 profile files; file hashes and executable bits are protected and unallowlisted instruction/automation surfaces fail closed.",
        )),
        ("CONTRIBUTING.md", "initial-bootstrap"): "\n".join((
            "### Initial protected-base activation", "",
            "There is no preceding trusted invariant gate for the initial activation because GitHub reads a `pull_request_target` workflow from the base branch. Local checks do not prove live activation. The separately authorized procedure must freeze merges; disable the old host-executing `Validate` workflow and cancel in-flight runs; prepare and independently review a clean protected-base change; regenerate policy version and protected-set digest; land through protected-base or administrator access; re-enable the replacement workflow; atomically migrate required status to `Trusted invariants (authoritative)`; run controlled positive and negative fork and same-repository pull requests; record run URLs, SHAs, policy/digest, and ruleset evidence; then unfreeze merges.",
        )),
        ("CONTRIBUTING.md", "protected-update"): "\n".join((
            "### Recurring protected-set update", "",
            "Any change to the complete derived protected set—including manifests, the exported skills tree, profiles/adapters, validator/router/replay, CI controls, generator, or these document contracts—requires the same protected-base procedure: freeze merges, disable/cancel validation, regenerate and increment policy, independently review contained positive/negative checks, land through protected-base/admin access, re-enable and migrate the required authoritative status, run controlled fork and same-repository enforcement tests, record evidence, and unfreeze. For an exported checkout, the generator requires a separately preserved baseline outside the candidate tree and its reviewed SHA-256, for example `python3 .github/ci/generate_trusted_validation_policy.py --root /path/to/candidate --previous-policy /path/to/previous-policy.json --previous-policy-sha256 <64-hex-digest>`; it rejects the candidate policy as a baseline. Ordinary pull requests must not modify policy and its subjects together.",
        )),
        ("CONTRIBUTING.md", "emergency-recovery"): "\n".join((
            "### Emergency recovery", "",
            "On containment failure or trusted-policy drift, freeze merges, disable the affected workflow, cancel in-flight runs, preserve the authoritative required context, restore or repair the complete protected set through protected-base/admin access, regenerate and review policy, re-enable validation, repeat controlled positive and negative fork and same-repository tests, record evidence, and unfreeze only after acceptance. Never execute candidate code on the host, unpin images, trust candidate policy, or remove the required merge block.",
        )),
    }
    return [
        {"begin": begin, "content": concise[(path, identifier)], "end": end, "id": identifier, "path": path}
        for path in sorted(CONTRACT_MARKERS)
        for identifier, begin, end in CONTRACT_MARKERS[path]
    ]
    listing = inventory_listing(inventory)
    root_listing = "\n".join(f"- `{path}`" for path in PROTECTED_ROOTS)
    contents = {
        ("README.md", "trust-summary"): "\n".join((
            "## Trusted validation boundary",
            "",
            f"The authoritative pull-request gate uses reviewed base-branch controls and policy version `{policy_version}` with protected-set digest `{set_digest}`. It binds the complete exported skill, both profile families, manifests, validator, router, replay data, CI controls, generator, file types, and executable bits; it also rejects unallowlisted repository instruction and automation surfaces.",
            "",
            "There is no preceding trusted invariant gate for the initial activation because GitHub reads the `pull_request_target` workflow from the base branch. Initial activation and every later protected-set update therefore use the separately authorized procedure in [CONTRIBUTING.md](CONTRIBUTING.md); local checks never prove live activation.",
        )),
        ("CONTRIBUTING.md", "protected-set"): "\n".join((
            "### Complete protected validation set",
            "",
            f"The authoritative policy is version `{policy_version}` and its `protected_set_digest` is `{set_digest}`. The digest is SHA-256 over the path-sorted inventory, concatenating each entry as `path NUL kind NUL binding NUL digest-or-empty NUL executable` without an additional record separator.",
            "",
            "The exact inventory roots are:",
            "",
            root_listing,
            "",
            "The exact protected inventory is:",
            "",
            "```text",
            listing,
            "```",
            "",
            "Directory entries are exact inventory contracts. File contents use either an exact SHA-256 binding or an individually mounted trusted base copy, and every entry binds whether any executable bit is set. The marked documentation contracts are separately rendered from the policy and byte-compared by the trusted gate.",
        )),
        ("CONTRIBUTING.md", "initial-bootstrap"): "\n".join((
            "### Initial protected-base activation",
            "",
            "There is no preceding trusted invariant gate for the initial activation because GitHub reads a `pull_request_target` workflow from the base branch. Local checks do not prove live activation. The separately authorized initial activation must:",
            "",
            "1. Freeze merges.",
            "2. Disable the old host-executing `Validate` workflow and cancel all in-flight runs.",
            "3. Prepare a reviewed, clean protected-base change containing the complete protected set.",
            "4. Regenerate the inventory, increment the policy version, and verify the protected-set digest.",
            "5. Run contained local positive and negative checks and obtain an independent security review; record that this is local evidence only.",
            "6. Use a separately authorized protected-base or administrator landing for the reviewed exact change.",
            "7. Re-enable the replacement `Validate` workflow.",
            "8. Atomically migrate the required status check to `Trusted invariants (authoritative)`.",
            "9. Run controlled positive and negative tests from one fork pull request and one same-repository pull request.",
            "10. Record run URLs, commit SHAs, policy version, protected-set digest, and ruleset evidence before unfreezing merges.",
        )),
        ("CONTRIBUTING.md", "protected-update"): "\n".join((
            "### Recurring protected-set update",
            "",
            "Every later change to any entry or contract in the complete protected set requires the same fail-closed protected-base procedure. Freeze merges; disable the protected workflow and cancel in-flight runs; prepare one clean reviewed update; regenerate the complete inventory, increment the policy version, and verify the digest; run contained local positive and negative checks plus independent security review; separately authorize the protected-base or administrator landing; re-enable the workflow and atomically preserve or migrate the required authoritative status; run controlled positive and negative fork and same-repository pull requests; record run URLs, SHAs, policy version, digest, and ruleset evidence; then unfreeze merges. An ordinary pull request must not update only a subset or rely on the candidate validator as authority.",
        )),
        ("CONTRIBUTING.md", "emergency-recovery"): "\n".join((
            "### Emergency recovery",
            "",
            "On containment failure or trusted-policy drift, freeze merges, disable the affected workflow, and cancel in-flight runs. Never recover by executing candidate code on the Actions host. Diagnose from trusted evidence, prepare a clean complete protected-set repair or restore the last reviewed complete set, regenerate the policy and digest, rerun contained positive and negative checks, and obtain independent security review. Land only through separately authorized protected-base or administrator access, re-enable and atomically restore the authoritative required status, repeat controlled fork and same-repository tests, record URLs/SHAs/policy/digest/ruleset evidence, and unfreeze only after the evidence is accepted. Treat rollback as unverified unless that exact recovery path was exercised.",
        )),
    }
    contracts: list[dict[str, str]] = []
    for path in sorted(CONTRACT_MARKERS):
        for identifier, begin, end in CONTRACT_MARKERS[path]:
            contracts.append({
                "begin": begin,
                "content": contents[(path, identifier)],
                "end": end,
                "id": identifier,
                "path": path,
            })
    return contracts


def previous_policy(
    root: Path,
    maximum: int,
    path: Path | None,
    candidate_policy_path: Path,
    expected_sha256: str | None,
) -> dict[str, Any]:
    if path is None:
        fail("an independently preserved previous policy and reviewed SHA-256 are required")
    else:
        baseline = path.expanduser()
        if not baseline.is_absolute():
            baseline = Path.cwd() / baseline
        baseline = baseline.resolve(strict=False)
        candidate_root = root.resolve(strict=True)
        candidate_policy = candidate_policy_path.resolve(strict=True)
        try:
            baseline.relative_to(candidate_root)
        except ValueError:
            pass
        else:
            fail("explicit previous policy must be outside the candidate checkout")
        try:
            if os.path.samefile(baseline, candidate_policy):
                fail("explicit previous policy must not be the candidate policy")
            metadata = baseline.lstat()
        except FileNotFoundError:
            fail("explicit previous policy is missing")
        except OSError as error:
            fail(f"explicit previous policy cannot be inspected: {error}")
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            fail("explicit previous policy must be a regular non-symlink file")
        if metadata.st_size > maximum:
            fail("explicit previous policy exceeds the configured size limit")
        if expected_sha256 is None or not SHA256_HEX.fullmatch(expected_sha256):
            fail("explicit previous policy requires a reviewed 64-character SHA-256 identity")
        try:
            content = baseline.read_bytes()
            after = baseline.lstat()
        except OSError as error:
            fail(f"explicit previous policy cannot be read: {error}")
        if (metadata.st_dev, metadata.st_ino, metadata.st_size, metadata.st_mode) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mode
        ):
            fail("explicit previous policy changed while being read")
        if sha256(content) != expected_sha256:
            fail("explicit previous policy SHA-256 does not match the reviewed identity")
    try:
        value = json.loads(content.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        fail(f"independent previous policy is invalid: {error}")
    if not isinstance(value, dict):
        fail("independent previous policy must be an object")
    return value


def generate(
    root: Path,
    policy_version: int | None,
    previous_policy_path: Path | None = None,
    previous_policy_sha256: str | None = None,
) -> bytes:
    policy_path = root / ".github/ci/trusted_validation_policy.json"
    content, _ = strict_file(root, policy_path, MAX_POLICY_BYTES)
    try:
        seed = json.loads(content.decode("utf-8"))
    except json.JSONDecodeError as error:
        fail(f"existing policy is not JSON: {error}")
    maximum = seed["max_file_bytes"]
    baseline = previous_policy(
        root, maximum, previous_policy_path, policy_path, previous_policy_sha256
    )
    inventory = collect_inventory(root, maximum)
    digest = protected_set_digest(inventory)
    codex, claude = derive_profiles(root, seed, maximum)
    pinned_candidate_files = {
        path: sha256(strict_file(root, root / path, maximum)[0])
        for path in sorted(seed["pinned_candidate_files"])
    }
    workflow_sha256 = sha256(strict_file(root, root / ".github/workflows/validate.yml", maximum)[0])
    trusted_copy_sha256 = {
        path: sha256(strict_file(root, root / path, maximum)[0])
        for path in sorted(TRUSTED_COPY_SHA256_PATHS)
    }
    current_policy_input_sha256 = policy_input_sha256(seed)
    current_version = seed.get("policy_version", 1)
    baseline_version = baseline.get("policy_version", 1)
    if not isinstance(current_version, int) or current_version < 1 or not isinstance(baseline_version, int) or baseline_version < 1:
        fail("policy version is invalid")
    baseline_trusted_copy_sha256 = baseline.get("trusted_copy_sha256", {})
    baseline_policy_input_sha256 = baseline.get("policy_input_sha256", policy_input_sha256(baseline))
    baseline_pins = baseline.get("pinned_candidate_files", {})
    baseline_workflow_sha256 = baseline.get("workflow_sha256")
    protected_state_changed = any((
        baseline.get("schema_version") != 2,
        baseline.get("protected_set_digest") != digest,
        baseline.get("protected_surface_roots") != list(PROTECTED_ROOTS),
        baseline.get("recognized_surface_rules") != RECOGNIZED_SURFACE_RULES,
        baseline_pins != pinned_candidate_files,
        baseline_workflow_sha256 != workflow_sha256,
        baseline_trusted_copy_sha256 != trusted_copy_sha256,
        baseline_policy_input_sha256 != current_policy_input_sha256,
        baseline.get("codex_profiles") != codex,
        baseline.get("claude_profiles") != claude,
        baseline.get("protected_document_contracts") != seed.get("protected_document_contracts"),
    ))
    if protected_state_changed:
        if policy_version is None:
            if current_version <= baseline_version:
                fail("protected validation state changed; policy version must increase")
            version = current_version
        elif not isinstance(policy_version, int) or policy_version <= baseline_version:
            fail("protected validation state changed; policy version must increase")
        else:
            version = policy_version
    else:
        version = current_version if policy_version is None else policy_version
        if not isinstance(version, int) or version < baseline_version:
            fail("policy version cannot decrease")
    if not 2 <= version <= 1_000_000:
        fail("policy version must be between 2 and 1000000")
    policy = {
        "authorization_by_role": seed["authorization_by_role"],
        "checkout_action": seed["checkout_action"],
        "claude_profiles": claude,
        "codex_profiles": codex,
        "max_file_bytes": maximum,
        "policy_markers": seed["policy_markers"],
        "policy_rows": seed["policy_rows"],
        "pinned_candidate_files": pinned_candidate_files,
        "policy_input_sha256": current_policy_input_sha256,
        "policy_version": version,
        "protected_document_contracts": document_contracts(inventory, version, digest),
        "protected_set_digest": digest,
        "protected_surface_inventory": inventory,
        "protected_surface_roots": list(PROTECTED_ROOTS),
        "recognized_surface_rules": RECOGNIZED_SURFACE_RULES,
        "schema_version": 2,
        "trusted_copy_sha256": trusted_copy_sha256,
        "workflow_sha256": workflow_sha256,
        "validation_images": seed["validation_images"],
    }
    proposal = (json.dumps(policy, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode("utf-8")
    if len(proposal) > MAX_POLICY_BYTES:
        fail(f"generated policy exceeds {MAX_POLICY_BYTES} bytes")
    return proposal


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=os.fspath(Path(__file__).resolve().parents[2]))
    parser.add_argument("--policy-version", type=int)
    parser.add_argument("--previous-policy", type=Path)
    parser.add_argument("--previous-policy-sha256")
    arguments = parser.parse_args(argv)
    root = Path(arguments.root)
    if not root.is_absolute():
        root = (Path.cwd() / root).resolve()
    try:
        proposal = generate(
            root,
            arguments.policy_version,
            arguments.previous_policy,
            arguments.previous_policy_sha256,
        )
        sys.stdout.buffer.write(proposal)
    except (ProposalError, KeyError, TypeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
