from __future__ import annotations

import copy
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "skills/discover-loops/scripts/score_loop_readiness.py"
REPLAY_PATH = ROOT / "skills/discover-loops/tests/readiness-cases.json"
SPEC = importlib.util.spec_from_file_location("loop_readiness", SCRIPT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load score_loop_readiness.py")
SCORER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SCORER)


def strong_card() -> dict[str, str]:
    return {
        "recurrence": "repeated-history",
        "value": "demonstrated",
        "boundary": "bounded",
        "completion_check": "deterministic",
        "action_scope": "local-reversible",
        "permission_scope": "least-privilege",
        "state_scope": "bounded",
        "stop_rule": "explicit",
        "requested_autonomy": "supervised",
        "data_handling": "ordinary",
    }


def run_cli(*arguments: str, input_bytes: bytes | None = None, cwd: Path = ROOT) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *arguments],
        cwd=cwd,
        input=input_bytes,
        capture_output=True,
        check=False,
        timeout=5,
    )


class LoopReadinessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = SCORER.load_json(REPLAY_PATH)

    def test_replay_expectations_are_complete_exact_outputs(self) -> None:
        for case in self.cases:
            with self.subTest(case=case["id"]):
                self.assertEqual(set(case["expected"]), SCORER.RESULT_FIELDS)
                self.assertEqual(SCORER.score(case["card"]), case["expected"])
        self.assertEqual(SCORER.check_replay(REPLAY_PATH), 0)

    def test_every_outcome_is_reachable_and_activation_is_always_false(self) -> None:
        outcomes = set()
        for case in self.cases:
            result = SCORER.score(case["card"])
            outcomes.add(result["outcome"])
            self.assertIs(result["activation_allowed"], False)
            self.assertGreaterEqual(result["score"], 0)
            self.assertLessEqual(result["score"], result["score_max"])
        self.assertEqual(outcomes, SCORER.OUTCOMES)

    def test_key_order_does_not_change_result(self) -> None:
        card = strong_card()
        self.assertEqual(SCORER.score(card), SCORER.score(dict(reversed(list(card.items())))))

    def test_card_schema_is_exact_and_duplicate_keys_are_rejected(self) -> None:
        for mutation, message in (
            (lambda card: card.pop("stop_rule"), "missing fields"),
            (lambda card: card.update(confidence="high"), "unknown fields"),
            (lambda card: card.update(boundary=True), "boundary has an invalid value"),
        ):
            card = strong_card()
            mutation(card)
            with self.assertRaisesRegex(SCORER.ReadinessError, message):
                SCORER.score(card)
        with self.assertRaisesRegex(SCORER.ReadinessError, "duplicate JSON key"):
            SCORER.parse_json('{"recurrence":"none","recurrence":"repeated-history"}')

    def test_loop_outcomes_require_demonstrated_value_and_supervised_autonomy(self) -> None:
        for field, value in (
            ("value", "unclear"),
            ("value", "plausible"),
            ("requested_autonomy", "advisory"),
        ):
            card = strong_card()
            card[field] = value
            self.assertNotIn(SCORER.score(card)["outcome"], {"read_only_triage_loop", "supervised_loop"})

    def test_external_and_sensitive_work_require_least_privilege(self) -> None:
        for field, value in (
            ("action_scope", "external-read-only"),
            ("action_scope", "external-reversible"),
            ("data_handling", "host-managed-sensitive"),
        ):
            for permission in ("none", "broad"):
                card = strong_card()
                card[field] = value
                card["permission_scope"] = permission
                self.assertEqual(SCORER.score(card)["outcome"], "manual_workflow")

    def test_read_only_action_scopes_require_no_state_for_every_loop_outcome(self) -> None:
        for action_scope, data_handling in (
            ("read-only", "ordinary"),
            ("read-only", "host-managed-sensitive"),
            ("external-read-only", "ordinary"),
        ):
            for state_scope in ("bounded", "unclear"):
                with self.subTest(
                    action_scope=action_scope,
                    data_handling=data_handling,
                    state_scope=state_scope,
                ):
                    card = strong_card()
                    card.update(
                        action_scope=action_scope,
                        data_handling=data_handling,
                        state_scope=state_scope,
                    )
                    result = SCORER.score(card)
                    self.assertEqual(result["outcome"], "manual_workflow")
                    self.assertNotIn(
                        result["outcome"],
                        {"read_only_triage_loop", "supervised_loop"},
                    )
                    if state_scope == "bounded":
                        self.assertIn("read-only-retained-state", result["hard_blocks"])
                        self.assertIn(
                            "remove retained state from read-only work",
                            result["required_changes"],
                        )
                    else:
                        self.assertIn("unclear-state", result["hard_blocks"])
                        self.assertIn(
                            "set state scope to none for read-only work",
                            result["required_changes"],
                        )

        ordinary = strong_card()
        ordinary.update(action_scope="read-only", state_scope="none")
        self.assertEqual(SCORER.score(ordinary)["outcome"], "read_only_triage_loop")

        sensitive = strong_card()
        sensitive.update(
            action_scope="read-only",
            state_scope="none",
            data_handling="host-managed-sensitive",
        )
        self.assertEqual(SCORER.score(sensitive)["outcome"], "supervised_loop")

        insufficient_history = strong_card()
        insufficient_history["recurrence"] = "one-example"
        self.assertEqual(
            SCORER.score(insufficient_history)["outcome"], "manual_workflow"
        )

    def test_hard_rejects_precede_manual_gates(self) -> None:
        card = strong_card()
        card.update(requested_autonomy="automatic", action_scope="irreversible", permission_scope="broad")
        result = SCORER.score(card)
        self.assertEqual(result["outcome"], "reject")
        self.assertEqual(result["hard_blocks"], ["automatic-autonomy"])

    def test_conservative_single_field_monotonicity_and_score_bounds(self) -> None:
        base = strong_card()
        for field, choices in SCORER.FIELDS.items():
            for choice in choices:
                card = dict(base)
                card[field] = choice
                result = SCORER.score(card)
                self.assertGreaterEqual(result["score"], 0)
                self.assertLessEqual(result["score"], SCORER.SCORE_MAX)
                if field == "requested_autonomy" and choice != "supervised":
                    self.assertNotIn(result["outcome"], {"read_only_triage_loop", "supervised_loop"})
                if field == "value" and choice != "demonstrated":
                    self.assertNotIn(result["outcome"], {"read_only_triage_loop", "supervised_loop"})

    def test_replay_case_schema_ids_and_expected_output_are_closed(self) -> None:
        base = copy.deepcopy(self.cases[0])
        mutations = []
        extra = copy.deepcopy(base)
        extra["note"] = "no"
        mutations.append(extra)
        missing = copy.deepcopy(base)
        missing["expected"].pop("score")
        mutations.append(missing)
        unknown = copy.deepcopy(base)
        unknown["expected"]["confidence"] = "high"
        mutations.append(unknown)
        empty_expected = copy.deepcopy(base)
        empty_expected["expected"] = {}
        mutations.append(empty_expected)
        duplicate_ids = [copy.deepcopy(base), copy.deepcopy(base)]
        mutations.append(duplicate_ids)
        for index, mutation in enumerate(mutations):
            data = mutation if isinstance(mutation, list) else [mutation]
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / f"bad-{index}.json"
                path.write_text(json.dumps(data), encoding="utf-8")
                with self.assertRaises(SCORER.ReadinessError):
                    SCORER.check_replay(path)

    def test_replay_duplicate_json_keys_are_rejected(self) -> None:
        payload = b'[{"id":"one","id":"two","card":{},"expected":{}}]'
        result = run_cli("--replay", "-", input_bytes=payload)
        self.assertEqual(result.returncode, 2)
        self.assertIn(b"duplicate JSON key", result.stderr)

    def test_cli_supports_bounded_stdin_and_unrelated_cwd(self) -> None:
        payload = json.dumps(strong_card()).encode()
        with tempfile.TemporaryDirectory() as directory:
            result = run_cli("--card", "-", input_bytes=payload, cwd=Path(directory))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(json.loads(result.stdout)["activation_allowed"])

    def test_cli_rejects_invalid_bytes_deep_json_huge_int_and_oversize_without_traceback(self) -> None:
        payloads = (
            b"\xff\xfe",
            b"[" * 2000,
            b'{"n":' + b"9" * 5000 + b"}",
            b" " * (SCORER.MAX_INPUT_BYTES + 1),
        )
        for payload in payloads:
            with self.subTest(size=len(payload)):
                result = run_cli("--card", "-", input_bytes=payload)
                self.assertEqual(result.returncode, 2)
                self.assertIn(b"ERROR:", result.stderr)
                self.assertNotIn(b"Traceback", result.stderr)

    def test_cli_rejects_symlink_and_fifo_without_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "card.json"
            target.write_text(json.dumps(strong_card()), encoding="utf-8")
            symlink = root / "card-link.json"
            symlink.symlink_to(target)
            result = run_cli("--card", str(symlink))
            self.assertEqual(result.returncode, 2)
            self.assertIn(b"must not be a symlink", result.stderr)
            if hasattr(os, "mkfifo"):
                fifo = root / "card.fifo"
                os.mkfifo(fifo)
                result = run_cli("--card", str(fifo))
                self.assertEqual(result.returncode, 2)
                self.assertIn(b"regular file", result.stderr)

    def test_cli_diagnostics_do_not_emit_ansi_or_raw_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            raw_name = "secret-\x1b[31m.json"
            path = Path(directory) / raw_name
            result = run_cli("--card", str(path))
            self.assertEqual(result.returncode, 2)
            self.assertNotIn(b"\x1b", result.stderr)
            self.assertNotIn(raw_name.encode(), result.stderr)
            self.assertNotIn(str(path).encode(), result.stderr)


if __name__ == "__main__":
    unittest.main()
