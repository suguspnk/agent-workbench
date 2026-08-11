#!/usr/bin/env python3
"""Validate the structural and safety invariants of a V1 loop proposal."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import stat
import sys
import unicodedata
from pathlib import Path
from typing import Any


MIN_PYTHON = (3, 11)
MAX_INPUT_BYTES = 1_048_576
MAX_STRING_LENGTH = 4096
MAX_LIST_ITEMS = 100
MAX_HOST_LOCATION_LENGTH = 128
MAX_SECRET_ADJACENT_CHARS = 8192
ROOT_FIELDS = {
    "artifact_type",
    "schema_version",
    "proposal_id",
    "objective",
    "evidence_refs",
    "readiness",
    "semantic_review",
    "trigger",
    "inputs",
    "scope",
    "state",
    "acceptance",
    "dry_run",
    "limits",
    "terminal_states",
    "approvals",
    "rollback",
    "metrics",
    "lifecycle",
}
PROPOSAL_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
HOST_MANAGED_LOCATION = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
PORTABLE_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
MANDATORY_PROHIBITED_ACTIONS = frozenset({"activate", "schedule", "install", "publish"})
TERMINAL_STATES = frozenset({"complete", "blocked", "needs-approval", "failed"})
OPERATION_MAP = {
    "workspace.observe": {"category": "observation", "effect": "read-only"},
    "workspace.write": {"category": "local-workspace", "effect": "local-reversible"},
    "external.read": {"category": "external-system", "effect": "read-only"},
    "external.write": {"category": "external-system", "effect": "external-reversible"},
    "credential.read": {"category": "credential-access", "effect": "read-only"},
}
LIFECYCLE_TOKENS = frozenset(
    {
        "activate",
        "activated",
        "activating",
        "activation",
        "activator",
        "enable",
        "enablement",
        "enabled",
        "enabler",
        "enabling",
        "schedule",
        "scheduled",
        "scheduler",
        "scheduling",
        "cron",
        "crontab",
        "timer",
        "timers",
        "periodic",
        "launchd",
        "systemd",
        "install",
        "installed",
        "installer",
        "installation",
        "publish",
        "published",
        "publisher",
        "publishing",
    }
)
DESTRUCTIVE_TOKENS = frozenset(
    {"delete", "destroy", "revoke", "wipe", "terminate", "drop", "purge", "truncate", "erase"}
)
SENSITIVE_PATH_TOKENS = frozenset(
    {
        "credential", "credentials", "secret", "secrets", "token", "tokens",
        "password", "passwords", "auth", "authentication", "authorization", "key", "keys",
    }
)
OBVIOUS_DENIED_NAMES = frozenset(
    {
        "start-recurring-run", "remove-record", "post-webhook", "deploy-production",
        "call-api", "curl-post", "sendemail", "mail-client", "slack-notifier",
        "keychain-reader", "vault-reader", "launch-agent", "background-job",
        "windows-task", "schtasks-client", "turn-on-loop",
    }
)
SENSITIVE_PATH_SEGMENTS = frozenset(
    {".git", ".hg", ".svn", ".github", ".gitlab", ".circleci", ".ssh"}
)
SENSITIVE_PATH_NAMES = frozenset(
    {"jenkinsfile", "azure-pipelines.yml", "azure-pipelines.yaml", ".gitlab-ci.yml"}
)
WRITE_ROOTS = (("loop-data",), ("reports", "loop-output"))
CONTROL_BASENAMES = frozenset(
    {
        "agents.md", "claude.md", "skill.md", "package.json", "package-lock.json",
        "pnpm-lock.yaml", "yarn.lock", "pyproject.toml", "setup.py", "setup.cfg",
        "requirements.txt", "pipfile", "cargo.toml", "cargo.lock", "go.mod", "go.sum",
        "makefile", "dockerfile", "compose.yaml", "compose.yml", "docker-compose.yml",
        "docker-compose.yaml", "plugin.json", "marketplace.json", ".mcp.json", ".app.json",
    }
)
CONTROL_SUFFIXES = (".sh", ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".exe", ".bat", ".cmd", ".ps1")
WINDOWS_DEVICES = frozenset({"con", "prn", "aux", "nul", "clock$"})
WRITE_EXTENSIONS = frozenset({".json", ".jsonl", ".csv", ".txt", ".log"})
MAX_SECRET_SCALARS = 2000
SECRET_KEYS = re.compile(
    r"(?:^|[_-])(?:password|passwd|secret|token|api[_-]?key|private[_-]?key|credential|authorization)(?:$|[_-])",
    re.I,
)
SECRET_VALUES = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    re.compile(r"(?i)\b(?:aws_)?secret_access_key\s*[:=]\s*['\"]?[A-Za-z0-9/+=]{20,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\b(?:sk|rk)_live_[A-Za-z0-9]{16,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    re.compile(r"\bhf_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bnpm_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bpypi-[A-Za-z0-9_-]{30,}\b"),
    re.compile(r"(?i)\bauthorization\s*:\s*bearer\s+[A-Za-z0-9._~+/=-]{10,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"-----BEGIN " r"ENCRYPTED PRIVATE KEY-----"),
    re.compile(r"-----BEGIN " r"PGP PRIVATE KEY BLOCK-----"),
    re.compile(r"https?://[^\s/:]+:[^\s/@]+@"),
    re.compile(
        r"(?i)(?:^|[?&\s])(?:api_key|access_token|client_secret|password|token|secret)"
        r"\s*(?:=|:)\s*['\"]?[A-Za-z0-9._~+/=-]{16,}"
    ),
)
ADJACENT_SECRET_VALUES = (
    re.compile(
        r"(?:AKIA|ASIA)[0-9A-Z]{16}"
        r"|gh[pousr]_[A-Za-z0-9_]{20,}"
        r"|github_pat_[A-Za-z0-9_]{20,}"
        r"|sk-[A-Za-z0-9_-]{20,}"
        r"|xox[baprs]-[A-Za-z0-9-]{10,}"
        r"|glpat-[A-Za-z0-9_-]{20,}"
        r"|(?:sk|rk)_live_[A-Za-z0-9]{16,}"
        r"|AIza[0-9A-Za-z_-]{30,}"
        r"|hf_[A-Za-z0-9]{20,}"
        r"|npm_[A-Za-z0-9]{20,}"
        r"|pypi-[A-Za-z0-9_-]{30,}"
        r"|eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"
    ),
    re.compile(
        r"(?i)(?:aws_)?secret_access_key\s*[:=]\s*['\"]?[A-Za-z0-9/+=]{20,}"
        r"|authorization\s*:\s*bearer\s+[A-Za-z0-9._~+/=-]{10,}"
        r"|(?:api_key|access_token|client_secret|password|token|secret)"
        r"\s*(?:=|:)\s*['\"]?[A-Za-z0-9._~+/=-]{16,}"
    ),
)


class ContractError(ValueError):
    """Raised when a loop contract is malformed or unsafe."""


def _load_readiness_scorer() -> Any:
    path = Path(__file__).with_name("score_loop_readiness.py")
    spec = importlib.util.spec_from_file_location("discover_loops_readiness_scorer", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("bundled readiness scorer could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


READINESS_SCORER = _load_readiness_scorer()


def parse_json(text: str) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ContractError("duplicate JSON key")
            result[key] = value
        return result

    try:
        return json.loads(text, object_pairs_hook=reject_duplicates)
    except ContractError:
        raise
    except json.JSONDecodeError as error:
        raise ContractError("invalid JSON input") from error
    except RecursionError as error:
        raise ContractError("JSON nesting exceeds the supported depth") from error
    except ValueError as error:
        raise ContractError("JSON contains an unsupported numeric value") from error


def _read_bounded(source: str | Path) -> bytes:
    source_text = str(source)
    if source_text == "-":
        return sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    path = Path(source_text)
    try:
        before = path.lstat()
    except OSError as error:
        raise ContractError("input file is unavailable") from error
    if stat.S_ISLNK(before.st_mode):
        raise ContractError("input file must not be a symlink")
    if not stat.S_ISREG(before.st_mode):
        raise ContractError("input file must be a regular file")
    flags = os.O_RDONLY
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise ContractError("input file could not be opened safely") from error
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise ContractError("input file must be a regular file")
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            raise ContractError("input file changed during safe open")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            return stream.read(MAX_INPUT_BYTES + 1)
    finally:
        os.close(descriptor)


def load_json(source: str | Path) -> Any:
    payload = _read_bounded(source)
    if len(payload) > MAX_INPUT_BYTES:
        raise ContractError(f"input exceeds {MAX_INPUT_BYTES} bytes")
    try:
        text = payload.decode("utf-8")
    except UnicodeError as error:
        raise ContractError("input is not valid UTF-8") from error
    return parse_json(text)


def _object(value: Any, label: str, fields: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be an object")
    if fields - set(value):
        raise ContractError(f"{label} has missing fields")
    if set(value) - fields:
        raise ContractError(f"{label} has unknown fields")
    return value


def _string(value: Any, label: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{label} must be a string")
    if len(value) > MAX_STRING_LENGTH:
        raise ContractError(f"{label} is too long")
    if not allow_empty and not value.strip():
        raise ContractError(f"{label} must not be empty")
    if any(
        unicodedata.category(character) in {"Cc", "Cf", "Cs", "Zl", "Zp"}
        for character in value
    ):
        raise ContractError(f"{label} contains unsupported control characters")
    if _contains_secret(value):
        raise ContractError(f"{label} appears to contain embedded credential material")
    return value


def _contains_secret(value: str) -> bool:
    return any(pattern.search(value) for pattern in SECRET_VALUES)


def _contains_adjacent_secret(value: str) -> bool:
    return _contains_secret(value) or any(
        pattern.search(value) for pattern in ADJACENT_SECRET_VALUES
    )


def _identifier(value: Any, label: str) -> str:
    item = _string(value, label)
    if len(item) > 128 or not PROPOSAL_ID.fullmatch(item):
        raise ContractError(f"{label} must be a bounded lowercase hyphenated identifier")
    return item


def _string_list(value: Any, label: str, *, nonempty: bool = False) -> list[str]:
    if not isinstance(value, list):
        raise ContractError(f"{label} must be an array")
    if len(value) > MAX_LIST_ITEMS:
        raise ContractError(f"{label} has too many items")
    if nonempty and not value:
        raise ContractError(f"{label} must not be empty")
    result = [_string(item, f"{label} item") for item in value]
    if len(result) != len(set(result)):
        raise ContractError(f"{label} must not contain duplicates")
    return result


def _evidence_ref(value: Any, label: str) -> str:
    ref = _string(value, label)
    if len(ref) > 256:
        raise ContractError(f"{label} must be a bounded evidence reference")
    scheme, separator, target = ref.partition(":")
    if not separator or scheme not in {"workspace", "source"}:
        raise ContractError(f"{label} uses an unsupported evidence-reference scheme")
    if scheme == "workspace":
        _portable_path(target, label, write_target=False)
    elif (
        len(target) > MAX_HOST_LOCATION_LENGTH
        or not HOST_MANAGED_LOCATION.fullmatch(target)
    ):
        raise ContractError(f"{label} source identifier is invalid")
    return ref


def _evidence_refs(value: Any, label: str, *, nonempty: bool = False) -> list[str]:
    refs = _string_list(value, label, nonempty=nonempty)
    for ref in refs:
        _evidence_ref(ref, f"{label} item")
    return refs


def _scan_secret_keys(value: Any, label: str = "contract") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ContractError(f"{label} contains a non-string key")
            if SECRET_KEYS.search(key):
                raise ContractError(f"{label} contains an embedded credential field")
            _scan_secret_keys(item, label)
    elif isinstance(value, list):
        for item in value:
            _scan_secret_keys(item, label)


def _scan_secret_material(value: Any) -> None:
    scalars: list[str] = []

    def collect(item: Any) -> None:
        if isinstance(item, str):
            if len(scalars) >= MAX_SECRET_SCALARS:
                raise ContractError("contract contains too many scalar values")
            if len(item) <= MAX_STRING_LENGTH:
                scalars.append(item)
            return
        if isinstance(item, dict):
            for key in sorted(item, key=lambda value: str(value)):
                collect(item[key])
            return
        if isinstance(item, list):
            for child in item:
                collect(child)

    collect(value)
    if any(_contains_secret(item) for item in scalars):
        raise ContractError("contract appears to contain embedded credential material")
    cumulative_tail = ""
    for item in scalars:
        cumulative_tail = (cumulative_tail + item)[-MAX_SECRET_ADJACENT_CHARS:]
        if _contains_adjacent_secret(cumulative_tail):
            raise ContractError("contract appears to contain split embedded credential material")


def _portable_path(
    value: str,
    label: str,
    *,
    write_target: bool = True,
    proposal_id: str | None = None,
) -> tuple[str, ...]:
    if (
        "\\" in value
        or ":" in value
        or value.startswith(("/", "~", "$"))
        or value.endswith("/")
        or "//" in value
    ):
        raise ContractError(f"{label} must use canonical portable relative-path syntax")
    parts = tuple(value.split("/"))
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ContractError(f"{label} must use canonical portable relative-path syntax")
    if any(not PORTABLE_SEGMENT.fullmatch(part) for part in parts):
        raise ContractError(f"{label} contains an unsafe path segment")
    if write_target and any(part != part.casefold() for part in parts):
        raise ContractError(f"{label} must use canonical lowercase output components")
    lowered = tuple(part.lower() for part in parts)
    for part in parts:
        lower = part.lower()
        device_base = lower.split(".", 1)[0]
        if part.endswith((".", " ")):
            raise ContractError(f"{label} contains an unsafe normalized basename")
        if (
            device_base in WINDOWS_DEVICES
            or re.fullmatch(r"(?:com|lpt)[1-9]", device_base)
        ):
            raise ContractError(f"{label} contains a reserved device basename")
    if write_target:
        if proposal_id is None:
            raise ContractError(f"{label} requires a proposal namespace")
        proposal_roots = tuple(root + (proposal_id,) for root in WRITE_ROOTS)
        matching_root = next(
            (root for root in proposal_roots if _is_at_or_beneath(parts, root)), None
        )
        if matching_root is None:
            raise ContractError(f"{label} must be beneath its proposal-namespaced output root")
        if len(parts) != len(matching_root) + 1:
            raise ContractError(f"{label} must identify one exact file, not a directory grant")
        filename = parts[-1].lower()
        suffix = "." + filename.rsplit(".", 1)[-1] if "." in filename else ""
        if suffix not in WRITE_EXTENSIONS:
            raise ContractError(f"{label} must use an allowlisted output-file extension")
        for part in lowered:
            tokens = set(filter(None, re.split(r"[._-]+", part)))
            if (
                part in SENSITIVE_PATH_SEGMENTS
                or part.startswith(".env")
                or part in SENSITIVE_PATH_NAMES
                or part in CONTROL_BASENAMES
                or part.endswith(CONTROL_SUFFIXES)
                or tokens & SENSITIVE_PATH_TOKENS
            ):
                raise ContractError(f"{label} selects a sensitive or control-plane path")
    return parts


def _is_at_or_beneath(path: tuple[str, ...], parent: tuple[str, ...]) -> bool:
    return len(path) >= len(parent) and path[: len(parent)] == parent


def _capability_entries(value: Any, label: str) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise ContractError(f"{label} must be an array")
    if len(value) > MAX_LIST_ITEMS:
        raise ContractError(f"{label} has too many items")
    entries: list[dict[str, str]] = []
    identities: list[str] = []
    for item in value:
        entry = _object(
            item,
            f"{label} item",
            {"id", "operation_id", "display_name", "binding_status"},
        )
        identity = _identifier(entry["id"], f"{label} item id")
        operation_id = _string(entry["operation_id"], f"{label} item operation_id")
        if operation_id not in OPERATION_MAP:
            raise ContractError(f"{label} item operation_id is not supported in V1")
        display_name = _string(entry["display_name"], f"{label} item display_name")
        if _string(entry["binding_status"], f"{label} item binding_status") != "unbound":
            raise ContractError("V1 capabilities must remain unbound and non-executable")
        normalized_name = "-".join(re.findall(r"[a-z0-9]+", display_name.casefold()))
        tokens = set(filter(None, normalized_name.split("-")))
        if tokens & LIFECYCLE_TOKENS or {"at", "job"}.issubset(tokens):
            raise ContractError("lifecycle capability aliases are prohibited in V1")
        if tokens & DESTRUCTIVE_TOKENS:
            raise ContractError("destructive capability aliases are prohibited in V1")
        if normalized_name in OBVIOUS_DENIED_NAMES:
            raise ContractError("obvious unsafe capability aliases are prohibited in V1")
        derived = OPERATION_MAP[operation_id]
        entries.append(
            {
                "id": identity,
                "operation_id": operation_id,
                "display_name": display_name,
                "binding_status": "unbound",
                "category": derived["category"],
                "effect": derived["effect"],
                "normalized_display_name": normalized_name,
            }
        )
        identities.append(identity)
    if len(identities) != len(set(identities)):
        raise ContractError(f"{label} must not contain duplicate capability IDs")
    return entries


def _positive_int(value: Any, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ContractError(f"{label} must be an integer from {minimum} through {maximum}")
    return value


def validate_contract(value: Any) -> dict[str, Any]:
    _scan_secret_material(value)
    _scan_secret_keys(value)
    contract = _object(value, "contract", ROOT_FIELDS)
    if _string(contract["artifact_type"], "artifact_type") != "loop-contract-proposal":
        raise ContractError("artifact_type must be loop-contract-proposal")
    if _string(contract["schema_version"], "schema_version") != "1.0":
        raise ContractError("schema_version must be 1.0")
    proposal_id = _identifier(contract["proposal_id"], "proposal_id")
    _string(contract["objective"], "objective")
    evidence_refs = _evidence_refs(contract["evidence_refs"], "evidence_refs", nonempty=True)

    readiness = _object(
        contract["readiness"],
        "readiness",
        {
            "outcome",
            "card",
            "card_ref",
            "card_sha256",
            "permission_scope",
            "requested_autonomy",
            "data_handling",
        },
    )
    readiness_outcome = _string(readiness["outcome"], "readiness.outcome")
    if readiness_outcome not in {"read_only_triage_loop", "supervised_loop"}:
        raise ContractError("readiness.outcome does not permit a loop contract")
    card_ref = _evidence_ref(readiness["card_ref"], "readiness.card_ref")
    if card_ref not in evidence_refs:
        raise ContractError("readiness.card_ref must appear exactly in evidence_refs")
    card_sha256 = _string(readiness["card_sha256"], "readiness.card_sha256")
    if not SHA256.fullmatch(card_sha256):
        raise ContractError("readiness.card_sha256 must be a lowercase SHA-256 digest")
    try:
        readiness_card = READINESS_SCORER.validate_card(readiness["card"])
        recomputed = READINESS_SCORER.score(readiness_card)
    except READINESS_SCORER.ReadinessError as error:
        raise ContractError("readiness.card is not a valid normalized readiness card") from error
    canonical_card = json.dumps(
        readiness_card, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    if hashlib.sha256(canonical_card).hexdigest() != card_sha256:
        raise ContractError("readiness.card_sha256 does not match the canonical readiness.card")
    if recomputed["outcome"] != readiness_outcome:
        raise ContractError("readiness.outcome does not match the recomputed scorer outcome")
    if recomputed["outcome"] not in {"read_only_triage_loop", "supervised_loop"}:
        raise ContractError("recomputed readiness outcome does not permit a loop contract")
    for name in ("permission_scope", "requested_autonomy", "data_handling"):
        if readiness_card[name] != readiness[name]:
            raise ContractError("readiness declarations do not match the embedded readiness.card")
    permission_scope = _string(readiness["permission_scope"], "readiness.permission_scope")
    if permission_scope not in {"none", "least-privilege", "broad"}:
        raise ContractError("readiness.permission_scope is invalid")
    requested_autonomy = _string(readiness["requested_autonomy"], "readiness.requested_autonomy")
    if requested_autonomy != "supervised":
        raise ContractError("loop contracts require supervised requested autonomy")
    data_handling = _string(readiness["data_handling"], "readiness.data_handling")
    if data_handling not in {"ordinary", "host-managed-sensitive", "embedded-secret"}:
        raise ContractError("readiness.data_handling is invalid")
    if data_handling == "embedded-secret":
        raise ContractError("embedded-secret data handling is prohibited")
    if permission_scope == "broad":
        raise ContractError("broad permission scope is prohibited in V1 loop contracts")

    semantic_review = _object(
        contract["semantic_review"], "semantic_review", {"required", "status"}
    )
    if semantic_review["required"] is not True:
        raise ContractError("semantic_review.required must be true")
    if _string(semantic_review["status"], "semantic_review.status") != "pending":
        raise ContractError("semantic_review.status must be pending")

    trigger = _object(contract["trigger"], "trigger", {"type", "description"})
    trigger_type = _string(trigger["type"], "trigger.type")
    if trigger_type not in {"manual", "event-proposal", "schedule-proposal"}:
        raise ContractError("trigger.type is invalid")
    _string(trigger["description"], "trigger.description")
    _string_list(contract["inputs"], "inputs", nonempty=True)

    scope = _object(
        contract["scope"],
        "scope",
        {"allowed_paths", "allowed_tools", "allowed_actions", "prohibited_actions"},
    )
    allowed_paths = _string_list(scope["allowed_paths"], "scope.allowed_paths")
    normalized_path_identities = [path.casefold() for path in allowed_paths]
    if len(normalized_path_identities) != len(set(normalized_path_identities)):
        raise ContractError("scope.allowed_paths contains case-insensitive duplicate targets")
    path_parts = [
        _portable_path(
            path, "scope.allowed_paths item", proposal_id=proposal_id
        )
        for path in allowed_paths
    ]
    allowed_tools = _capability_entries(scope["allowed_tools"], "scope.allowed_tools")
    allowed_actions = _capability_entries(scope["allowed_actions"], "scope.allowed_actions")
    capabilities = allowed_tools + allowed_actions
    if not capabilities:
        raise ContractError("scope must declare at least one allowed capability")
    capability_ids = [entry["id"] for entry in capabilities]
    if len(capability_ids) != len(set(capability_ids)):
        raise ContractError("scope capability IDs must be unique across tools and actions")

    prohibited_actions = _string_list(
        scope["prohibited_actions"], "scope.prohibited_actions", nonempty=True
    )
    if any(not PROPOSAL_ID.fullmatch(item) for item in prohibited_actions):
        raise ContractError("scope.prohibited_actions must contain lowercase identifiers")
    if not MANDATORY_PROHIBITED_ACTIONS.issubset(prohibited_actions):
        raise ContractError("scope.prohibited_actions is missing mandatory lifecycle denies")
    if set(capability_ids) & set(prohibited_actions):
        raise ContractError("allowed capabilities cannot also be prohibited")
    for entry in capabilities:
        display = entry["normalized_display_name"]
        for prohibited in prohibited_actions:
            if display == prohibited or f"-{prohibited}-" in f"-{display}-":
                raise ContractError("capability display name conflicts with a prohibited action")
    if any(entry["category"] == "local-workspace" for entry in capabilities) and not path_parts:
        raise ContractError("local-workspace capabilities require allowed_paths")

    state = _object(contract["state"], "state", {"kind", "location", "retention"})
    state_kind = _string(state["kind"], "state.kind")
    if state_kind not in {"none", "workspace-file", "host-managed"}:
        raise ContractError("state.kind is invalid")
    state_location = _string(state["location"], "state.location", allow_empty=True)
    retention = state["retention"]
    if not isinstance(retention, dict):
        raise ContractError("state.retention must be an object")
    retention_mode = retention.get("mode")
    if state_kind == "none":
        _object(retention, "state.retention", {"mode"})
        if state_location:
            raise ContractError("state.location must be empty when state.kind is none")
        if retention_mode != "none":
            raise ContractError("state.retention must be none when state.kind is none")
    else:
        _object(retention, "state.retention", {"mode", "max_records", "max_age_days"})
        if not state_location:
            raise ContractError("state.location must not be empty when state is retained")
        if retention_mode != "bounded":
            raise ContractError("retained state requires bounded retention")
        _positive_int(retention["max_records"], "state.retention.max_records", 1, 10000)
        _positive_int(retention["max_age_days"], "state.retention.max_age_days", 1, 365)
    if state_kind == "workspace-file":
        state_parts = _portable_path(
            state_location, "state.location", proposal_id=proposal_id
        )
        if state_parts not in path_parts:
            raise ContractError("workspace-file state must exactly equal an allowed file target")
        if not any(entry["category"] == "local-workspace" for entry in capabilities):
            raise ContractError("workspace-file state requires a local-workspace capability")
    if state_kind == "host-managed":
        raise ContractError("host-managed mutable state is prohibited in V1")

    operation_ids = {entry["operation_id"] for entry in capabilities}
    if "external.write" in operation_ids:
        inferred_action_scope = "external-reversible"
    elif "external.read" in operation_ids:
        inferred_action_scope = "external-read-only"
    elif "workspace.write" in operation_ids:
        inferred_action_scope = "local-reversible"
    else:
        inferred_action_scope = "read-only"
    if readiness_card["action_scope"] != inferred_action_scope:
        raise ContractError("readiness.card action_scope does not match declared capabilities")
    inferred_state_scope = "none" if state_kind == "none" else "bounded"
    if readiness_card["state_scope"] != inferred_state_scope:
        raise ContractError("readiness.card state_scope does not match declared state")

    acceptance = _object(contract["acceptance"], "acceptance", {"checks", "verifier"})
    _string_list(acceptance["checks"], "acceptance.checks", nonempty=True)
    verifier = _object(acceptance["verifier"], "acceptance.verifier", {"required", "status"})
    if verifier["required"] is not True:
        raise ContractError("acceptance.verifier.required must be true")
    if _string(verifier["status"], "acceptance.verifier.status") != "pending":
        raise ContractError("V1 acceptance.verifier.status must be pending")

    dry_run = _object(
        contract["dry_run"], "dry_run", {"cases", "pass_condition", "result", "evidence_refs"}
    )
    cases = dry_run["cases"]
    if not isinstance(cases, list) or not 1 <= len(cases) <= MAX_LIST_ITEMS:
        raise ContractError("dry_run.cases must be a bounded non-empty array")
    case_ids: list[str] = []
    for case_value in cases:
        case = _object(case_value, "dry_run case", {"id", "description", "expected_evidence"})
        case_ids.append(_identifier(case["id"], "dry_run case id"))
        _string(case["description"], "dry_run case description")
        _string(case["expected_evidence"], "dry_run case expected_evidence")
    if len(case_ids) != len(set(case_ids)):
        raise ContractError("dry_run case IDs must be unique")
    _string(dry_run["pass_condition"], "dry_run.pass_condition")
    dry_result = _string(dry_run["result"], "dry_run.result")
    if dry_result not in {"pending", "passed", "failed"}:
        raise ContractError("dry_run.result is invalid")
    dry_evidence = _evidence_refs(dry_run["evidence_refs"], "dry_run.evidence_refs")
    if dry_result != "pending" and not dry_evidence:
        raise ContractError("every non-pending dry-run result requires evidence references")

    limits = _object(
        contract["limits"], "limits", {"max_iterations", "max_retries", "max_elapsed_minutes"}
    )
    _positive_int(limits["max_iterations"], "limits.max_iterations", 1, 50)
    _positive_int(limits["max_retries"], "limits.max_retries", 0, 5)
    _positive_int(limits["max_elapsed_minutes"], "limits.max_elapsed_minutes", 1, 240)
    terminal_states = _string_list(contract["terminal_states"], "terminal_states", nonempty=True)
    if len(terminal_states) != len(TERMINAL_STATES) or set(terminal_states) != TERMINAL_STATES:
        raise ContractError("terminal_states must be exactly complete, blocked, needs-approval, failed")

    approval_values = contract["approvals"]
    if not isinstance(approval_values, list) or not 1 <= len(approval_values) <= MAX_LIST_ITEMS:
        raise ContractError("approvals must be a bounded non-empty array")
    approval_actions: list[str] = []
    human_approvals: set[str] = set()
    for approval_value in approval_values:
        approval = _object(approval_value, "approval", {"action", "required", "approver"})
        action = _identifier(approval["action"], "approval.action")
        if not isinstance(approval["required"], bool):
            raise ContractError("approval.required must be a boolean")
        if _string(approval["approver"], "approval.approver") != "human":
            raise ContractError("approval.approver must be human")
        approval_actions.append(action)
        if approval["required"]:
            human_approvals.add(action)
    if len(approval_actions) != len(set(approval_actions)):
        raise ContractError("approvals must not contain duplicate actions")
    if "activate" not in human_approvals:
        raise ContractError("every proposal requires human activation approval")
    if trigger_type == "schedule-proposal" and "schedule" not in human_approvals:
        raise ContractError("schedule-proposal requires distinct human schedule approval")

    for entry in capabilities:
        if entry["id"] not in human_approvals:
            raise ContractError("every allowed capability requires exact human approval")
        if entry["category"] in {"external-system", "credential-access"}:
            if permission_scope != "least-privilege":
                raise ContractError("external and credential capabilities require least privilege")
            if readiness_outcome != "supervised_loop":
                raise ContractError("external and credential capabilities require supervised_loop")
            if entry["id"] not in human_approvals:
                raise ContractError("external and credential capabilities require exact human approval")
        if entry["category"] == "credential-access" and data_handling != "host-managed-sensitive":
            raise ContractError("credential-access requires host-managed-sensitive data handling")

    has_credential = any(entry["category"] == "credential-access" for entry in capabilities)
    if data_handling == "host-managed-sensitive" and not has_credential:
        raise ContractError("host-managed-sensitive data requires a credential-access capability")
    if readiness_outcome == "read_only_triage_loop":
        if data_handling != "ordinary":
            raise ContractError("read_only_triage_loop permits only ordinary data")
        if state_kind == "workspace-file":
            raise ContractError("read_only_triage_loop cannot retain workspace-file state")
        if path_parts:
            raise ContractError("read_only_triage_loop must not declare writable allowed_paths")
        if any(
            entry["operation_id"] != "workspace.observe"
            for entry in capabilities
        ):
            raise ContractError("read_only_triage_loop permits only workspace.observe capabilities")
    else:
        if not any(entry["category"] != "observation" for entry in capabilities):
            raise ContractError("supervised_loop requires a bounded non-observation capability")
    if path_parts and not any(entry["category"] == "local-workspace" for entry in capabilities):
        raise ContractError("allowed_paths require a local-workspace capability")

    _string(contract["rollback"], "rollback")
    _string_list(contract["metrics"], "metrics", nonempty=True)
    lifecycle = _object(
        contract["lifecycle"],
        "lifecycle",
        {"proposal_status", "activation_status", "scheduler_status"},
    )
    if _string(lifecycle["proposal_status"], "lifecycle.proposal_status") != "draft":
        raise ContractError("V1 lifecycle.proposal_status must be draft")
    if _string(lifecycle["activation_status"], "lifecycle.activation_status") != "pending":
        raise ContractError("V1 lifecycle.activation_status must be pending")
    if _string(lifecycle["scheduler_status"], "lifecycle.scheduler_status") != "inactive":
        raise ContractError("V1 lifecycle.scheduler_status must be inactive")
    return contract


def _python_supported() -> bool:
    if sys.version_info < MIN_PYTHON:
        print("ERROR: Python 3.11 or newer is required", file=sys.stderr)
        return False
    return True


def main() -> int:
    if not _python_supported():
        return 2
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", required=True, help="V1 contract file, or - for bounded stdin")
    args = parser.parse_args()
    try:
        contract = validate_contract(load_json(args.contract))
        print(
            json.dumps(
                {
                    "artifact_type": contract["artifact_type"],
                    "schema_version": contract["schema_version"],
                    "proposal_id": contract["proposal_id"],
                    "structurally_valid": True,
                    "semantic_review_required": True,
                    "activation_allowed": False,
                },
                sort_keys=True,
            )
        )
        return 0
    except ContractError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    except (OSError, RecursionError, ValueError):
        print("ERROR: input could not be processed safely", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
