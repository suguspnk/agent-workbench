from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROUTER_PATH = ROOT / "skills/orchestrate-task/scripts/route_subagent.py"
REPLAY_PATH = ROOT / "skills/orchestrate-task/tests/routing-cases.json"
SPEC = importlib.util.spec_from_file_location("agent_workbench_router", ROUTER_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load route_subagent.py")
ROUTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ROUTER)


class RouteSubagentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = ROUTER.load_json(REPLAY_PATH)

    def test_replay_expectations_are_complete_and_exact(self) -> None:
        for case in self.cases:
            with self.subTest(case=case["id"]):
                self.assertEqual(set(case["expected"]), ROUTER.OUTPUT_KEYS)
                self.assertEqual(ROUTER.route(case["card"]), case["expected"])

    def test_every_role_is_reachable(self) -> None:
        reached = {ROUTER.route(case["card"])["primary_role"] for case in self.cases}
        self.assertEqual(reached, set(ROUTER.ROLE_PROFILE))

    def test_routing_is_deterministic(self) -> None:
        card = self.cases[0]["card"]
        self.assertEqual(ROUTER.route(card), ROUTER.route(dict(reversed(list(card.items())))))

    def test_all_evidence_and_boundary_overlays_are_independent(self) -> None:
        by_id = {case["id"]: case["expected"] for case in self.cases}
        self.assertEqual(by_id["bounded-integration-regression"]["required_followups"], ["awb_verifier", "awb_test_engineer"])
        self.assertEqual(by_id["bounded-independent-review"]["required_followups"], ["awb_verifier", "awb_test_engineer", "awb_reviewer"])
        self.assertEqual(by_id["persistent-debugging-overlays"]["required_followups"], ["awb_verifier", "awb_test_engineer", "awb_reviewer"])
        self.assertEqual(by_id["all-contract-boundaries"]["required_followups"], ["awb_verifier", "awb_test_engineer", "awb_reviewer", "awb_security_reviewer"])
        self.assertEqual(by_id["shared-impact-sole-test-trigger"]["required_followups"], ["awb_verifier", "awb_test_engineer"])
        self.assertEqual(by_id["production-impact-sole-test-trigger"]["required_followups"], ["awb_verifier", "awb_test_engineer"])

    def test_migration_is_always_critical_and_reviewed(self) -> None:
        expected = next(case["expected"] for case in self.cases if case["id"] == "migration-never-routine")
        self.assertEqual(expected["primary_role"], "awb_migration_worker")
        self.assertEqual(expected["task_class"], "critical")
        self.assertTrue(expected["must_not_downgrade"])
        self.assertEqual(expected["required_followups"], ["awb_verifier", "awb_test_engineer", "awb_reviewer"])

    def test_operator_to_external_verifier_to_security_review_flow(self) -> None:
        by_id = {case["id"]: case["expected"] for case in self.cases}
        self.assertEqual(by_id["authorized-external-operation"]["required_followups"], ["awb_verifier", "awb_security_reviewer"])
        verification = by_id["independent-external-verification"]
        self.assertEqual(verification["primary_role"], "awb_verifier")
        self.assertEqual(verification["required_followups"], ["awb_security_reviewer"])
        self.assertIn("external-verification", verification["required_capabilities"])
        operation = by_id["authorized-external-operation"]
        self.assertEqual(operation["authorization_binding"], verification["authorization_binding"])
        self.assertEqual(operation["authorization_reference"], verification["authorization_reference"])

    def test_unresolved_implementation_defers_mutation_requirements_to_planner(self) -> None:
        case = next(case for case in self.cases if case["id"] == "unresolved-implementation-needs-plan")
        result = ROUTER.route(case["card"])
        self.assertEqual(result["primary_role"], "awb_planner")
        self.assertTrue(result["reroute_after_planning"])
        self.assertEqual(result["required_capabilities"], [])
        self.assertEqual(result["required_tools"], [])
        self.assertEqual(result["current_change_authority"], "none")
        self.assertEqual(result["deferred_capabilities"], ["write", "test"])
        self.assertEqual(result["deferred_tools"], ["file-write", "shell"])
        self.assertEqual(result["deferred_change_authority"], "shared contract")
        self.assertIn("implementation-quality-governance", result["deferred_skills"])

    def test_planner_current_step_cannot_request_mutation(self) -> None:
        card = next(case["card"] for case in self.cases if case["id"] == "unresolved-implementation-needs-plan")
        for field, value in (("planning_capabilities", ["write"]), ("planning_tools", ["file-write"])):
            with self.subTest(field=field), self.assertRaises(ROUTER.RoutingError):
                ROUTER.route(dict(card, **{field: value}))
        for field, value in (("deferred_capabilities", ["external-operation"]), ("deferred_tools", ["network"])):
            with self.subTest(field=field), self.assertRaisesRegex(ROUTER.RoutingError, "cannot be deferred"):
                ROUTER.route(dict(card, **{field: value}))

    def test_missing_unknown_and_invalid_fields_are_rejected(self) -> None:
        card = dict(self.cases[0]["card"])
        card.pop("impact")
        with self.assertRaisesRegex(ROUTER.RoutingError, "missing routing fields: impact"):
            ROUTER.route(card)
        with self.assertRaisesRegex(ROUTER.RoutingError, 'unknown routing fields: "urgency"'):
            ROUTER.route(dict(self.cases[0]["card"], urgency="high"))
        with self.assertRaisesRegex(ROUTER.RoutingError, "impact must be one of"):
            ROUTER.route(dict(self.cases[0]["card"], impact="urgent"))

    def test_duplicate_json_keys_and_list_items_are_rejected(self) -> None:
        with self.assertRaisesRegex(ROUTER.RoutingError, 'duplicate JSON key: "impact"'):
            ROUTER.parse_json('{"impact": "reversible", "impact": "user-visible"}')
        card = dict(self.cases[0]["card"], contract_boundaries=["public API", "public API"])
        with self.assertRaisesRegex(ROUTER.RoutingError, "duplicate item"):
            ROUTER.route(card)

    def test_external_authority_fails_closed_without_exact_packet(self) -> None:
        valid = next(case["card"] for case in self.cases if case["id"] == "authorized-external-operation")
        card = dict(valid)
        card.pop("operation_authorization")
        with self.assertRaisesRegex(ROUTER.RoutingError, "requires operation_authorization"):
            ROUTER.route(card)
        card["operation_authorization"] = {"action": "delete", "target": "x"}
        with self.assertRaisesRegex(ROUTER.RoutingError, "missing operation authorization fields"):
            ROUTER.route(card)
        for field in valid["operation_authorization"]:
            authorization = dict(valid["operation_authorization"])
            authorization.pop(field)
            with self.subTest(missing=field), self.assertRaisesRegex(ROUTER.RoutingError, "missing operation authorization fields"):
                ROUTER.route(dict(valid, operation_authorization=authorization))
        for field in ("action", "target"):
            authorization = dict(valid["operation_authorization"], **{field: "bad\nvalue"})
            with self.subTest(control=field), self.assertRaisesRegex(ROUTER.RoutingError, "trimmed non-control"):
                ROUTER.route(dict(valid, operation_authorization=authorization))

    def test_authority_matrix_rejects_cross_field_contradictions(self) -> None:
        base = dict(self.cases[0]["card"])
        for shape in ("implement", "debug", "migrate"):
            for authority in ("none", "owned-path deletion", "external/destructive"):
                with self.subTest(shape=shape, authority=authority), self.assertRaises(ROUTER.RoutingError):
                    ROUTER.route(dict(base, work_shape=shape, change_authority=authority))
        for shape in ("map", "extract", "plan", "test", "review", "verify-external"):
            for authority in ("owned local paths", "owned-path deletion", "shared contract", "external/destructive"):
                with self.subTest(shape=shape, authority=authority), self.assertRaises(ROUTER.RoutingError):
                    ROUTER.route(dict(base, work_shape=shape, change_authority=authority))
        for authority in ("none", "owned local paths", "owned-path deletion", "shared contract"):
            with self.subTest(shape="operate", authority=authority), self.assertRaises(ROUTER.RoutingError):
                ROUTER.route(dict(base, work_shape="operate", change_authority=authority))

    def test_operator_intrinsic_requirements_and_contradictions(self) -> None:
        valid = next(case["card"] for case in self.cases if case["id"] == "authorized-external-operation")
        mutations = (
            {"required_capabilities": []},
            {"required_tools": ["shell"]},
            {"required_tools": ["network"]},
            {"tool_loop": "one read/check"},
            {"contract": "internal", "contract_boundaries": []},
            {"ambiguity": "local unknown"},
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation), self.assertRaises(ROUTER.RoutingError):
                ROUTER.route(dict(valid, **mutation))
        for field in ("packet_id", "revision", "action", "target"):
            authorization = dict(valid["operation_authorization"])
            authorization[field] = authorization[field] + "-changed"
            with self.subTest(binding_field=field), self.assertRaisesRegex(ROUTER.RoutingError, "binding does not match"):
                ROUTER.route(dict(valid, operation_authorization=authorization))

    def test_external_verification_is_separate_exact_read_only_authority(self) -> None:
        valid = next(case["card"] for case in self.cases if case["id"] == "independent-external-verification")
        for mutation in (
            {"external_verification": None},
            {"required_capabilities": []},
            {"required_tools": ["shell"]},
            {"change_authority": "external/destructive"},
            {"contract": "internal", "contract_boundaries": []},
        ):
            with self.subTest(mutation=mutation), self.assertRaises(ROUTER.RoutingError):
                ROUTER.route(dict(valid, **mutation))
        for field in ("operator_packet_id", "operator_revision", "action", "target"):
            verification = dict(valid["external_verification"])
            verification[field] = verification[field] + "-changed"
            with self.subTest(binding_field=field), self.assertRaisesRegex(ROUTER.RoutingError, "binding does not match"):
                ROUTER.route(dict(valid, external_verification=verification))

    def test_external_verification_requires_settled_high_confidence(self) -> None:
        valid = next(case["card"] for case in self.cases if case["id"] == "independent-external-verification")
        ambiguities = ("settled", "local unknown", "competing hypotheses", "open-ended")
        confidences = ("high", "uncertain", "unresolved")
        for ambiguity in ambiguities:
            for confidence in confidences:
                if (ambiguity, confidence) == ("settled", "high"):
                    continue
                with self.subTest(ambiguity=ambiguity, confidence=confidence), self.assertRaisesRegex(ROUTER.RoutingError, "requires settled ambiguity and high router confidence"):
                    ROUTER.route(dict(valid, ambiguity=ambiguity, router_confidence=confidence))
        self.assertEqual(ROUTER.route(valid), next(case["expected"] for case in self.cases if case["id"] == "independent-external-verification"))

    def test_privileged_capabilities_and_network_cannot_self_grant(self) -> None:
        base = dict(self.cases[0]["card"])
        ordinary_shapes = ("map", "extract", "plan", "test", "review", "implement", "debug", "migrate")
        for shape in ordinary_shapes:
            authority = "owned local paths" if shape in {"implement", "debug", "migrate"} else "none"
            card = dict(base, work_shape=shape, change_authority=authority)
            with self.subTest(shape=shape, bypass="external-verification"), self.assertRaisesRegex(ROUTER.RoutingError, "only valid for work_shape=verify-external"):
                ROUTER.route(dict(card, required_capabilities=["external-verification"]))
            with self.subTest(shape=shape, bypass="external-operation"), self.assertRaisesRegex(ROUTER.RoutingError, "only valid for work_shape=operate"):
                ROUTER.route(dict(card, required_capabilities=["external-operation"]))
            with self.subTest(shape=shape, bypass="network"), self.assertRaisesRegex(ROUTER.RoutingError, "network tool is only valid"):
                ROUTER.route(dict(card, required_tools=["network", "shell"]))
        operator = next(case["card"] for case in self.cases if case["id"] == "authorized-external-operation")
        with self.assertRaisesRegex(ROUTER.RoutingError, "only valid for work_shape=verify-external"):
            ROUTER.route(dict(operator, required_capabilities=["external-operation", "external-verification"]))
        verification = next(case["card"] for case in self.cases if case["id"] == "independent-external-verification")
        with self.assertRaisesRegex(ROUTER.RoutingError, "only valid for work_shape=operate"):
            ROUTER.route(dict(verification, required_capabilities=["external-verification", "external-operation"]))

    def test_ordinary_local_shell_verification_remains_allowed(self) -> None:
        card = next(case["card"] for case in self.cases if case["id"] == "ordinary-local-shell-verification")
        result = ROUTER.route(card)
        self.assertEqual(result["primary_role"], "awb_verifier")
        self.assertEqual(result["required_tools"], ["shell"])

    def test_optional_names_reject_whitespace_and_controls(self) -> None:
        for field, value in (
            ("required_skills", [" "]),
            ("required_skills", ["skill\nname"]),
            ("required_capabilities", [" read"]),
            ("required_modalities", ["code\t"]),
            ("required_tools", ["shell\x7f"]),
        ):
            with self.subTest(field=field, value=value), self.assertRaisesRegex(ROUTER.RoutingError, "trimmed, non-control"):
                ROUTER.route(dict(self.cases[0]["card"], **{field: value}))

    def test_authorization_strings_reject_unicode_controls_formats_and_surrogates(self) -> None:
        operator = next(case["card"] for case in self.cases if case["id"] == "authorized-external-operation")
        verifier = next(case["card"] for case in self.cases if case["id"] == "independent-external-verification")
        for unsafe in ("x\u202ey", "x\u200by", "x\ud800y", "x\u0085y"):
            authorization = dict(operator["operation_authorization"], action=unsafe)
            with self.subTest(kind="operator", unsafe=ascii(unsafe)), self.assertRaisesRegex(ROUTER.RoutingError, "non-control"):
                ROUTER.route(dict(operator, operation_authorization=authorization))
            verification = dict(verifier["external_verification"], scope=unsafe)
            with self.subTest(kind="verifier", unsafe=ascii(unsafe)), self.assertRaisesRegex(ROUTER.RoutingError, "non-control"):
                ROUTER.route(dict(verifier, external_verification=verification))
            with self.subTest(kind="list", unsafe=ascii(unsafe)), self.assertRaisesRegex(ROUTER.RoutingError, "trimmed, non-control"):
                ROUTER.route(dict(self.cases[0]["card"], required_skills=[unsafe]))

    def test_unmet_role_capability_fails_closed(self) -> None:
        card = dict(self.cases[0]["card"], required_tools=["browser"])
        with self.assertRaisesRegex(ROUTER.RoutingError, "lacks required_tools: browser"):
            ROUTER.route(card)

    def test_load_rejects_oversize_symlink_special_and_deep_nesting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            oversize = root / "oversize.json"
            oversize.write_bytes(b" " * (ROUTER.MAX_INPUT_BYTES + 1))
            with self.assertRaisesRegex(ROUTER.RoutingError, "input exceeds"):
                ROUTER.load_json(oversize)

            target = root / "target.json"
            target.write_text("{}", encoding="utf-8")
            link = root / "link.json"
            link.symlink_to(target)
            with self.assertRaisesRegex(ROUTER.RoutingError, "symlink"):
                ROUTER.load_json(link)

            real_parent = root / "real-parent"
            real_parent.mkdir()
            nested = real_parent / "nested.json"
            nested.write_text("{}", encoding="utf-8")
            linked_parent = root / "linked-parent"
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            self.assertEqual(ROUTER.load_json(linked_parent / "nested.json"), {})

            fifo = root / "input.fifo"
            os.mkfifo(fifo)
            with self.assertRaisesRegex(ROUTER.RoutingError, "regular file"):
                ROUTER.load_json(fifo)

            deep = root / "deep.json"
            deep.write_text("[" * 2000 + "]" * 2000, encoding="utf-8")
            with self.assertRaisesRegex(ROUTER.RoutingError, "nesting exceeds"):
                ROUTER.load_json(deep)

            nodes = root / "nodes.json"
            nodes.write_text(json.dumps([0] * ROUTER.MAX_JSON_NODES), encoding="utf-8")
            with self.assertRaisesRegex(ROUTER.RoutingError, "more than"):
                ROUTER.load_json(nodes)

    def test_load_pins_followed_ancestor_and_rejects_final_symlink_swap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original_parent = root / "original-parent"
            original_parent.mkdir()
            (original_parent / "card.json").write_text('{"source": "original"}', encoding="utf-8")
            alternate_parent = root / "alternate-parent"
            alternate_parent.mkdir()
            (alternate_parent / "card.json").write_text('{"source": "alternate"}', encoding="utf-8")
            linked_parent = root / "linked-parent"
            linked_parent.symlink_to(original_parent, target_is_directory=True)

            real_open = os.open
            ancestor_swapped = False

            def swap_ancestor_after_open(path: str, flags: int, *, dir_fd: int | None = None) -> int:
                nonlocal ancestor_swapped
                descriptor = real_open(path, flags, dir_fd=dir_fd)
                if path == linked_parent.name and not ancestor_swapped:
                    linked_parent.unlink()
                    linked_parent.symlink_to(alternate_parent, target_is_directory=True)
                    ancestor_swapped = True
                return descriptor

            with mock.patch.object(ROUTER.os, "open", side_effect=swap_ancestor_after_open):
                self.assertEqual(ROUTER.load_json(linked_parent / "card.json"), {"source": "original"})
            self.assertTrue(ancestor_swapped)

            target = root / "target.json"
            target.write_text("{}", encoding="utf-8")
            final_path = root / "final.json"
            final_path.write_text("{}", encoding="utf-8")
            final_swapped = False

            def swap_final_before_open(path: str, flags: int, *, dir_fd: int | None = None) -> int:
                nonlocal final_swapped
                if path == final_path.name and not final_swapped:
                    final_path.unlink()
                    final_path.symlink_to(target)
                    final_swapped = True
                return real_open(path, flags, dir_fd=dir_fd)

            with mock.patch.object(ROUTER.os, "open", side_effect=swap_final_before_open):
                with self.assertRaisesRegex(ROUTER.RoutingError, "symlink"):
                    ROUTER.load_json(final_path)
            self.assertTrue(final_swapped)

    def test_json_nesting_ignores_brackets_inside_strings(self) -> None:
        value = "[" * (ROUTER.MAX_JSON_DEPTH + 10)
        self.assertEqual(ROUTER.parse_json(json.dumps(value)), value)

    def test_replay_rejects_duplicate_ids_and_inexact_expected_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "replay.json"
            case = self.cases[0]
            path.write_text(json.dumps([case, case]), encoding="utf-8")
            self.assertEqual(ROUTER.check_replay(path), 1)
            bad = json.loads(json.dumps(case))
            bad["expected"].pop("effort")
            bad["expected"]["unsupported"] = True
            path.write_text(json.dumps([bad]), encoding="utf-8")
            self.assertEqual(ROUTER.check_replay(path), 1)

    def test_replay_diagnostics_escape_untrusted_ids_and_keys(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "replay.json"
            malicious = "bad\n\x1b]8;;https://example.invalid\x07\x85\u202e"
            case = json.loads(json.dumps(self.cases[0]))
            case["id"] = malicious
            path.write_text(json.dumps([case]), encoding="utf-8")
            result = subprocess.run([sys.executable, str(ROUTER_PATH), "--replay", str(path)], cwd=ROOT, capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 1)
            self.assertNotIn("\x1b", result.stderr)
            self.assertNotIn("\x85", result.stderr)
            self.assertNotIn("\u202e", result.stderr)
            self.assertIn("\\u001b", result.stderr)
            self.assertIn("\\u0085", result.stderr)
            with self.assertRaisesRegex(ROUTER.RoutingError, r'unknown routing fields: "bad\\nkey"'):
                ROUTER.route(dict(self.cases[0]["card"], **{"bad\nkey": "value"}))

    def test_cli_exit_codes(self) -> None:
        good = subprocess.run([sys.executable, str(ROUTER_PATH), "--replay", str(REPLAY_PATH)], cwd=ROOT, capture_output=True, text=True, check=False)
        self.assertEqual(good.returncode, 0, good.stderr)
        with tempfile.TemporaryDirectory() as directory:
            bad_path = Path(directory) / "bad.json"
            bad_path.write_text("{", encoding="utf-8")
            bad = subprocess.run([sys.executable, str(ROUTER_PATH), "--card", str(bad_path)], cwd=ROOT, capture_output=True, text=True, check=False)
            self.assertEqual(bad.returncode, 2)
            self.assertTrue(bad.stderr.startswith("ERROR:"))


if __name__ == "__main__":
    unittest.main()
