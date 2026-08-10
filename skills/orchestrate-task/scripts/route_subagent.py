#!/usr/bin/env python3
"""Deterministically route one normalized Agent Workbench child packet."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


FIELDS: dict[str, tuple[str, ...]] = {
    "work_shape": ("map", "plan", "extract", "implement", "test", "debug", "migrate", "review"),
    "scope": ("one file", "bounded component", "cross-component", "cross-system"),
    "ambiguity": ("settled", "local unknown", "competing hypotheses", "open-ended"),
    "contract": ("none", "internal", "public API", "persistent data", "security boundary"),
    "tool_loop": ("none", "one read/check", "repeated local tools", "repeated external tools"),
    "impact": ("reversible", "user-visible", "shared system", "production-critical"),
    "evidence_bar": ("syntax", "focused test", "integration/regression", "independent review"),
    "context_profile": ("compact facts", "focused source set", "noisy logs/large artifacts", "long-running history"),
    "parallelism": ("none", "independent read-only", "independent writes", "dependent sequence"),
    "change_authority": ("none", "owned local paths", "shared contract", "external/destructive"),
    "router_confidence": ("high", "uncertain", "unresolved"),
}

ROLE_PROFILE: dict[str, tuple[str, str]] = {
    "awb_fast_investigator": ("efficient", "low"),
    "awb_planner": ("frontier", "high"),
    "awb_builder": ("balanced", "medium"),
    "awb_deep_worker": ("frontier", "high"),
    "awb_migration_worker": ("frontier", "maximum"),
    "awb_verifier": ("balanced", "medium"),
    "awb_test_engineer": ("balanced", "high"),
    "awb_reviewer": ("frontier", "high"),
    "awb_security_reviewer": ("frontier", "maximum"),
}
MAX_INPUT_BYTES = 1_048_576


class RoutingError(ValueError):
    """Raised when a routing card is incomplete or unsupported."""


def parse_json(text: str) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise RoutingError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    return json.loads(text, object_pairs_hook=reject_duplicates)


def load_json(path: Path) -> Any:
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise RoutingError(f"input exceeds {MAX_INPUT_BYTES} bytes")
    return parse_json(path.read_text(encoding="utf-8"))


def validate_card(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        raise RoutingError("routing card must be a JSON object")

    missing = sorted(set(FIELDS) - set(value))
    extra = sorted(set(value) - set(FIELDS))
    if missing:
        raise RoutingError(f"missing routing fields: {', '.join(missing)}")
    if extra:
        raise RoutingError(f"unknown routing fields: {', '.join(extra)}")

    card: dict[str, str] = {}
    for field, allowed in FIELDS.items():
        item = value[field]
        if not isinstance(item, str) or item not in allowed:
            choices = " | ".join(allowed)
            raise RoutingError(f"{field} must be one of: {choices}")
        card[field] = item
    return card


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def _is_complex_execution(card: dict[str, str]) -> bool:
    return any(
        (
            card["scope"] in {"cross-component", "cross-system"},
            card["ambiguity"] in {"competing hypotheses", "open-ended"},
            card["contract"] in {"public API", "persistent data", "security boundary"},
            card["tool_loop"] == "repeated external tools",
            card["impact"] in {"shared system", "production-critical"},
            card["context_profile"] in {"noisy logs/large artifacts", "long-running history"},
            card["change_authority"] in {"shared contract", "external/destructive"},
        )
    )


def route(card_value: Any) -> dict[str, Any]:
    card = validate_card(card_value)
    shape = card["work_shape"]
    security_boundary = (
        card["contract"] == "security boundary"
        or card["change_authority"] == "external/destructive"
    )
    migration_change = shape == "migrate" or (
        shape == "implement" and card["contract"] == "persistent data"
    )
    needs_planning = (
        shape == "plan"
        or card["router_confidence"] == "unresolved"
        or card["ambiguity"] == "open-ended"
    )
    reasons: list[str] = []

    if needs_planning:
        role = "awb_planner"
        reasons.append("architecture, packet boundaries, or routing remain unresolved")
    elif shape == "review":
        role = "awb_security_reviewer" if security_boundary else "awb_reviewer"
        reasons.append("review packets use an independent findings-only role")
    elif migration_change:
        role = "awb_migration_worker"
        reasons.append("persistent-data or migration work requires rollout and rollback analysis")
    elif shape in {"map", "extract"}:
        narrow_read = (
            card["ambiguity"] == "settled"
            and card["contract"] in {"none", "internal"}
            and card["change_authority"] == "none"
            and card["router_confidence"] == "high"
        )
        role = "awb_fast_investigator" if narrow_read else "awb_planner"
        reasons.append(
            "settled read-only evidence can use the efficient profile"
            if narrow_read
            else "read-only work still needs a planner because its boundary is unsettled or consequential"
        )
    elif shape == "test":
        focused = (
            card["evidence_bar"] in {"syntax", "focused test"}
            and card["impact"] in {"reversible", "user-visible"}
            and not security_boundary
        )
        role = "awb_verifier" if focused else "awb_test_engineer"
        reasons.append(
            "focused deterministic acceptance checks fit the verifier"
            if focused
            else "integration, failure-path, or high-impact validation needs the test engineer"
        )
    elif shape == "debug":
        role = "awb_deep_worker"
        reasons.append("debugging requires hypothesis formation and an iterative tool loop")
    elif shape == "implement":
        role = "awb_deep_worker" if _is_complex_execution(card) else "awb_builder"
        reasons.append(
            "risk, ambiguity, context, or blast radius requires a frontier worker"
            if role == "awb_deep_worker"
            else "the interface and ownership are bounded enough for the balanced builder"
        )
    else:
        raise RoutingError(f"no routing rule for work_shape={shape}")

    followups: list[str] = []
    if role in {"awb_builder", "awb_deep_worker", "awb_migration_worker"}:
        followups.append("awb_verifier")
    if role == "awb_deep_worker" and (
        card["evidence_bar"] in {"integration/regression", "independent review"}
        or card["impact"] in {"shared system", "production-critical"}
    ):
        followups.append("awb_test_engineer")
    if migration_change and role != "awb_planner":
        followups.extend(("awb_test_engineer", "awb_reviewer"))
    if card["contract"] == "public API" and role not in {"awb_planner", "awb_reviewer"}:
        followups.append("awb_reviewer")
    if security_boundary and role not in {"awb_planner", "awb_security_reviewer"}:
        followups.append("awb_security_reviewer")

    critical = (
        security_boundary
        or card["contract"] == "persistent data"
        or card["impact"] == "production-critical"
        or card["change_authority"] == "external/destructive"
    )
    if critical:
        task_class = "critical"
    elif role in {"awb_planner", "awb_deep_worker", "awb_reviewer"}:
        task_class = "complex"
    elif role in {"awb_builder", "awb_test_engineer", "awb_verifier"}:
        task_class = "bounded"
    else:
        task_class = "routine"

    tier, effort = ROLE_PROFILE[role]
    return {
        "primary_role": role,
        "task_class": task_class,
        "capability_tier": tier,
        "effort": effort,
        "required_followups": _unique(followups),
        "reroute_after_planning": role == "awb_planner",
        "must_not_downgrade": critical or card["contract"] == "public API",
        "reasons": reasons,
    }


def check_replay(path: Path) -> int:
    data = load_json(path)
    if not isinstance(data, list):
        raise RoutingError("replay file must contain a JSON array")
    failures: list[str] = []
    for index, case in enumerate(data):
        if not isinstance(case, dict):
            failures.append(f"case {index}: must be an object")
            continue
        case_id = case.get("id", f"case-{index}")
        try:
            actual = route(case.get("card"))
        except (RoutingError, KeyError) as error:
            failures.append(f"{case_id}: routing failed: {error}")
            continue
        expected = case.get("expected")
        if not isinstance(expected, dict):
            failures.append(f"{case_id}: expected must be an object")
            continue
        for key, expected_value in expected.items():
            if actual.get(key) != expected_value:
                failures.append(
                    f"{case_id}: {key} expected {expected_value!r}, got {actual.get(key)!r}"
                )
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
        card = load_json(args.card)
        print(json.dumps(route(card), indent=2, sort_keys=True))
        return 0
    except (OSError, json.JSONDecodeError, RoutingError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
