#!/usr/bin/env python3
"""Deterministically route one normalized Agent Workbench child packet."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import unicodedata
from pathlib import Path
from typing import Any


FIELDS: dict[str, tuple[str, ...]] = {
    "work_shape": ("map", "plan", "extract", "diagnose", "implement", "test", "debug", "migrate", "review", "operate", "verify-external"),
    "scope": ("one file", "bounded component", "cross-component", "cross-system"),
    "ambiguity": ("settled", "local unknown", "competing hypotheses", "open-ended"),
    "contract": ("none", "internal", "public API", "persistent data", "security boundary"),
    "tool_loop": ("none", "one read/check", "repeated local tools", "repeated external tools"),
    "impact": ("reversible", "user-visible", "shared system", "production-critical"),
    "evidence_bar": ("syntax", "focused test", "integration/regression", "independent review"),
    "context_profile": ("compact facts", "focused source set", "noisy logs/large artifacts", "long-running history"),
    "parallelism": ("none", "independent read-only", "independent writes", "dependent sequence"),
    "change_authority": ("none", "owned local paths", "owned-path deletion", "shared contract", "external/destructive"),
    "router_confidence": ("high", "uncertain", "unresolved"),
}
BOUNDARIES = ("public API", "persistent data", "security boundary")
OPTIONAL_LIST_FIELDS: dict[str, tuple[str, ...] | None] = {
    "contract_boundaries": BOUNDARIES,
    "required_capabilities": ("read", "write", "test", "review", "security-review", "migration", "external-operation", "external-verification"),
    "required_modalities": ("text", "code", "structured-data", "image", "browser"),
    "required_tools": ("file-read", "file-write", "shell", "network", "browser"),
    "required_skills": None,
    "planning_capabilities": ("read", "test", "review", "security-review"),
    "planning_modalities": ("text", "code", "structured-data"),
    "planning_tools": ("file-read", "shell"),
    "planning_skills": None,
    "deferred_capabilities": ("read", "write", "test", "review", "security-review", "migration", "external-operation", "external-verification"),
    "deferred_modalities": ("text", "code", "structured-data", "image", "browser"),
    "deferred_tools": ("file-read", "file-write", "shell", "network", "browser"),
    "deferred_skills": None,
}
OPTIONAL_OBJECT_FIELDS = {"operation_authorization", "external_verification"}

ROLE_PROFILE: dict[str, tuple[str, str]] = {
    "awb_fast_investigator": ("efficient", "low"),
    "awb_deep_investigator": ("frontier", "high"),
    "awb_planner": ("frontier", "high"),
    "awb_builder": ("balanced", "medium"),
    "awb_deep_worker": ("frontier", "high"),
    "awb_migration_worker": ("frontier", "maximum"),
    "awb_operator": ("frontier", "maximum"),
    "awb_verifier": ("balanced", "medium"),
    "awb_test_engineer": ("balanced", "high"),
    "awb_reviewer": ("frontier", "high"),
    "awb_security_reviewer": ("frontier", "maximum"),
}
ROLE_CAPABILITIES: dict[str, frozenset[str]] = {
    "awb_fast_investigator": frozenset({"read"}),
    "awb_deep_investigator": frozenset({"read"}),
    "awb_planner": frozenset({"read"}),
    "awb_builder": frozenset({"read", "write", "test"}),
    "awb_deep_worker": frozenset({"read", "write", "test"}),
    "awb_migration_worker": frozenset({"read", "write", "test", "migration"}),
    "awb_operator": frozenset({"read"}),
    "awb_verifier": frozenset({"read", "test"}),
    "awb_test_engineer": frozenset({"read", "test"}),
    "awb_reviewer": frozenset({"read", "review"}),
    "awb_security_reviewer": frozenset({"read", "review", "security-review"}),
}
ROLE_MODALITIES = {role: frozenset({"text", "code", "structured-data"}) for role in ROLE_PROFILE}
ROLE_TOOLS: dict[str, frozenset[str]] = {
    role: frozenset({"file-read", "shell"}) for role in ROLE_PROFILE
}
for _role in ("awb_builder", "awb_deep_worker", "awb_migration_worker"):
    ROLE_TOOLS[_role] = frozenset({"file-read", "file-write", "shell"})
ENABLED_ROLES = frozenset(set(ROLE_PROFILE) - {"awb_operator"})

OUTPUT_KEYS = {
    "primary_role", "execution_path", "task_class", "capability_tier", "effort", "required_followups",
    "reroute_after_planning", "must_not_downgrade", "required_capabilities",
    "required_modalities", "required_tools", "required_skills", "skill_fallback_required",
    "reasons",
    "deferred_capabilities", "deferred_modalities", "deferred_tools", "deferred_skills",
    "current_change_authority", "deferred_change_authority", "authorization_binding", "authorization_reference",
}
DIRECT_DIAGNOSIS_OUTPUT_KEYS = OUTPUT_KEYS | {"lifecycle"}
DIRECT_DIAGNOSIS_LIFECYCLE = {
    "work_cutoff_seconds": 90,
    "hard_deadline_seconds": 120,
    "handoff_reserve_seconds": 30,
    "max_children": 1,
    "max_waits": 2,
    "max_followups": 0,
    "cutoff_action": "synthesize-only-already-gathered-evidence",
    "hard_deadline_outcome": "blocked",
    "model_escalation": "prohibited",
    "implementation_governance": "prohibited",
}
PROBE_ROLE = "lead-owned-protected-mcp"
PROBE_LIFECYCLE = {
    "work_cutoff_seconds": 45,
    "hard_deadline_seconds": 60,
    "handoff_reserve_seconds": 15,
    "max_mcp_calls": 1,
    "max_children": 0,
    "max_waits": 0,
    "hard_deadline_outcome": "inconclusive-delegate",
}
MAX_PROBE_MATCHES = 64
PROBE_DESCRIPTOR_VERSION = 6
PROBE_PARENT_CONTEXT_VERSION = 2
PROBE_STABILITY_PASSES = 2
PROBE_METADATA_TOKEN_FIELDS = [
    "st_dev",
    "st_ino",
    "st_mode",
    "st_nlink",
    "st_uid",
    "st_gid",
    "st_size",
    "st_mtime_ns",
    "st_ctime_ns",
]
PROBE_STABILITY_COMPARISON = "byte-identical-canonical-metadata-receipts-and-query-results"
PROBE_STABILITY_FAILURE_ACTION = "all-query-results-incomplete"
PROBE_ROOT_SOURCE = "one-strict-canonical-local-file-uri-from-full-duplex-mcp-roots-list"
PROBE_SERVER_CWD = "installed-plugin-root-never-used-as-scan-target"
PROBE_ROOT_PINNING = "roots-list-path-opened-before-workspace-identity-and-reused-across-both-passes"
PROBE_WORKSPACE_IDENTITY_BINDING = (
    "canonical-path-and-pinned-root-st-dev-st-ino-revalidated-before-between-and-after-passes"
)
CODEX_PROFILE_SCHEMA_KEYS = (
    "name",
    "description",
    "model",
    "model_reasoning_effort",
    "sandbox_mode",
    "developer_instructions",
)
PROBE_ARTIFACT_REGISTRY: dict[str, dict[str, Any]] = {
    "ecs-task-definition-manifests": {
        "accepted_path_pattern": (
            r"(?:[A-Za-z0-9._@+-]+/)*(?:[A-Za-z0-9][A-Za-z0-9._-]*[-_])?"
            r"task[-_]definitions?(?:[-_.][A-Za-z0-9][A-Za-z0-9._-]*)?\.(?:json|yaml|yml)\Z"
        ),
    },
    "deployment-pipeline-manifests": {
        "accepted_path_pattern": (
            r"(?:[A-Za-z0-9._@+-]+/)*(?:\.github/workflows/[A-Za-z0-9._-]+\.(?:ya?ml)|"
            r"(?:[A-Za-z0-9][A-Za-z0-9._-]*[-_])?bitbucket-pipelines"
            r"(?:[-_.][A-Za-z0-9][A-Za-z0-9._-]*)?\.(?:yaml|yml)|"
            r"(?:[A-Za-z0-9][A-Za-z0-9._-]*[-_])?(?:cloudbuild|buildspec)"
            r"(?:[-_.][A-Za-z0-9][A-Za-z0-9._-]*)?\.(?:json|yaml|yml)|"
            r"(?:[A-Za-z0-9][A-Za-z0-9._-]*[-_])?pipeline"
            r"(?:[-_.][A-Za-z0-9][A-Za-z0-9._-]*)?\.(?:json|yaml|yml|groovy)|"
            r"(?:[A-Za-z0-9][A-Za-z0-9._-]*[-_])?Jenkinsfile"
            r"(?:[-_][A-Za-z0-9][A-Za-z0-9._-]*)?(?:\.groovy)?)\Z"
        ),
    },
    "infrastructure-as-code": {
        "accepted_path_pattern": (
            r"(?:[A-Za-z0-9._@+-]+/)*(?:[A-Za-z0-9._-]+\.tf(?:\.json)?|cdk\.json|Pulumi[A-Za-z0-9._-]*\.ya?ml|"
            r"(?:serverless|sam|cloudformation|template)[A-Za-z0-9._-]*\.ya?ml)\Z"
        ),
    },
}
PROBE_TOOL_CONSTRAINTS = {
    "mcp_server": "awb_ownership",
    "mcp_tool": "scan_required_artifacts",
    "invocation": "one-direct-lead-owned-zero-argument-call",
    "required_observation": "exact-protected-mcp-tool-registered-and-enabled",
    "missing_or_unobservable_action": "normal-full-flow-zero-probe-children-waits-or-synthesis",
    "forbidden": [
        "ownership-probe-child",
        "caller-supplied-input",
        "file-content-reads",
        "shell-or-repository-commands-or-imports",
        "hooks-helpers-or-configuration-evaluation",
        "network-or-credentials",
        "mutation-or-tests",
        "implementation-governance",
        "symlink-following",
    ],
}
PROBE_INPUT_KEYS = {
    "phase",
    "registry_descriptor",
    "registry_descriptor_sha256",
    "required_artifact_classes",
    "direct_user_objective_repository_identity",
    "host_canonical_workspace_identity",
    "declaration_conflict",
    "query_results",
}
PROBE_ADAPTER_RESULT_KEYS = {
    "adapter_result_version",
    "tool_name",
    "descriptor_version",
    "descriptor_sha256",
    "workspace_identity",
    "query_results",
}
PROBE_PARENT_CONTEXT_KEYS = {
    "context_version",
    "phase",
    "descriptor_version",
    "descriptor_sha256",
    "required_artifact_classes",
    "declaration_conflict",
    "direct_user_objective_repository_identity",
    "host_canonical_workspace_identity",
    "adapter_result",
}
PROBE_AMBIGUITY_KEYS = {
    "declaration_conflict",
    "unsupported_required_classes",
    "incomplete_query_classes",
    "truncated_query_classes",
    "symlink_encountered_query_classes",
    "symlinks_followed_query_classes",
}
PROBE_QUERY_KEYS = {
    "artifact_class",
    "complete",
    "truncated",
    "symlink_encountered",
    "symlinks_followed",
    "matches",
}
PROBE_OUTPUT_KEYS = {
    "phase",
    "primary_role",
    "execution_path",
    "capability_tier",
    "effort",
    "required_followups",
    "artifact_queries",
    "required_artifact_classes",
    "matched_required_classes",
    "outcome",
    "routing_action",
    "expected_owner_identity",
    "required_input",
    "lifecycle",
    "planner_count",
    "probe_child_count",
    "wait_count",
    "virtual_elapsed_seconds_upper_bound",
}
PROBE_CAPABILITY_GATE_KEYS = {
    "harness",
    "probe_supported",
    "spawn_probe_child",
    "direct_mcp_call",
    "max_waits",
    "max_syntheses",
    "routing_action",
    "reason",
    "outcome",
    "required_input",
    "planner_count",
    "probe_child_count",
    "wait_count",
    "virtual_elapsed_seconds_upper_bound",
}

OWNERSHIP_REPOSITORY_REQUIRED_INPUT = "exact-objective-owning-repository-identity-or-path"


def ownership_probe_descriptor() -> dict[str, Any]:
    """Return the canonical pre-query contract without reading repository state."""
    return {
        "version": PROBE_DESCRIPTOR_VERSION,
        "phase": "probe-ownership",
        "class_queries": [
            {
                "artifact_class": name,
                "accepted_path_pattern": details["accepted_path_pattern"],
            }
            for name, details in PROBE_ARTIFACT_REGISTRY.items()
        ],
        "limits": {
            "max_classes": len(PROBE_ARTIFACT_REGISTRY),
            "max_matches_per_class": MAX_PROBE_MATCHES,
            "max_depth": 32,
            "max_entries": 50000,
            "deadline_seconds": 45,
        },
        "stability": {
            "passes": PROBE_STABILITY_PASSES,
            "entry_budget_scope": "cumulative-across-passes",
            "deadline_scope": "cumulative-across-passes",
            "metadata_token_fields": list(PROBE_METADATA_TOKEN_FIELDS),
            "directory_tokens": "pre-and-post-fstat-must-match",
            "root_source": PROBE_ROOT_SOURCE,
            "server_cwd": PROBE_SERVER_CWD,
            "root_pinning": PROBE_ROOT_PINNING,
            "workspace_identity_binding": PROBE_WORKSPACE_IDENTITY_BINDING,
            "comparison": PROBE_STABILITY_COMPARISON,
            "failure_action": PROBE_STABILITY_FAILURE_ACTION,
        },
        "excluded_directories": [
            ".git", ".hg", ".svn", ".tox", ".venv", "__pycache__", "node_modules", "vendor"
        ],
        "query_result_schema": {
            "required_fields": sorted(PROBE_QUERY_KEYS),
            "matches": "unique-sorted-canonical-repository-relative-paths",
            "classification": "validate-all-paths-then-filter-by-accepted-path-pattern",
        },
        "adapter_result_schema": {
            "required_fields": sorted(PROBE_ADAPTER_RESULT_KEYS),
            "descriptor_binding": "sha256-canonical-json-of-registry-descriptor",
            "workspace_binding": "exact-host-canonical-workspace-identity",
            "classification": "lead-recomputes-from-retained-context-and-exact-adapter-result",
        },
        "parent_context_schema": {
            "version": PROBE_PARENT_CONTEXT_VERSION,
            "required_fields": sorted(PROBE_PARENT_CONTEXT_KEYS),
            "canonicalization": "utf8-json-sort-keys-true-separators-comma-colon-ensure-ascii-true",
            "binding_semantics": "integrity-only-not-authentication",
            "parent_retention": "exact-object-and-digest",
        },
        "tool_constraints": {
            "mcp_server": PROBE_TOOL_CONSTRAINTS["mcp_server"],
            "mcp_tool": PROBE_TOOL_CONSTRAINTS["mcp_tool"],
            "invocation": PROBE_TOOL_CONSTRAINTS["invocation"],
            "required_observation": PROBE_TOOL_CONSTRAINTS["required_observation"],
            "missing_or_unobservable_action": PROBE_TOOL_CONSTRAINTS["missing_or_unobservable_action"],
            "forbidden": list(PROBE_TOOL_CONSTRAINTS["forbidden"]),
        },
        "lifecycle": dict(PROBE_LIFECYCLE),
    }


def ownership_probe_descriptor_sha256() -> str:
    canonical = json.dumps(
        ownership_probe_descriptor(), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _canonical_sha256(value: Any) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def ownership_probe_parent_context(
    descriptor: Any,
    required_artifact_classes: Any,
    declaration_conflict: Any,
    direct_user_objective_repository_identity: Any,
    host_canonical_workspace_identity: Any,
    adapter_result: Any,
) -> dict[str, Any]:
    """Build the immutable parent-retained context for an ownership probe."""
    if descriptor != ownership_probe_descriptor():
        raise RoutingError("ownership probe parent context descriptor differs from the canonical contract")
    if (
        not isinstance(required_artifact_classes, list)
        or not 1 <= len(required_artifact_classes) <= len(PROBE_ARTIFACT_REGISTRY)
        or required_artifact_classes != list(dict.fromkeys(required_artifact_classes))
    ):
        raise RoutingError("required_artifact_classes must contain one to three unique class names")
    for artifact_class in required_artifact_classes:
        if not _is_clean_text(artifact_class):
            raise RoutingError("required_artifact_classes must contain exact trimmed non-control names")
    if type(declaration_conflict) is not bool:
        raise RoutingError("ownership probe declaration_conflict must be a boolean")
    if direct_user_objective_repository_identity is not None and not _is_clean_text(
        direct_user_objective_repository_identity
    ):
        raise RoutingError("direct user objective repository identity must be null or exact trimmed non-control text")
    if not _is_canonical_workspace_identity(host_canonical_workspace_identity):
        raise RoutingError("host canonical workspace identity must be an exact canonical absolute path")
    _validate_probe_adapter_result(adapter_result, host_canonical_workspace_identity)
    context = {
        "context_version": PROBE_PARENT_CONTEXT_VERSION,
        "phase": "probe-ownership",
        "descriptor_version": descriptor["version"],
        "descriptor_sha256": ownership_probe_descriptor_sha256(),
        "required_artifact_classes": list(required_artifact_classes),
        "declaration_conflict": declaration_conflict,
        "direct_user_objective_repository_identity": direct_user_objective_repository_identity,
        "host_canonical_workspace_identity": host_canonical_workspace_identity,
        "adapter_result": adapter_result,
    }
    if set(context) != PROBE_PARENT_CONTEXT_KEYS:
        raise AssertionError("ownership probe parent context schema drifted")
    return context


def ownership_probe_parent_context_sha256(context: Any) -> str:
    """Return the canonical integrity binding for a validated parent context."""
    if not isinstance(context, dict) or set(context) != PROBE_PARENT_CONTEXT_KEYS:
        raise RoutingError("ownership probe parent context has an invalid schema")
    expected = ownership_probe_parent_context(
        ownership_probe_descriptor(),
        context.get("required_artifact_classes"),
        context.get("declaration_conflict"),
        context.get("direct_user_objective_repository_identity"),
        context.get("host_canonical_workspace_identity"),
        context.get("adapter_result"),
    )
    if context != expected:
        raise RoutingError("ownership probe parent context differs from the canonical retained context")
    return _canonical_sha256(context)


def ownership_probe_capability_gate(
    harness: Any,
    tool_registered: Any,
    observed_tools: Any,
    required_artifact_classes: Any = None,
    direct_user_objective_repository_identity: Any = None,
) -> dict[str, Any]:
    """Decide whether the lead may call the protected MCP tool directly."""
    if harness not in {"codex", "claude"}:
        raise RoutingError("ownership probe harness must be codex or claude")
    if type(tool_registered) is not bool:
        raise RoutingError("ownership probe tool_registered must be a boolean")
    if (
        not isinstance(observed_tools, list)
        or observed_tools != sorted(set(observed_tools))
        or any(not _is_clean_text(tool) for tool in observed_tools)
    ):
        raise RoutingError("ownership probe observed_tools must be unique sorted exact names")
    required = [] if required_artifact_classes is None else required_artifact_classes
    if (
        not isinstance(required, list)
        or required != list(dict.fromkeys(required))
        or any(item not in PROBE_ARTIFACT_REGISTRY for item in required)
    ):
        raise RoutingError("ownership probe required artifact classes must be unique registered names")
    if direct_user_objective_repository_identity is not None and not _is_clean_text(
        direct_user_objective_repository_identity
    ):
        raise RoutingError("direct user objective repository identity must be exact clean text or null")
    supported = tool_registered and observed_tools == ["awb_ownership.scan_required_artifacts"]
    if supported:
        reason = "verified-protected-awb-ownership-mcp-tool"
        routing_action = "probe-ownership"
        outcome = "probe-ownership"
        required_input = None
    elif not tool_registered:
        reason = "protected-awb-ownership-mcp-server-unregistered"
        outcome, routing_action, required_input = _unresolved_ownership_fallback(
            required, direct_user_objective_repository_identity
        )
    else:
        reason = "exact-protected-awb-ownership-mcp-tool-unavailable"
        outcome, routing_action, required_input = _unresolved_ownership_fallback(
            required, direct_user_objective_repository_identity
        )
    result = {
        "harness": harness,
        "probe_supported": supported,
        "spawn_probe_child": False,
        "direct_mcp_call": supported,
        "max_waits": 0,
        "max_syntheses": 0,
        "routing_action": routing_action,
        "reason": reason,
        "outcome": outcome,
        "required_input": required_input,
        "planner_count": 0,
        "probe_child_count": 0,
        "wait_count": 0,
        "virtual_elapsed_seconds_upper_bound": 0,
    }
    if set(result) != PROBE_CAPABILITY_GATE_KEYS:
        raise AssertionError("ownership probe capability gate schema drifted")
    return result


def _unresolved_ownership_fallback(
    required_artifact_classes: list[str],
    direct_user_objective_repository_identity: str | None,
) -> tuple[str, str, str | None]:
    """Stop before planning only when one exact repository answer can settle the packet."""
    if required_artifact_classes and direct_user_objective_repository_identity is None:
        return (
            "unknown-owner-needs-input",
            "request-input-before-planner",
            OWNERSHIP_REPOSITORY_REQUIRED_INPUT,
        )
    return "inconclusive-delegate", "normal-full-flow", None


MAX_INPUT_BYTES = 1_048_576
MAX_TEXT_FIELD = 512
MAX_JSON_DEPTH = 128
MAX_JSON_NODES = 100_000
REPLAY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_ORIGINAL_OS_OPEN = os.open
_SECURE_OPEN_DIAGNOSTIC = (
    "secure file reading is unsupported on this platform; requires POSIX os.open "
    "dir_fd support and O_DIRECTORY, O_NOFOLLOW, and O_NONBLOCK"
)
EXTERNAL_EXECUTION_UNAVAILABLE = "external execution unavailable: no constrained network adapter is configured"


class RoutingError(ValueError):
    """Raised when a routing card is incomplete or unsupported."""


def _is_clean_text(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and value == value.strip()
        and value == unicodedata.normalize("NFC", value)
        and len(value) <= MAX_TEXT_FIELD
        and not any(unicodedata.category(char) in {"Cc", "Cf", "Cs"} for char in value)
    )


def _is_canonical_repository_path(value: Any) -> bool:
    if not _is_clean_text(value) or "\\" in value or value.startswith("/"):
        return False
    components = value.split("/")
    return all(
        component not in {"", ".", ".."}
        and re.fullmatch(r"[A-Za-z0-9._@+-]+", component) is not None
        for component in components
    )


def _display(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, default=str)


def _authorization_binding(packet_id: str, revision: str, action: str, target: str) -> str:
    canonical = json.dumps(
        {"action": action, "packet_id": packet_id, "revision": revision, "target": target},
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def parse_json(text: str) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise RoutingError(f"duplicate JSON key: {_display(key)}")
            result[key] = value
        return result

    _check_json_nesting(text)
    try:
        value = json.loads(text, object_pairs_hook=reject_duplicates)
    except RecursionError as error:
        raise RoutingError("JSON nesting exceeds the supported depth") from error
    except MemoryError as error:
        raise RoutingError("JSON input exhausted available memory") from error
    _check_json_nodes(value)
    return value


def _check_json_nesting(text: str) -> None:
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
                raise RoutingError(f"JSON nesting exceeds {MAX_JSON_DEPTH} levels")
        elif character in "]}":
            depth -= 1


def _check_json_nodes(value: Any) -> None:
    pending = [value]
    nodes = 0
    while pending:
        item = pending.pop()
        nodes += 1
        if nodes > MAX_JSON_NODES:
            raise RoutingError(f"JSON contains more than {MAX_JSON_NODES} nodes")
        if isinstance(item, dict):
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)


def load_json(path: Path) -> Any:
    """Open once, reject final symlinks/special files, and read at most MAX+1 bytes."""
    _require_secure_open_support()
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    descriptor = _open_with_pinned_directories(path, flags)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise RoutingError("input must be a regular file")
        if metadata.st_size > MAX_INPUT_BYTES:
            raise RoutingError(f"input exceeds {MAX_INPUT_BYTES} bytes")
        with os.fdopen(descriptor, "rb", closefd=True) as stream:
            descriptor = -1
            content = stream.read(MAX_INPUT_BYTES + 1)
        if len(content) > MAX_INPUT_BYTES:
            raise RoutingError(f"input exceeds {MAX_INPUT_BYTES} bytes")
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise RoutingError(f"input must be UTF-8: {error}") from error
        return parse_json(text)
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _open_with_pinned_directories(path: Path, file_flags: int) -> int:
    if ".." in Path(os.fspath(path)).parts:
        raise RoutingError("input path must not contain parent path components")
    absolute = Path(os.path.abspath(os.fspath(path)))
    parts = absolute.parts[1:]
    if not parts:
        raise RoutingError("input path must name a file")
    directory_flags = os.O_RDONLY | os.O_DIRECTORY
    if hasattr(os, "O_CLOEXEC"):
        directory_flags |= os.O_CLOEXEC
    # Follow directory aliases, but pin each resolved directory by descriptor;
    # file_flags still rejects a symlink swapped into the final component.
    try:
        directory_fd = os.open(os.sep, directory_flags)
    except (NotImplementedError, TypeError) as error:
        raise RoutingError(_SECURE_OPEN_DIAGNOSTIC) from error
    try:
        for component in parts[:-1]:
            try:
                next_fd = os.open(component, directory_flags, dir_fd=directory_fd)
            except (NotImplementedError, TypeError) as error:
                raise RoutingError(_SECURE_OPEN_DIAGNOSTIC) from error
            except OSError as error:
                raise RoutingError("input path has a missing, non-directory, or inaccessible ancestor") from error
            os.close(directory_fd)
            directory_fd = next_fd
        try:
            return os.open(parts[-1], file_flags, dir_fd=directory_fd)
        except (NotImplementedError, TypeError) as error:
            raise RoutingError(_SECURE_OPEN_DIAGNOSTIC) from error
        except OSError as error:
            raise RoutingError("input path is a symlink, missing, or inaccessible") from error
    finally:
        os.close(directory_fd)


def _require_secure_open_support() -> None:
    required_flags = ("O_DIRECTORY", "O_NOFOLLOW", "O_NONBLOCK")
    if any(not isinstance(getattr(os, name, None), int) for name in required_flags):
        raise RoutingError(_SECURE_OPEN_DIAGNOSTIC)
    if _ORIGINAL_OS_OPEN not in getattr(os, "supports_dir_fd", ()):
        raise RoutingError(_SECURE_OPEN_DIAGNOSTIC)


def _validate_string_list(name: str, value: Any, allowed: tuple[str, ...] | None) -> list[str]:
    if not isinstance(value, list):
        raise RoutingError(f"{name} must be an array")
    if len(value) > 32:
        raise RoutingError(f"{name} contains too many items")
    result: list[str] = []
    for item in value:
        if not _is_clean_text(item):
            raise RoutingError(f"{name} items must be trimmed, non-control strings no longer than {MAX_TEXT_FIELD} characters")
        if allowed is not None and item not in allowed:
            raise RoutingError(f"{name} items must be one of: {' | '.join(allowed)}")
        if item in result:
            raise RoutingError(f"{name} contains duplicate item: {_display(item)}")
        result.append(item)
    return result


def _validate_operation(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        raise RoutingError("operation_authorization must be an object")
    required = {"packet_id", "revision", "action", "target", "approval", "recovery", "verification", "binding"}
    missing, extra = sorted(required - set(value)), sorted(set(value) - required)
    if missing:
        raise RoutingError(f"missing operation authorization fields: {', '.join(missing)}")
    if extra:
        raise RoutingError(f"unknown operation authorization fields: {', '.join(_display(item) for item in extra)}")
    for key in ("packet_id", "revision", "action", "target"):
        if not _is_clean_text(value[key]):
            raise RoutingError(f"operation_authorization.{key} must be an exact trimmed non-control string")
    enums = {
        "approval": ("explicit trusted-user authorization",),
        "recovery": ("recoverable", "irreversible"),
        "verification": ("independent verifier",),
    }
    for key, choices in enums.items():
        if value[key] not in choices:
            raise RoutingError(f"operation_authorization.{key} must be one of: {' | '.join(choices)}")
    expected_binding = _authorization_binding(value["packet_id"], value["revision"], value["action"], value["target"])
    if value["binding"] != expected_binding:
        raise RoutingError("operation_authorization.binding does not match the canonical packet reference")
    return dict(value)


def _validate_external_verification(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        raise RoutingError("external_verification must be an object")
    required = {"operator_packet_id", "operator_revision", "action", "target", "authorization_binding", "scope", "approval", "access", "evidence"}
    missing, extra = sorted(required - set(value)), sorted(set(value) - required)
    if missing:
        raise RoutingError(f"missing external verification fields: {', '.join(missing)}")
    if extra:
        raise RoutingError(f"unknown external verification fields: {', '.join(_display(item) for item in extra)}")
    for key in ("operator_packet_id", "operator_revision", "action", "target", "scope"):
        item = value[key]
        if not _is_clean_text(item):
            raise RoutingError(f"external_verification.{key} must be an exact trimmed non-control string")
    enums = {
        "approval": ("explicit trusted-user authorization",),
        "access": ("public read-only",),
        "evidence": ("independent direct observation",),
    }
    for key, choices in enums.items():
        if value[key] not in choices:
            raise RoutingError(f"external_verification.{key} must be one of: {' | '.join(choices)}")
    expected_binding = _authorization_binding(value["operator_packet_id"], value["operator_revision"], value["action"], value["target"])
    if value["authorization_binding"] != expected_binding:
        raise RoutingError("external_verification authorization binding does not match packet ID, revision, action, and target")
    return dict(value)


def validate_card(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RoutingError("routing card must be a JSON object")
    allowed_fields = set(FIELDS) | set(OPTIONAL_LIST_FIELDS) | OPTIONAL_OBJECT_FIELDS
    missing, extra = sorted(set(FIELDS) - set(value)), sorted(set(value) - allowed_fields)
    if missing:
        raise RoutingError(f"missing routing fields: {', '.join(missing)}")
    if extra:
        raise RoutingError(f"unknown routing fields: {', '.join(_display(item) for item in extra)}")

    card: dict[str, Any] = {}
    for field, allowed in FIELDS.items():
        item = value[field]
        if not isinstance(item, str) or item not in allowed:
            raise RoutingError(f"{field} must be one of: {' | '.join(allowed)}")
        card[field] = item
    for field, allowed in OPTIONAL_LIST_FIELDS.items():
        card[field] = _validate_string_list(field, value.get(field, []), allowed)
    operation = value.get("operation_authorization")
    card["operation_authorization"] = _validate_operation(operation) if operation is not None else None
    verification = value.get("external_verification")
    card["external_verification"] = _validate_external_verification(verification) if verification is not None else None
    shape = card["work_shape"]
    authority = card["change_authority"]
    capabilities = set(card["required_capabilities"])
    tools = set(card["required_tools"])
    deferred_capabilities = set(card["deferred_capabilities"])
    deferred_tools = set(card["deferred_tools"])
    if deferred_capabilities.intersection({"external-operation", "external-verification"}) or "network" in deferred_tools:
        raise RoutingError("privileged external capabilities and network cannot be deferred; reroute a complete exact authorization card")
    if shape == "verify-external" and (card["ambiguity"] != "settled" or card["router_confidence"] != "high"):
        raise RoutingError("verify-external requires settled ambiguity and high router confidence")
    if "external-verification" in capabilities and shape != "verify-external":
        raise RoutingError("external-verification capability is only valid for work_shape=verify-external")
    if "external-operation" in capabilities and shape != "operate":
        raise RoutingError("external-operation capability is only valid for work_shape=operate")
    if "network" in tools and shape not in {"operate", "verify-external"}:
        raise RoutingError("network tool is only valid for work_shape=operate or verify-external")
    mutating_shapes = {"implement", "debug", "migrate"}
    if shape in mutating_shapes and authority not in {"owned local paths", "shared contract"}:
        raise RoutingError(f"work_shape={shape} requires owned local paths or shared contract authority")
    if shape in {"map", "extract", "diagnose", "plan", "test", "review", "verify-external"} and authority != "none":
        raise RoutingError(f"work_shape={shape} requires change_authority=none")
    if authority == "owned-path deletion":
        raise RoutingError("owned-path deletion is unsupported by current read-only operator policy")
    if card["change_authority"] == "external/destructive":
        if card["work_shape"] != "operate":
            raise RoutingError("external/destructive authority requires work_shape=operate")
        if card["operation_authorization"] is None:
            raise RoutingError("external/destructive authority requires operation_authorization")
        if card["ambiguity"] != "settled" or card["router_confidence"] != "high":
            raise RoutingError("external/destructive operation requires settled ambiguity and high router confidence")
        if "security boundary" not in _boundaries(card):
            raise RoutingError("external/destructive operation requires a security boundary")
        if "external-operation" not in card["required_capabilities"] or not {"network", "shell"}.issubset(card["required_tools"]):
            raise RoutingError("external/destructive operation requires external-operation capability and network and shell tools")
        if card["tool_loop"] != "repeated external tools":
            raise RoutingError("external/destructive operation requires repeated external tools")
    elif card["operation_authorization"] is not None:
        raise RoutingError("operation_authorization is only valid for external/destructive authority")
    elif card["work_shape"] == "operate":
        raise RoutingError("work_shape=operate requires external/destructive authority")
    if shape == "verify-external":
        if card["external_verification"] is None:
            raise RoutingError("verify-external requires external_verification")
        if "security boundary" not in _boundaries(card):
            raise RoutingError("verify-external requires a security boundary")
        if "external-verification" not in card["required_capabilities"] or not {"network", "shell"}.issubset(card["required_tools"]):
            raise RoutingError("verify-external requires external-verification capability and network and shell tools")
        if card["tool_loop"] != "repeated external tools":
            raise RoutingError("verify-external requires repeated external tools")
        raise RoutingError(EXTERNAL_EXECUTION_UNAVAILABLE)
    elif card["external_verification"] is not None:
        raise RoutingError("external_verification is only valid for work_shape=verify-external")
    if shape == "operate":
        raise RoutingError(EXTERNAL_EXECUTION_UNAVAILABLE)
    return card


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def _boundaries(card: dict[str, Any]) -> set[str]:
    result = set(card["contract_boundaries"])
    if card["contract"] in BOUNDARIES:
        result.add(card["contract"])
    return result


def _is_complex_execution(card: dict[str, Any], boundaries: set[str]) -> bool:
    return bool(boundaries) or any((
        card["scope"] in {"cross-component", "cross-system"},
        card["ambiguity"] in {"competing hypotheses", "open-ended"},
        card["tool_loop"] == "repeated external tools",
        card["impact"] in {"shared system", "production-critical"},
        card["context_profile"] in {"noisy logs/large artifacts", "long-running history"},
        card["change_authority"] in {"shared contract", "owned-path deletion"},
    ))


def _validate_role_requirements(role: str, card: dict[str, Any]) -> None:
    checks = (
        ("required_capabilities", ROLE_CAPABILITIES[role]),
        ("required_modalities", ROLE_MODALITIES[role]),
        ("required_tools", ROLE_TOOLS[role]),
    )
    for field, exposed in checks:
        missing = sorted(set(card[field]) - exposed)
        if missing:
            raise RoutingError(f"{role} lacks {field}: {', '.join(missing)}")


def _is_fast_path(card: dict[str, str]) -> bool:
    """Return whether an implementation packet can skip planning and review fan-out."""
    return (
        card["work_shape"] == "implement"
        and card["scope"] in {"one file", "bounded component"}
        and card["ambiguity"] == "settled"
        and card["contract"] in {"none", "internal"}
        and card["tool_loop"] in {"none", "one read/check", "repeated local tools"}
        and card["impact"] in {"reversible", "user-visible"}
        and card["evidence_bar"] in {"syntax", "focused test"}
        and card["context_profile"] in {"compact facts", "focused source set"}
        and card["parallelism"] == "none"
        and card["change_authority"] == "owned local paths"
        and card["router_confidence"] == "high"
        and not any(card[field] for field in OPTIONAL_LIST_FIELDS)
    )


def _is_fast_diagnosis(card: dict[str, Any]) -> bool:
    """Return whether a settled diagnosis can use one bounded investigator directly."""
    return (
        card["work_shape"] == "diagnose"
        and card["scope"] in {"one file", "bounded component"}
        and card["ambiguity"] == "settled"
        and card["contract"] in {"none", "internal"}
        and card["tool_loop"] in {"none", "one read/check", "repeated local tools"}
        and card["impact"] in {"reversible", "user-visible"}
        and card["evidence_bar"] in {"syntax", "focused test"}
        and card["context_profile"] in {"compact facts", "focused source set"}
        and card["parallelism"] == "none"
        and card["change_authority"] == "none"
        and card["router_confidence"] == "high"
        and not any(card[field] for field in OPTIONAL_LIST_FIELDS)
    )


def expected_output_keys(card_value: Any) -> set[str]:
    """Return the exact replay schema without changing legacy route outputs."""
    card = validate_card(card_value)
    return DIRECT_DIAGNOSIS_OUTPUT_KEYS if _is_fast_diagnosis(card) else OUTPUT_KEYS


def route(card_value: Any) -> dict[str, Any]:
    card = validate_card(card_value)
    shape = card["work_shape"]
    boundaries = _boundaries(card)
    security_boundary = "security boundary" in boundaries
    persistent_boundary = "persistent data" in boundaries
    public_boundary = "public API" in boundaries
    migration_change = shape == "migrate" or (shape == "implement" and persistent_boundary)
    unsettled_read = shape in {"map", "extract", "diagnose"} and (
        card["ambiguity"] != "settled" or card["router_confidence"] != "high"
    )
    needs_planning = shape == "plan" or unsettled_read or card["router_confidence"] == "unresolved" or card["ambiguity"] == "open-ended"
    reasons: list[str] = []

    if shape == "operate":
        role = "awb_operator"
        reasons.append("an exact authorized external action requires the least-authority operator")
    elif shape == "verify-external":
        role = "awb_verifier"
        reasons.append("separately authorized public read-only external verification requires direct independent observation")
    elif needs_planning:
        role = "awb_planner"
        reasons.append("read-only evidence or routing remains unsettled" if unsettled_read else "architecture, packet boundaries, or routing remain unresolved")
    elif shape == "review":
        role = "awb_security_reviewer" if security_boundary else "awb_reviewer"
        reasons.append("review packets use an independent findings-only role")
    elif migration_change:
        role = "awb_migration_worker"
        reasons.append("persistent-data or migration work requires rollout, observability, and recovery analysis")
    elif shape in {"map", "extract", "diagnose"}:
        narrow_read = (
            card["ambiguity"] == "settled"
            and not boundaries
            and card["change_authority"] == "none"
            and card["router_confidence"] == "high"
            and (shape != "diagnose" or _is_fast_diagnosis(card))
        )
        role = "awb_fast_investigator" if narrow_read else "awb_deep_investigator"
        if shape == "diagnose":
            reasons.append(
                "settled bounded diagnosis fits one direct efficient investigator"
                if narrow_read
                else "settled consequential diagnosis needs a terminal frontier investigator"
            )
        else:
            reasons.append("settled narrow evidence fits the efficient investigator" if narrow_read else "settled consequential read-only work needs a terminal frontier investigator")
    elif shape == "test":
        focused = card["evidence_bar"] in {"syntax", "focused test"} and card["impact"] in {"reversible", "user-visible"} and not security_boundary
        role = "awb_verifier" if focused else "awb_test_engineer"
        reasons.append("focused deterministic acceptance checks fit the verifier" if focused else "integration, failure-path, or high-impact validation needs the test engineer")
    elif shape == "debug":
        role = "awb_deep_worker"
        reasons.append("debugging requires hypothesis formation and an iterative tool loop")
    elif shape == "implement":
        role = "awb_deep_worker" if _is_complex_execution(card, boundaries) else "awb_builder"
        reasons.append("risk, ambiguity, context, or blast radius requires a frontier worker" if role == "awb_deep_worker" else "the interface and ownership are bounded enough for the balanced builder")
    else:
        raise RoutingError(f"no routing rule for work_shape={shape}")

    planning_map = {
        "required_capabilities": "planning_capabilities",
        "required_modalities": "planning_modalities",
        "required_tools": "planning_tools",
        "required_skills": "planning_skills",
    }
    deferred_map = {
        "required_capabilities": "deferred_capabilities",
        "required_modalities": "deferred_modalities",
        "required_tools": "deferred_tools",
        "required_skills": "deferred_skills",
    }
    if role == "awb_planner":
        current_requirements = {field: list(card[planning_field]) for field, planning_field in planning_map.items()}
        deferred_requirements = {
            deferred_field: _unique(list(card[field]) + list(card[deferred_field]))
            for field, deferred_field in deferred_map.items()
        }
        current_change_authority = "none"
        deferred_change_authority = card["change_authority"]
    else:
        if any(card[field] for field in (*planning_map.values(), *deferred_map.values())):
            raise RoutingError("planning and deferred requirements are only valid when routing to awb_planner")
        current_requirements = {field: list(card[field]) for field in planning_map}
        deferred_requirements = {field: [] for field in deferred_map.values()}
        current_change_authority = card["change_authority"]
        deferred_change_authority = None
    requirement_card = dict(card, **current_requirements)
    _validate_role_requirements(role, requirement_card)
    implementation_roles = {"awb_builder", "awb_deep_worker", "awb_migration_worker"}
    followups: set[str] = set()
    if role in implementation_roles or role == "awb_operator":
        followups.add("awb_verifier")
    if role in implementation_roles and card["evidence_bar"] in {"integration/regression", "independent review"}:
        followups.add("awb_test_engineer")
    if role in implementation_roles and card["impact"] in {"shared system", "production-critical"}:
        followups.add("awb_test_engineer")
    if role in implementation_roles and card["evidence_bar"] == "independent review":
        followups.add("awb_reviewer")
    if persistent_boundary and role in implementation_roles:
        followups.update(("awb_test_engineer", "awb_reviewer"))
    if role == "awb_migration_worker":
        followups.update(("awb_test_engineer", "awb_reviewer"))
    if public_boundary and role in implementation_roles:
        followups.add("awb_reviewer")
    if security_boundary and role not in {"awb_planner", "awb_security_reviewer"}:
        followups.add("awb_security_reviewer")
    if role == "awb_operator":
        followups.add("awb_security_reviewer")
    ordered_followups = [
        followup
        for followup in ("awb_test_engineer", "awb_verifier", "awb_reviewer", "awb_security_reviewer")
        if followup in followups
    ]

    critical = security_boundary or persistent_boundary or role in {"awb_operator", "awb_migration_worker"} or card["impact"] == "production-critical"
    if critical:
        task_class = "critical"
    elif role in {"awb_planner", "awb_deep_investigator", "awb_deep_worker", "awb_reviewer"}:
        task_class = "complex"
    elif role in {"awb_builder", "awb_test_engineer", "awb_verifier"}:
        task_class = "bounded"
    else:
        task_class = "routine"

    required_skills = list(current_requirements["required_skills"])
    if role in implementation_roles and "implementation-quality-governance" not in required_skills:
        required_skills.append("implementation-quality-governance")
    if role == "awb_planner" and shape in {"implement", "debug", "migrate"}:
        if "implementation-quality-governance" not in deferred_requirements["deferred_skills"]:
            deferred_requirements["deferred_skills"].append("implementation-quality-governance")
    authorization = card["operation_authorization"] or card["external_verification"]
    if card["operation_authorization"]:
        authorization_reference = {
            "packet_id": authorization["packet_id"], "revision": authorization["revision"],
            "action": authorization["action"], "target": authorization["target"],
        }
        authorization_binding = authorization["binding"]
    elif card["external_verification"]:
        authorization_reference = {
            "packet_id": authorization["operator_packet_id"], "revision": authorization["operator_revision"],
            "action": authorization["action"], "target": authorization["target"],
        }
        authorization_binding = authorization["authorization_binding"]
    else:
        authorization_reference = None
        authorization_binding = None
    tier, effort = ROLE_PROFILE[role]
    fast_diagnosis = _is_fast_diagnosis(card)
    fast_path = _is_fast_path(card) or fast_diagnosis
    result = {
        "primary_role": role,
        "execution_path": "fast" if fast_path else "standard",
        "task_class": task_class,
        "capability_tier": tier,
        "effort": effort,
        "required_followups": ordered_followups,
        "reroute_after_planning": role == "awb_planner",
        "must_not_downgrade": critical or public_boundary,
        "required_capabilities": current_requirements["required_capabilities"],
        "required_modalities": current_requirements["required_modalities"],
        "required_tools": current_requirements["required_tools"],
        "required_skills": required_skills,
        "skill_fallback_required": bool(required_skills or deferred_requirements["deferred_skills"]),
        "reasons": reasons,
        **deferred_requirements,
        "current_change_authority": current_change_authority,
        "deferred_change_authority": deferred_change_authority,
        "authorization_binding": authorization_binding,
        "authorization_reference": authorization_reference,
    }
    if fast_diagnosis:
        result["lifecycle"] = dict(DIRECT_DIAGNOSIS_LIFECYCLE)
    return result


def _validate_probe_query(value: Any) -> tuple[dict[str, Any], list[str]]:
    if not isinstance(value, dict):
        raise RoutingError("ownership probe query result must be an object")
    missing, extra = sorted(PROBE_QUERY_KEYS - set(value)), sorted(set(value) - PROBE_QUERY_KEYS)
    if missing:
        raise RoutingError(f"missing ownership probe query fields: {', '.join(missing)}")
    if extra:
        raise RoutingError(f"unknown ownership probe query fields: {', '.join(_display(item) for item in extra)}")
    artifact_class = value["artifact_class"]
    if artifact_class not in PROBE_ARTIFACT_REGISTRY:
        raise RoutingError(f"query artifact_class is outside the closed registry: {_display(artifact_class)}")
    for field in ("complete", "truncated", "symlink_encountered", "symlinks_followed"):
        if type(value[field]) is not bool:
            raise RoutingError(f"ownership probe query {field} must be a boolean")
    if value["symlinks_followed"]:
        raise RoutingError("ownership probe query must not follow symlinks")
    if value["complete"] and (value["truncated"] or value["symlink_encountered"]):
        raise RoutingError("ownership probe query cannot be complete when truncated or symlink-affected")
    matches = value["matches"]
    if not isinstance(matches, list):
        raise RoutingError("ownership probe query matches must be an array")
    if len(matches) > MAX_PROBE_MATCHES:
        raise RoutingError(f"ownership probe query exceeds {MAX_PROBE_MATCHES} matches")
    if matches != sorted(set(matches)):
        raise RoutingError("ownership probe query matches must be unique and sorted")
    path_pattern = re.compile(PROBE_ARTIFACT_REGISTRY[artifact_class]["accepted_path_pattern"])
    accepted_matches: list[str] = []
    for match in matches:
        if not _is_canonical_repository_path(match):
            raise RoutingError(f"ownership probe match must be a canonical repository-relative path: {_display(match)}")
        if path_pattern.fullmatch(match) is not None:
            accepted_matches.append(match)
        else:
            raise RoutingError("ownership probe adapter returned a path outside its accepted class pattern")
    validated = {
        "artifact_class": artifact_class,
        "complete": value["complete"],
        "truncated": value["truncated"],
        "symlink_encountered": value["symlink_encountered"],
        "symlinks_followed": False,
        "matches": list(matches),
    }
    return validated, accepted_matches


def _is_canonical_workspace_identity(value: Any) -> bool:
    return (
        _is_clean_text(value)
        and os.path.isabs(value)
        and os.path.normpath(value) == value
        and os.path.realpath(value) == value
    )


def _validate_probe_adapter_result(value: Any, expected_workspace_identity: Any) -> list[dict[str, Any]]:
    if not isinstance(value, dict) or set(value) != PROBE_ADAPTER_RESULT_KEYS:
        raise RoutingError("ownership probe adapter result has an invalid schema")
    if value["adapter_result_version"] != 1 or value["tool_name"] != "scan_required_artifacts":
        raise RoutingError("ownership probe adapter identity differs from the protected tool contract")
    if (
        value["descriptor_version"] != PROBE_DESCRIPTOR_VERSION
        or value["descriptor_sha256"] != ownership_probe_descriptor_sha256()
    ):
        raise RoutingError("ownership probe adapter descriptor binding differs from the protected contract")
    if value["workspace_identity"] != expected_workspace_identity or not _is_canonical_workspace_identity(
        value["workspace_identity"]
    ):
        raise RoutingError("ownership probe adapter workspace differs from the host canonical workspace")
    raw_queries = value["query_results"]
    if not isinstance(raw_queries, list) or len(raw_queries) != len(PROBE_ARTIFACT_REGISTRY):
        raise RoutingError("ownership probe adapter requires exactly three artifact-class results")
    queries = [_validate_probe_query(query)[0] for query in raw_queries]
    if [query["artifact_class"] for query in queries] != list(PROBE_ARTIFACT_REGISTRY):
        raise RoutingError("ownership probe adapter results must use every class in canonical order")
    return queries


def build_ownership_probe_adapter_result(value: Any) -> dict[str, Any]:
    """Build a protected adapter result for offline validation and replay only."""
    if not isinstance(value, dict):
        raise RoutingError("ownership probe packet must be a JSON object")
    missing, extra = sorted(PROBE_INPUT_KEYS - set(value)), sorted(set(value) - PROBE_INPUT_KEYS)
    if missing:
        raise RoutingError(f"missing ownership probe fields: {', '.join(missing)}")
    if extra:
        raise RoutingError(f"unknown ownership probe fields: {', '.join(_display(item) for item in extra)}")
    if value["phase"] != "probe-ownership":
        raise RoutingError("ownership probe phase must be probe-ownership")
    descriptor = ownership_probe_descriptor()
    descriptor_sha256 = ownership_probe_descriptor_sha256()
    if value["registry_descriptor"] != descriptor:
        raise RoutingError("ownership probe registry descriptor differs from the canonical pre-query contract")
    if value["registry_descriptor_sha256"] != descriptor_sha256:
        raise RoutingError("ownership probe registry descriptor binding differs from the canonical pre-query contract")
    if not _is_canonical_workspace_identity(value["host_canonical_workspace_identity"]):
        raise RoutingError("host canonical workspace identity must be an exact canonical absolute path")
    raw_queries = value["query_results"]
    if not isinstance(raw_queries, list) or len(raw_queries) != len(PROBE_ARTIFACT_REGISTRY):
        raise RoutingError("ownership probe requires exactly three fixed artifact-class query results")
    queries = [_validate_probe_query(query)[0] for query in raw_queries]
    query_classes = [query["artifact_class"] for query in queries]
    expected_classes = list(PROBE_ARTIFACT_REGISTRY)
    if query_classes != expected_classes:
        raise RoutingError("ownership probe query results must use every fixed artifact class in canonical order")

    adapter_result = {
        "adapter_result_version": 1,
        "tool_name": "scan_required_artifacts",
        "descriptor_version": descriptor["version"],
        "descriptor_sha256": descriptor_sha256,
        "workspace_identity": value["host_canonical_workspace_identity"],
        "query_results": queries,
    }
    _validate_probe_adapter_result(adapter_result, value["host_canonical_workspace_identity"])
    return adapter_result


def evaluate_ownership_probe_result(
    descriptor: Any,
    expected_parent_context: Any,
    expected_parent_context_sha256: Any,
) -> str:
    """Fail-closed parity evaluator using only the exact parent-retained context."""
    try:
        if descriptor != ownership_probe_descriptor():
            return "inconclusive-delegate"
        if not isinstance(expected_parent_context_sha256, str):
            return "inconclusive-delegate"
        retained_digest = ownership_probe_parent_context_sha256(expected_parent_context)
        if expected_parent_context_sha256 != retained_digest:
            return "inconclusive-delegate"
        queries = _validate_probe_adapter_result(
            expected_parent_context["adapter_result"],
            expected_parent_context["host_canonical_workspace_identity"],
        )
    except (RoutingError, TypeError, ValueError):
        return "inconclusive-delegate"
    required = expected_parent_context["required_artifact_classes"]
    if expected_parent_context["declaration_conflict"] or any(
        artifact_class not in PROBE_ARTIFACT_REGISTRY for artifact_class in required
    ):
        return "inconclusive-delegate"
    if any(
        not query["complete"]
        or query["truncated"]
        or query["symlink_encountered"]
        or query["symlinks_followed"]
        for query in queries
    ):
        return "inconclusive-delegate"
    matches = {query["artifact_class"]: query["matches"] for query in queries}
    return "owner-artifact-present" if any(matches[item] for item in required) else "known-artifact-mismatch"


def probe_ownership(value: Any) -> dict[str, Any]:
    """Classify an ownership packet using offline validation/test tooling only."""
    adapter_result = build_ownership_probe_adapter_result(value)
    direct_identity = value["direct_user_objective_repository_identity"]
    required = value["required_artifact_classes"]
    accepted_map = {item["artifact_class"]: item["matches"] for item in adapter_result["query_results"]}
    matched_required = [item for item in required if item in accepted_map and accepted_map[item]]
    descriptor = ownership_probe_descriptor()
    parent_context = ownership_probe_parent_context(
        descriptor,
        required,
        value["declaration_conflict"],
        direct_identity,
        value["host_canonical_workspace_identity"],
        adapter_result,
    )
    parent_context_sha256 = ownership_probe_parent_context_sha256(parent_context)
    outcome = evaluate_ownership_probe_result(
        descriptor,
        parent_context,
        parent_context_sha256,
    )
    if outcome == "inconclusive-delegate":
        outcome, routing_action, required_input = _unresolved_ownership_fallback(required, direct_identity)
    elif outcome == "owner-artifact-present":
        routing_action = "normal-reroute"
        required_input = None
    else:
        outcome = "known-artifact-mismatch"
        routing_action = "stop-before-planner"
        required_input = None if direct_identity is not None else OWNERSHIP_REPOSITORY_REQUIRED_INPUT
    artifact_queries = [
        {
            "artifact_class": name,
            "scan": "protected-mcp-roots-list-metadata",
            "max_matches": MAX_PROBE_MATCHES,
        }
        for name in PROBE_ARTIFACT_REGISTRY
    ]
    result = {
        "phase": "probe-ownership",
        "primary_role": PROBE_ROLE,
        "execution_path": "probe",
        "capability_tier": "efficient",
        "effort": "low",
        "required_followups": [],
        "artifact_queries": artifact_queries,
        "required_artifact_classes": list(required),
        "matched_required_classes": matched_required,
        "outcome": outcome,
        "routing_action": routing_action,
        "expected_owner_identity": direct_identity if outcome == "known-artifact-mismatch" else None,
        "required_input": required_input,
        "lifecycle": dict(PROBE_LIFECYCLE),
        "planner_count": 0,
        "probe_child_count": 0,
        "wait_count": 0,
        "virtual_elapsed_seconds_upper_bound": 59,
    }
    if set(result) != PROBE_OUTPUT_KEYS:
        raise AssertionError("ownership probe output schema drifted")
    return result


def check_replay(path: Path) -> int:
    data = load_json(path)
    if not isinstance(data, list):
        raise RoutingError("replay file must contain a JSON array")
    failures: list[str] = []
    seen_ids: set[str] = set()
    for index, case in enumerate(data):
        label = f"case {index}"
        if not isinstance(case, dict):
            failures.append(f"{label}: must be an object")
            continue
        is_probe = "probe" in case
        required = {"id", "probe"} if is_probe else {"id", "card"}
        allowed = required | {"expected", "expected_error"}
        missing, extra = sorted(required - set(case)), sorted(set(case) - allowed)
        expectation_count = sum(name in case for name in ("expected", "expected_error"))
        if missing or extra or expectation_count != 1:
            failures.append(f"{label}: invalid keys or expectation (missing={_display(missing)}, unknown={_display(extra)})")
            continue
        case_id = case["id"]
        if not isinstance(case_id, str) or not REPLAY_ID.fullmatch(case_id):
            failures.append(f"{label}: id must match {REPLAY_ID.pattern}: {_display(case_id)}")
            continue
        if case_id in seen_ids:
            failures.append(f"{_display(case_id)}: duplicate id")
            continue
        seen_ids.add(case_id)
        expected = case.get("expected")
        expected_error = case.get("expected_error")
        if expected is not None:
            if not isinstance(expected, dict):
                failures.append(f"{case_id}: expected must be an object")
                continue
            exact_output_keys = PROBE_OUTPUT_KEYS if is_probe else expected_output_keys(case["card"])
            missing_expected, unknown_expected = sorted(exact_output_keys - set(expected)), sorted(set(expected) - exact_output_keys)
            if missing_expected or unknown_expected:
                failures.append(f"{_display(case_id)}: invalid expected keys (missing={_display(missing_expected)}, unknown={_display(unknown_expected)})")
                continue
        elif not _is_clean_text(expected_error):
            failures.append(f"{case_id}: expected_error must be an exact trimmed non-control string")
            continue
        try:
            if is_probe:
                if not isinstance(case["probe"], dict):
                    raise RoutingError("probe replay input must be an object")
                replay_probe_keys = PROBE_INPUT_KEYS - {
                    "phase",
                    "registry_descriptor",
                    "registry_descriptor_sha256",
                    "host_canonical_workspace_identity",
                }
                missing_probe = sorted(replay_probe_keys - set(case["probe"]))
                extra_probe = sorted(set(case["probe"]) - replay_probe_keys)
                if missing_probe or extra_probe:
                    raise RoutingError(
                        "probe replay fields differ from the descriptor-first packet schema "
                        f"(missing={_display(missing_probe)}, unknown={_display(extra_probe)})"
                    )
                descriptor = ownership_probe_descriptor()
                packet = {
                    "phase": descriptor["phase"],
                    "registry_descriptor": descriptor,
                    "registry_descriptor_sha256": ownership_probe_descriptor_sha256(),
                    "host_canonical_workspace_identity": "/workspace/current",
                    **case["probe"],
                }
                actual = probe_ownership(packet)
            else:
                actual = route(case["card"])
        except (RoutingError, KeyError) as error:
            if expected_error is None or str(error) != expected_error:
                failures.append(f"{_display(case_id)}: routing failed: {error}")
            continue
        if expected_error is not None:
            failures.append(f"{_display(case_id)}: expected routing error {_display(expected_error)}, got successful output")
        elif actual != expected:
            failures.append(f"{_display(case_id)}: expected {_display(expected)}, got {_display(actual)}")
    if failures:
        for failure in failures:
            print(f"ERROR: {failure}", file=sys.stderr)
        return 1
    print(
        f"Routing replay passed ({len(data)} cases; ownership probe descriptor sha256 "
        f"{ownership_probe_descriptor_sha256()})."
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--card", type=Path, help="JSON routing card to classify")
    source.add_argument("--replay", type=Path, help="JSON replay set to validate")
    source.add_argument(
        "--probe-ownership",
        type=Path,
        help="OFFLINE validation/test only: classify a bounded ownership-probe metadata packet; forbidden in runtime pre-ownership flow",
    )
    source.add_argument(
        "--describe-ownership-probe",
        action="store_true",
        help="OFFLINE validation/test only: print the canonical ownership-probe registry; forbidden in runtime pre-ownership flow",
    )
    args = parser.parse_args()
    try:
        if args.replay:
            return check_replay(args.replay)
        if args.probe_ownership:
            print(json.dumps(probe_ownership(load_json(args.probe_ownership)), indent=2, sort_keys=True))
            return 0
        if args.describe_ownership_probe:
            print(json.dumps(ownership_probe_descriptor(), indent=2, sort_keys=True))
            return 0
        print(json.dumps(route(load_json(args.card)), indent=2, sort_keys=True))
        return 0
    except (OSError, UnicodeError, json.JSONDecodeError, RoutingError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
