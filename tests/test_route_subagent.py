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


def bind_probe_packet(packet: dict[str, object]) -> dict[str, object]:
    return json.loads(json.dumps(packet))


def adapter_result(packet: dict[str, object]) -> dict[str, object]:
    return ROUTER.build_ownership_probe_adapter_result(packet)


def retained_probe_context(packet: dict[str, object]) -> dict[str, object]:
    return ROUTER.ownership_probe_parent_context(
        packet["registry_descriptor"],
        packet["required_artifact_classes"],
        packet["declaration_conflict"],
        packet["direct_user_objective_repository_identity"],
        packet["host_canonical_workspace_identity"],
        adapter_result(packet),
    )


class RouteSubagentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = ROUTER.load_json(REPLAY_PATH)
        cls.success_cases = [case for case in cls.cases if "card" in case and "expected" in case]
        cls.error_cases = [case for case in cls.cases if "card" in case and "expected_error" in case]
        cls.probe_packet = {
            "phase": "probe-ownership",
            "registry_descriptor": ROUTER.ownership_probe_descriptor(),
            "registry_descriptor_sha256": ROUTER.ownership_probe_descriptor_sha256(),
            "required_artifact_classes": ["ecs-task-definition-manifests"],
            "direct_user_objective_repository_identity": None,
            "host_canonical_workspace_identity": "/workspace/current",
            "declaration_conflict": False,
            "query_results": [
                {
                    "artifact_class": artifact_class,
                    "complete": True,
                    "truncated": False,
                    "symlink_encountered": False,
                    "symlinks_followed": False,
                    "matches": [],
                }
                for artifact_class in ROUTER.PROBE_ARTIFACT_REGISTRY
            ],
        }

    def test_replay_expectations_are_complete_and_exact(self) -> None:
        for case in self.cases:
            with self.subTest(case=case["id"]):
                if "expected" in case:
                    if "probe" in case:
                        packet = {
                            "phase": ROUTER.ownership_probe_descriptor()["phase"],
                            "registry_descriptor": ROUTER.ownership_probe_descriptor(),
                            "registry_descriptor_sha256": ROUTER.ownership_probe_descriptor_sha256(),
                            "host_canonical_workspace_identity": "/workspace/current",
                            **case["probe"],
                        }
                        self.assertEqual(set(case["expected"]), ROUTER.PROBE_OUTPUT_KEYS)
                        self.assertEqual(ROUTER.probe_ownership(packet), case["expected"])
                    else:
                        self.assertEqual(set(case["expected"]), ROUTER.expected_output_keys(case["card"]))
                        self.assertEqual(ROUTER.route(case["card"]), case["expected"])
                else:
                    with self.assertRaisesRegex(ROUTER.RoutingError, f"^{case['expected_error']}$"):
                        ROUTER.route(case["card"])

    def test_every_role_is_reachable(self) -> None:
        reached = {ROUTER.route(case["card"])["primary_role"] for case in self.success_cases}
        self.assertEqual(reached, set(ROUTER.ENABLED_ROLES))
        self.assertNotIn("awb_operator", reached)
        self.assertIn("awb_operator", ROUTER.ROLE_PROFILE)

    def test_routing_is_deterministic(self) -> None:
        card = self.cases[0]["card"]
        self.assertEqual(ROUTER.route(card), ROUTER.route(dict(reversed(list(card.items())))))

    def test_all_evidence_and_boundary_overlays_are_independent(self) -> None:
        by_id = {case["id"]: case["expected"] for case in self.success_cases}
        self.assertEqual(by_id["bounded-integration-regression"]["required_followups"], ["awb_test_engineer", "awb_verifier"])
        self.assertEqual(by_id["bounded-independent-review"]["required_followups"], ["awb_test_engineer", "awb_verifier", "awb_reviewer"])
        self.assertEqual(by_id["persistent-debugging-overlays"]["required_followups"], ["awb_test_engineer", "awb_verifier", "awb_reviewer"])
        self.assertEqual(by_id["all-contract-boundaries"]["required_followups"], ["awb_test_engineer", "awb_verifier", "awb_reviewer", "awb_security_reviewer"])
        self.assertEqual(by_id["shared-impact-sole-test-trigger"]["required_followups"], ["awb_test_engineer", "awb_verifier"])
        self.assertEqual(by_id["production-impact-sole-test-trigger"]["required_followups"], ["awb_test_engineer", "awb_verifier"])
        order = {role: index for index, role in enumerate(("awb_test_engineer", "awb_verifier", "awb_reviewer", "awb_security_reviewer"))}
        for case in self.success_cases:
            followups = case["expected"]["required_followups"]
            with self.subTest(order=case["id"]):
                self.assertEqual(followups, sorted(set(followups), key=order.__getitem__))

    def test_migration_is_always_critical_and_reviewed(self) -> None:
        expected = next(case["expected"] for case in self.cases if case["id"] == "migration-never-routine")
        self.assertEqual(expected["primary_role"], "awb_migration_worker")
        self.assertEqual(expected["task_class"], "critical")
        self.assertTrue(expected["must_not_downgrade"])
        self.assertEqual(expected["required_followups"], ["awb_test_engineer", "awb_verifier", "awb_reviewer"])

    def test_external_execution_cards_fail_with_stable_unavailable_adapter_error(self) -> None:
        self.assertEqual(
            {case["id"] for case in self.error_cases},
            {"authorized-external-operation", "independent-external-verification"},
        )
        for case in self.error_cases:
            with self.subTest(case=case["id"]), self.assertRaisesRegex(
                ROUTER.RoutingError, f"^{ROUTER.EXTERNAL_EXECUTION_UNAVAILABLE}$"
            ):
                ROUTER.route(case["card"])

    def test_successful_routes_never_expose_external_or_network_requirements(self) -> None:
        forbidden_capabilities = {"external-operation", "external-verification"}
        for case in self.success_cases:
            result = ROUTER.route(case["card"])
            with self.subTest(case=case["id"]):
                self.assertTrue(forbidden_capabilities.isdisjoint(result["required_capabilities"]))
                self.assertTrue(forbidden_capabilities.isdisjoint(result["deferred_capabilities"]))
                self.assertNotIn("network", result["required_tools"])
                self.assertNotIn("network", result["deferred_tools"])

    def test_unsettled_map_and_extract_always_plan_before_terminal_investigation(self) -> None:
        ids = {
            "map-local-unknown-plans",
            "extract-competing-hypotheses-plans",
            "map-uncertain-confidence-plans",
        }
        for case in (case for case in self.success_cases if case["id"] in ids):
            result = ROUTER.route(case["card"])
            with self.subTest(case=case["id"]):
                self.assertEqual(result["primary_role"], "awb_planner")
                self.assertTrue(result["reroute_after_planning"])

    def test_simple_read_only_diagnosis_uses_one_bounded_child(self) -> None:
        case = next(case for case in self.success_cases if case["id"] == "simple-read-only-diagnosis")
        result = ROUTER.route(case["card"])
        self.assertEqual(result["primary_role"], "awb_fast_investigator")
        self.assertEqual(result["execution_path"], "fast")
        self.assertEqual(result["required_followups"], [])
        self.assertEqual(result["required_skills"], [])
        self.assertFalse(result["reroute_after_planning"])
        self.assertEqual(
            result["lifecycle"],
            {
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
            },
        )

    def test_consequential_or_unsettled_diagnosis_does_not_use_fast_path(self) -> None:
        base = next(case["card"] for case in self.success_cases if case["id"] == "simple-read-only-diagnosis")
        consequential = ROUTER.route(dict(base, impact="shared system"))
        self.assertEqual(consequential["primary_role"], "awb_deep_investigator")
        self.assertEqual(consequential["execution_path"], "standard")
        self.assertNotIn("lifecycle", consequential)
        unsettled = ROUTER.route(dict(base, ambiguity="local unknown", router_confidence="uncertain"))
        self.assertEqual(unsettled["primary_role"], "awb_planner")
        self.assertTrue(unsettled["reroute_after_planning"])

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
        for shape in ("map", "extract", "diagnose", "plan", "test", "review", "verify-external"):
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
        with self.assertRaisesRegex(ROUTER.RoutingError, f"^{ROUTER.EXTERNAL_EXECUTION_UNAVAILABLE}$"):
            ROUTER.route(valid)

    def test_privileged_capabilities_and_network_cannot_self_grant(self) -> None:
        base = dict(self.cases[0]["card"])
        ordinary_shapes = ("map", "extract", "diagnose", "plan", "test", "review", "implement", "debug", "migrate")
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

    def test_healthpal_zero_match_is_terminal_without_planner_child_or_wait(self) -> None:
        packet = dict(
            self.probe_packet,
            direct_user_objective_repository_identity="healthpal-infrastructure",
            required_artifact_classes=[
                "ecs-task-definition-manifests",
                "deployment-pipeline-manifests",
                "infrastructure-as-code",
            ],
        )
        result = ROUTER.probe_ownership(packet)
        self.assertEqual(set(result), ROUTER.PROBE_OUTPUT_KEYS)
        self.assertEqual(result["primary_role"], "lead-owned-protected-mcp")
        self.assertEqual(result["outcome"], "known-artifact-mismatch")
        self.assertEqual(result["routing_action"], "stop-before-planner")
        self.assertEqual(result["expected_owner_identity"], "healthpal-infrastructure")
        self.assertEqual(result["planner_count"], 0)
        self.assertEqual(result["probe_child_count"], 0)
        self.assertEqual(result["wait_count"], 0)
        self.assertLess(result["virtual_elapsed_seconds_upper_bound"], 60)
        self.assertEqual(result["lifecycle"], ROUTER.PROBE_LIFECYCLE)

    def test_direct_adapter_match_reroutes_for_every_class(self) -> None:
        matches = {
            "ecs-task-definition-manifests": "deploy/api-task-definition.json",
            "deployment-pipeline-manifests": ".github/workflows/release.yml",
            "infrastructure-as-code": "infra/main.tf",
        }
        for artifact_class, path in matches.items():
            packet = json.loads(json.dumps(self.probe_packet))
            packet["required_artifact_classes"] = [artifact_class]
            packet["query_results"][list(ROUTER.PROBE_ARTIFACT_REGISTRY).index(artifact_class)]["matches"] = [path]
            with self.subTest(artifact_class=artifact_class):
                result = ROUTER.probe_ownership(packet)
                self.assertEqual(result["outcome"], "owner-artifact-present")
                self.assertEqual(result["matched_required_classes"], [artifact_class])
                self.assertEqual(result["probe_child_count"], 0)

    def test_retained_context_binds_user_workspace_requirements_conflict_and_adapter(self) -> None:
        context = retained_probe_context(self.probe_packet)
        digest = ROUTER.ownership_probe_parent_context_sha256(context)
        self.assertEqual(
            ROUTER.evaluate_ownership_probe_result(ROUTER.ownership_probe_descriptor(), context, digest),
            "known-artifact-mismatch",
        )
        mutations = []
        for field, value in (
            ("required_artifact_classes", ["infrastructure-as-code"]),
            ("declaration_conflict", True),
            ("direct_user_objective_repository_identity", "other-owner"),
            ("host_canonical_workspace_identity", "/workspace/other"),
        ):
            mutation = json.loads(json.dumps(context))
            mutation[field] = value
            mutations.append(mutation)
        for mutation in mutations:
            with self.subTest(field=mutation):
                self.assertEqual(
                    ROUTER.evaluate_ownership_probe_result(
                        ROUTER.ownership_probe_descriptor(), mutation, digest
                    ),
                    "inconclusive-delegate",
                )

    def test_adapter_tamper_replay_malformed_and_ambiguity_fail_closed(self) -> None:
        mutations = []
        for field, value in (
            ("complete", False),
            ("truncated", True),
            ("symlink_encountered", True),
            ("symlinks_followed", True),
        ):
            packet = json.loads(json.dumps(self.probe_packet))
            packet["query_results"][0][field] = value
            mutations.append(packet)
        malformed = json.loads(json.dumps(self.probe_packet))
        malformed["query_results"].pop()
        mutations.append(malformed)
        replay = json.loads(json.dumps(self.probe_packet))
        replay["host_canonical_workspace_identity"] = "/workspace/other"
        replay_adapter = adapter_result(replay)
        context = retained_probe_context(self.probe_packet)
        context["adapter_result"] = replay_adapter
        digest = ROUTER._canonical_sha256(context)
        self.assertEqual(
            ROUTER.evaluate_ownership_probe_result(ROUTER.ownership_probe_descriptor(), context, digest),
            "inconclusive-delegate",
        )
        for packet in mutations:
            with self.subTest(packet=packet):
                try:
                    result = ROUTER.probe_ownership(packet)
                except ROUTER.RoutingError:
                    continue
                self.assertEqual(result["outcome"], "inconclusive-delegate")

    def test_adapter_rejects_untrusted_paths_and_wrong_class_patterns(self) -> None:
        for unsafe in (
            "/deploy/api-task-definition.json",
            "../deploy/api-task-definition.json",
            "deploy//api-task-definition.json",
            "deploy\\api-task-definition.json",
            "deploy/not-a-task.txt",
        ):
            packet = json.loads(json.dumps(self.probe_packet))
            packet["query_results"][0]["matches"] = [unsafe]
            with self.subTest(path=unsafe), self.assertRaises(ROUTER.RoutingError):
                ROUTER.probe_ownership(packet)

    def test_capability_gate_requires_exact_protected_mcp_and_never_spawns(self) -> None:
        for harness in ("codex", "claude"):
            supported = ROUTER.ownership_probe_capability_gate(
                harness, True, ["awb_ownership.scan_required_artifacts"]
            )
            self.assertTrue(supported["probe_supported"])
            self.assertTrue(supported["direct_mcp_call"])
            self.assertFalse(supported["spawn_probe_child"])
            self.assertEqual(supported["max_waits"], 0)
        for observed in ([], ["Glob"], ["awb_ownership.scan_required_artifacts", "other"]):
            decision = ROUTER.ownership_probe_capability_gate("codex", bool(observed), observed)
            self.assertFalse(decision["probe_supported"])
            self.assertEqual(decision["routing_action"], "normal-full-flow")
            self.assertEqual(decision["max_waits"], 0)

    def test_ownership_probe_requires_every_fixed_result_once_in_order(self) -> None:
        missing = json.loads(json.dumps(self.probe_packet))
        missing["query_results"].pop()
        with self.assertRaisesRegex(ROUTER.RoutingError, "exactly three"):
            ROUTER.probe_ownership(missing)
        reordered = json.loads(json.dumps(self.probe_packet))
        reordered["query_results"].reverse()
        with self.assertRaisesRegex(ROUTER.RoutingError, "canonical order"):
            ROUTER.probe_ownership(reordered)

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

    def test_load_rejects_alias_parent_components_before_normalization(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original_parent = root / "original-parent"
            original_parent.mkdir()
            alternate_parent = root / "alternate-parent"
            alternate_parent.mkdir()
            (root / "card.json").write_text('{"source": "lexically-collapsed"}', encoding="utf-8")
            linked_parent = root / "linked-parent"
            linked_parent.symlink_to(original_parent, target_is_directory=True)

            absolute = linked_parent / ".." / "card.json"
            relative = Path(os.path.relpath(root, Path.cwd())) / "linked-parent" / ".." / "card.json"
            for path in (absolute, relative):
                with self.subTest(path=os.fspath(path)), self.assertRaisesRegex(ROUTER.RoutingError, "parent path components"):
                    ROUTER.load_json(path)

            linked_parent.unlink()
            linked_parent.symlink_to(alternate_parent, target_is_directory=True)
            with self.assertRaisesRegex(ROUTER.RoutingError, "parent path components"):
                ROUTER.load_json(absolute)
            (original_parent / "safe.json").write_text('{"source": "safe-alias"}', encoding="utf-8")
            linked_parent.unlink()
            linked_parent.symlink_to(original_parent, target_is_directory=True)
            self.assertEqual(ROUTER.load_json(linked_parent / "safe.json"), {"source": "safe-alias"})

    def test_load_fails_closed_when_secure_posix_features_are_missing_or_partial(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "card.json"
            path.write_text("{}", encoding="utf-8")
            for feature in ("O_DIRECTORY", "O_NOFOLLOW", "O_NONBLOCK"):
                with self.subTest(feature=feature), mock.patch.object(ROUTER.os, feature, None):
                    with self.assertRaisesRegex(ROUTER.RoutingError, "secure file reading is unsupported"):
                        ROUTER.load_json(path)
            with mock.patch.object(ROUTER.os, "supports_dir_fd", frozenset()):
                with self.assertRaisesRegex(ROUTER.RoutingError, "secure file reading is unsupported"):
                    ROUTER.load_json(path)

            real_open = os.open

            def unsupported_dir_fd(component: str, flags: int, *, dir_fd: int | None = None) -> int:
                if dir_fd is not None:
                    raise NotImplementedError("unsafe\n\x1b\x07details")
                return real_open(component, flags)

            with mock.patch.object(ROUTER.os, "open", side_effect=unsupported_dir_fd):
                with self.assertRaisesRegex(ROUTER.RoutingError, "secure file reading is unsupported") as raised:
                    ROUTER.load_json(path)
            self.assertNotIn("unsafe", str(raised.exception))

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
            error_case = json.loads(json.dumps(self.error_cases[0]))
            error_case["expected"] = {}
            path.write_text(json.dumps([error_case]), encoding="utf-8")
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
            probe_path = Path(directory) / "probe.json"
            probe_path.write_text(json.dumps(self.probe_packet), encoding="utf-8")
            probe = subprocess.run(
                [sys.executable, str(ROUTER_PATH), "--probe-ownership", str(probe_path)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(probe.returncode, 0, probe.stderr)
            self.assertEqual(json.loads(probe.stdout)["outcome"], "known-artifact-mismatch")
            descriptor = subprocess.run(
                [sys.executable, str(ROUTER_PATH), "--describe-ownership-probe"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(descriptor.returncode, 0, descriptor.stderr)
            self.assertEqual(json.loads(descriptor.stdout), ROUTER.ownership_probe_descriptor())


if __name__ == "__main__":
    unittest.main()
