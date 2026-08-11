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
    "work_shape": ("map", "plan", "extract", "implement", "test", "debug", "migrate", "review", "operate", "verify-external"),
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
    "awb_operator": frozenset({"read", "external-operation"}),
    "awb_verifier": frozenset({"read", "test", "external-verification"}),
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
ROLE_TOOLS["awb_operator"] = frozenset({"file-read", "shell", "network"})
ROLE_TOOLS["awb_verifier"] = frozenset({"file-read", "shell", "network"})

OUTPUT_KEYS = {
    "primary_role", "task_class", "capability_tier", "effort", "required_followups",
    "reroute_after_planning", "must_not_downgrade", "required_capabilities",
    "required_modalities", "required_tools", "required_skills", "skill_fallback_required",
    "reasons",
    "deferred_capabilities", "deferred_modalities", "deferred_tools", "deferred_skills",
    "current_change_authority", "deferred_change_authority", "authorization_binding", "authorization_reference",
}
MAX_INPUT_BYTES = 1_048_576
MAX_TEXT_FIELD = 512
MAX_JSON_DEPTH = 128
MAX_JSON_NODES = 100_000
REPLAY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


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
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_NONBLOCK"):
        flags |= os.O_NONBLOCK
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
    absolute = Path(os.path.abspath(os.fspath(path)))
    parts = absolute.parts[1:]
    if not parts:
        raise RoutingError("input path must name a file")
    directory_flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        directory_flags |= os.O_DIRECTORY
    if hasattr(os, "O_CLOEXEC"):
        directory_flags |= os.O_CLOEXEC
    # Follow directory aliases, but pin each resolved directory by descriptor;
    # file_flags still rejects a symlink swapped into the final component.
    directory_fd = os.open(os.sep, directory_flags)
    try:
        for component in parts[:-1]:
            try:
                next_fd = os.open(component, directory_flags, dir_fd=directory_fd)
            except OSError as error:
                raise RoutingError("input path has a missing, non-directory, or inaccessible ancestor") from error
            os.close(directory_fd)
            directory_fd = next_fd
        try:
            return os.open(parts[-1], file_flags, dir_fd=directory_fd)
        except OSError as error:
            raise RoutingError("input path is a symlink, missing, or inaccessible") from error
    finally:
        os.close(directory_fd)


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
    if shape in {"map", "extract", "plan", "test", "review", "verify-external"} and authority != "none":
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
    elif card["external_verification"] is not None:
        raise RoutingError("external_verification is only valid for work_shape=verify-external")
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


def route(card_value: Any) -> dict[str, Any]:
    card = validate_card(card_value)
    shape = card["work_shape"]
    boundaries = _boundaries(card)
    security_boundary = "security boundary" in boundaries
    persistent_boundary = "persistent data" in boundaries
    public_boundary = "public API" in boundaries
    migration_change = shape == "migrate" or (shape == "implement" and persistent_boundary)
    needs_planning = shape == "plan" or card["router_confidence"] == "unresolved" or card["ambiguity"] == "open-ended"
    reasons: list[str] = []

    if shape == "operate":
        role = "awb_operator"
        reasons.append("an exact authorized external action requires the least-authority operator")
    elif shape == "verify-external":
        role = "awb_verifier"
        reasons.append("separately authorized public read-only external verification requires direct independent observation")
    elif needs_planning:
        role = "awb_planner"
        reasons.append("architecture, packet boundaries, or routing remain unresolved")
    elif shape == "review":
        role = "awb_security_reviewer" if security_boundary else "awb_reviewer"
        reasons.append("review packets use an independent findings-only role")
    elif migration_change:
        role = "awb_migration_worker"
        reasons.append("persistent-data or migration work requires rollout, observability, and recovery analysis")
    elif shape in {"map", "extract"}:
        narrow_read = card["ambiguity"] == "settled" and not boundaries and card["change_authority"] == "none" and card["router_confidence"] == "high"
        role = "awb_fast_investigator" if narrow_read else "awb_deep_investigator"
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
    followups: list[str] = []
    if role in implementation_roles or role == "awb_operator":
        followups.append("awb_verifier")
    if role in implementation_roles and card["evidence_bar"] in {"integration/regression", "independent review"}:
        followups.append("awb_test_engineer")
    if role in implementation_roles and card["impact"] in {"shared system", "production-critical"}:
        followups.append("awb_test_engineer")
    if role in implementation_roles and card["evidence_bar"] == "independent review":
        followups.append("awb_reviewer")
    if persistent_boundary and role in implementation_roles:
        followups.extend(("awb_test_engineer", "awb_reviewer"))
    if role == "awb_migration_worker":
        followups.extend(("awb_test_engineer", "awb_reviewer"))
    if public_boundary and role in implementation_roles:
        followups.append("awb_reviewer")
    if security_boundary and role not in {"awb_planner", "awb_security_reviewer"}:
        followups.append("awb_security_reviewer")
    if role == "awb_operator":
        followups.append("awb_security_reviewer")

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
    return {
        "primary_role": role,
        "task_class": task_class,
        "capability_tier": tier,
        "effort": effort,
        "required_followups": _unique(followups),
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
        missing, extra = sorted({"id", "card", "expected"} - set(case)), sorted(set(case) - {"id", "card", "expected"})
        if missing or extra:
            failures.append(f"{label}: invalid keys (missing={_display(missing)}, unknown={_display(extra)})")
            continue
        case_id = case["id"]
        if not isinstance(case_id, str) or not REPLAY_ID.fullmatch(case_id):
            failures.append(f"{label}: id must match {REPLAY_ID.pattern}: {_display(case_id)}")
            continue
        if case_id in seen_ids:
            failures.append(f"{_display(case_id)}: duplicate id")
            continue
        seen_ids.add(case_id)
        expected = case["expected"]
        if not isinstance(expected, dict):
            failures.append(f"{case_id}: expected must be an object")
            continue
        missing_expected, unknown_expected = sorted(OUTPUT_KEYS - set(expected)), sorted(set(expected) - OUTPUT_KEYS)
        if missing_expected or unknown_expected:
            failures.append(f"{_display(case_id)}: invalid expected keys (missing={_display(missing_expected)}, unknown={_display(unknown_expected)})")
            continue
        try:
            actual = route(case["card"])
        except (RoutingError, KeyError) as error:
            failures.append(f"{_display(case_id)}: routing failed: {error}")
            continue
        if actual != expected:
            failures.append(f"{_display(case_id)}: expected {_display(expected)}, got {_display(actual)}")
    if failures:
        for failure in failures:
            print(f"ERROR: {failure}", file=sys.stderr)
        return 1
    print(f"Routing replay passed ({len(data)} cases).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--card", type=Path, help="JSON routing card to classify")
    source.add_argument("--replay", type=Path, help="JSON replay set to validate")
    args = parser.parse_args()
    try:
        if args.replay:
            return check_replay(args.replay)
        print(json.dumps(route(load_json(args.card)), indent=2, sort_keys=True))
        return 0
    except (OSError, UnicodeError, json.JSONDecodeError, RoutingError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
