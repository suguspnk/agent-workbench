#!/usr/bin/env python3
"""Score a normalized recurring-work card and recommend the safest artifact."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "1.0"
MIN_PYTHON = (3, 11)
MAX_INPUT_BYTES = 1_048_576
MAX_REPLAY_CASES = 100
CASE_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
FIELDS: dict[str, tuple[str, ...]] = {
    "recurrence": ("none", "one-example", "repeated-history"),
    "value": ("unclear", "plausible", "demonstrated"),
    "boundary": ("open-ended", "partial", "bounded"),
    "completion_check": ("subjective", "human-review", "deterministic"),
    "action_scope": ("read-only", "local-reversible", "external-read-only", "external-reversible", "irreversible"),
    "permission_scope": ("none", "least-privilege", "broad"),
    "state_scope": ("none", "bounded", "unclear"),
    "stop_rule": ("explicit", "human-only", "missing"),
    "requested_autonomy": ("advisory", "supervised", "automatic"),
    "data_handling": ("ordinary", "host-managed-sensitive", "embedded-secret"),
}
POINTS: dict[str, dict[str, int]] = {
    field: {choice: index for index, choice in enumerate(choices)}
    for field, choices in FIELDS.items()
}
POINTS["action_scope"] = {
    "read-only": 2,
    "local-reversible": 2,
    "external-read-only": 1,
    "external-reversible": 1,
    "irreversible": 0,
}
POINTS["permission_scope"] = {"none": 2, "least-privilege": 2, "broad": 0}
POINTS["state_scope"] = {"none": 2, "bounded": 2, "unclear": 0}
POINTS["stop_rule"] = {"explicit": 2, "human-only": 1, "missing": 0}
POINTS["requested_autonomy"] = {"advisory": 2, "supervised": 1, "automatic": 0}
POINTS["data_handling"] = {"ordinary": 2, "host-managed-sensitive": 1, "embedded-secret": 0}
SCORE_MAX = sum(max(values.values()) for values in POINTS.values())
RESULT_FIELDS = {
    "schema_version",
    "outcome",
    "score",
    "score_max",
    "hard_blocks",
    "reasons",
    "required_changes",
    "required_approvals",
    "activation_allowed",
}
OUTCOMES = {
    "reject",
    "manual_workflow",
    "normal_skill",
    "read_only_triage_loop",
    "supervised_loop",
}
READ_ONLY_ACTION_SCOPES = frozenset({"read-only", "external-read-only"})


class ReadinessError(ValueError):
    """Raised when a readiness card or replay file is invalid."""


def parse_json(text: str) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ReadinessError("duplicate JSON key")
            result[key] = value
        return result

    try:
        return json.loads(text, object_pairs_hook=reject_duplicates)
    except ReadinessError:
        raise
    except json.JSONDecodeError as error:
        raise ReadinessError("invalid JSON input") from error
    except RecursionError as error:
        raise ReadinessError("JSON nesting exceeds the supported depth") from error
    except ValueError as error:
        raise ReadinessError("JSON contains an unsupported numeric value") from error


def _read_bounded(source: str | Path) -> bytes:
    source_text = str(source)
    if source_text == "-":
        return sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)

    path = Path(source_text)
    try:
        before = path.lstat()
    except OSError as error:
        raise ReadinessError("input file is unavailable") from error
    if stat.S_ISLNK(before.st_mode):
        raise ReadinessError("input file must not be a symlink")
    if not stat.S_ISREG(before.st_mode):
        raise ReadinessError("input file must be a regular file")

    flags = os.O_RDONLY
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise ReadinessError("input file could not be opened safely") from error
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise ReadinessError("input file must be a regular file")
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            raise ReadinessError("input file changed during safe open")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            return stream.read(MAX_INPUT_BYTES + 1)
    finally:
        os.close(descriptor)


def load_json(source: str | Path) -> Any:
    payload = _read_bounded(source)
    if len(payload) > MAX_INPUT_BYTES:
        raise ReadinessError(f"input exceeds {MAX_INPUT_BYTES} bytes")
    try:
        text = payload.decode("utf-8")
    except UnicodeError as error:
        raise ReadinessError("input is not valid UTF-8") from error
    return parse_json(text)


def validate_card(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ReadinessError("readiness card must be a JSON object")
    missing = set(FIELDS) - set(value)
    unknown = set(value) - set(FIELDS)
    if missing:
        raise ReadinessError("readiness card has missing fields")
    if unknown:
        raise ReadinessError("readiness card has unknown fields")
    card: dict[str, str] = {}
    for field, allowed in FIELDS.items():
        item = value[field]
        if not isinstance(item, str) or item not in allowed:
            raise ReadinessError(f"{field} has an invalid value")
        card[field] = item
    return card


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def score(card_value: Any) -> dict[str, Any]:
    card = validate_card(card_value)
    total = sum(POINTS[field][value] for field, value in card.items())
    hard_blocks: list[str] = []
    reasons: list[str] = []
    changes: list[str] = []
    approvals: list[str] = []

    if card["requested_autonomy"] == "automatic":
        hard_blocks.append("automatic-autonomy")
        changes.append("reduce requested autonomy to supervised or advisory")
    if card["data_handling"] == "embedded-secret":
        hard_blocks.append("embedded-secret")
        changes.append("remove embedded credentials and use an authorized host-managed reference")
    if card["recurrence"] == "none" and card["value"] == "unclear":
        hard_blocks.append("no-recurrence-or-value-evidence")
        changes.append("provide traceable recurrence and value evidence")

    manual_gates = {
        "irreversible-action": card["action_scope"] == "irreversible",
        "broad-permission": card["permission_scope"] == "broad",
        "unclear-state": card["state_scope"] == "unclear",
        "read-only-retained-state": (
            card["action_scope"] in READ_ONLY_ACTION_SCOPES
            and card["state_scope"] == "bounded"
        ),
        "missing-stop-rule": card["stop_rule"] == "missing",
        "unclear-value": card["value"] == "unclear",
        "external-permission-mismatch": (
            card["action_scope"] in {"external-read-only", "external-reversible"}
            and card["permission_scope"] != "least-privilege"
        ),
        "sensitive-permission-mismatch": (
            card["data_handling"] == "host-managed-sensitive"
            and card["permission_scope"] != "least-privilege"
        ),
    }
    if hard_blocks:
        outcome = "reject"
        reasons.append("one or more V1 hard safety gates reject the proposal")
    elif any(manual_gates.values()):
        outcome = "manual_workflow"
        hard_blocks.extend(gate for gate, active in manual_gates.items() if active)
        reasons.append("the work must remain manual until its authority or evidence boundary is resolved")
        if manual_gates["irreversible-action"]:
            changes.append("replace irreversible actions with a reversible review step")
        if manual_gates["broad-permission"]:
            changes.append("define least-privilege permissions")
        if manual_gates["unclear-state"]:
            if card["action_scope"] in READ_ONLY_ACTION_SCOPES:
                changes.append("set state scope to none for read-only work")
            else:
                changes.append("define bounded state and retention")
        if manual_gates["read-only-retained-state"]:
            changes.append("remove retained state from read-only work")
        if manual_gates["missing-stop-rule"]:
            changes.append("define an explicit stop rule and limits")
        if manual_gates["unclear-value"]:
            changes.append("demonstrate useful value with traceable evidence")
        if manual_gates["external-permission-mismatch"]:
            changes.append("bind external actions to least-privilege permission scope")
        if manual_gates["sensitive-permission-mismatch"]:
            changes.append("bind sensitive access to least-privilege permission scope")
    elif card["recurrence"] != "repeated-history":
        outcome = "manual_workflow"
        reasons.append("the available evidence does not yet establish recurring work")
        changes.append("collect multiple traceable occurrences before proposing a loop")
    elif card["value"] != "demonstrated":
        outcome = "normal_skill"
        reasons.append("recurring guidance may help, but loop value is not demonstrated")
        changes.append("use reusable guidance or demonstrate useful loop value")
    elif card["requested_autonomy"] != "supervised":
        outcome = "normal_skill"
        reasons.append("the requested autonomy is advisory rather than a supervised loop")
        changes.append("use reusable guidance or explicitly request supervised autonomy")
    elif card["stop_rule"] != "explicit":
        outcome = "normal_skill"
        reasons.append("a loop requires an explicit machine-checkable stop rule")
        changes.append("define an explicit stop rule")
    elif card["completion_check"] == "subjective" or card["boundary"] != "bounded":
        outcome = "normal_skill"
        reasons.append("recurring guidance is useful, but it is subjective or insufficiently bounded")
        changes.append("use reusable guidance or make the boundary and completion check objective")
    elif (
        card["action_scope"] == "read-only"
        and card["data_handling"] == "ordinary"
        and card["state_scope"] == "none"
        and card["completion_check"] in {"human-review", "deterministic"}
    ):
        outcome = "read_only_triage_loop"
        reasons.append("repeated bounded ordinary read-only work has reviewable completion evidence")
    elif (
        card["action_scope"] in {"local-reversible", "external-read-only", "external-reversible"}
        or card["data_handling"] == "host-managed-sensitive"
    ) and card["completion_check"] == "deterministic":
        outcome = "supervised_loop"
        reasons.append("repeated bounded reversible or sensitive work has deterministic completion evidence")
    else:
        outcome = "normal_skill"
        reasons.append("the work lacks deterministic evidence required for supervised action")
        changes.append("use reusable guidance or add a deterministic completion check")

    if outcome in {"read_only_triage_loop", "supervised_loop"}:
        approvals.append("human activation after independent dry-run evidence")
        changes.append("obtain independent dry-run evidence before claiming readiness")
    if card["action_scope"] in {"external-read-only", "external-reversible"}:
        approvals.append("human approval for each external action")
    if card["data_handling"] == "host-managed-sensitive":
        approvals.append("human approval for each credential-access capability")

    return {
        "schema_version": SCHEMA_VERSION,
        "outcome": outcome,
        "score": total,
        "score_max": SCORE_MAX,
        "hard_blocks": _unique(hard_blocks),
        "reasons": _unique(reasons),
        "required_changes": _unique(changes),
        "required_approvals": _unique(approvals),
        "activation_allowed": False,
    }


def _validate_expected(value: Any) -> None:
    if not isinstance(value, dict) or set(value) != RESULT_FIELDS:
        raise ReadinessError("replay expected output must contain the exact result schema")
    if value.get("schema_version") != SCHEMA_VERSION:
        raise ReadinessError("replay expected schema_version is invalid")
    if value.get("outcome") not in OUTCOMES:
        raise ReadinessError("replay expected outcome is invalid")
    for name in ("score", "score_max"):
        if isinstance(value.get(name), bool) or not isinstance(value.get(name), int):
            raise ReadinessError("replay expected scores must be integers")
    for name in ("hard_blocks", "reasons", "required_changes", "required_approvals"):
        items = value.get(name)
        if not isinstance(items, list) or any(not isinstance(item, str) for item in items):
            raise ReadinessError("replay expected list fields must be string arrays")
        if len(items) != len(set(items)):
            raise ReadinessError("replay expected list fields must not contain duplicates")
    if value.get("activation_allowed") is not False:
        raise ReadinessError("replay expected activation_allowed must be false")


def check_replay(source: str | Path) -> int:
    data = load_json(source)
    if not isinstance(data, list) or not 1 <= len(data) <= MAX_REPLAY_CASES:
        raise ReadinessError("replay file must contain a bounded non-empty JSON array")
    failures: list[str] = []
    seen: set[str] = set()
    for index, case in enumerate(data):
        if not isinstance(case, dict) or set(case) != {"id", "card", "expected"}:
            raise ReadinessError("replay case must contain exactly id, card, and expected")
        case_id = case["id"]
        if (
            not isinstance(case_id, str)
            or len(case_id) > 80
            or not CASE_ID.fullmatch(case_id)
            or case_id in seen
        ):
            raise ReadinessError("replay case IDs must be unique bounded lowercase identifiers")
        seen.add(case_id)
        _validate_expected(case["expected"])
        actual = score(case["card"])
        if actual != case["expected"]:
            failures.append(f"case {index + 1} output mismatch")
    if failures:
        for failure in failures:
            print(f"ERROR: {failure}", file=sys.stderr)
        return 1
    print(f"Loop-readiness replay passed ({len(data)} cases).")
    return 0


def _python_supported() -> bool:
    if sys.version_info < MIN_PYTHON:
        print("ERROR: Python 3.11 or newer is required", file=sys.stderr)
        return False
    return True


def main() -> int:
    if not _python_supported():
        return 2
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--card", help="JSON readiness card file, or - for bounded stdin")
    source.add_argument("--replay", help="JSON replay file, or - for bounded stdin")
    args = parser.parse_args()
    try:
        if args.replay is not None:
            return check_replay(args.replay)
        print(json.dumps(score(load_json(args.card)), indent=2, sort_keys=True))
        return 0
    except ReadinessError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    except (OSError, RecursionError, ValueError):
        print("ERROR: input could not be processed safely", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
