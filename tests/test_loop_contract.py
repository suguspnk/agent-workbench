from __future__ import annotations

import copy
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "skills/discover-loops/scripts/validate_loop_contract.py"
READINESS_REPLAY_PATH = ROOT / "skills/discover-loops/tests/readiness-cases.json"
SPEC = importlib.util.spec_from_file_location("loop_contract", SCRIPT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load validate_loop_contract.py")
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)
VERIFY_PATH = ROOT / "scripts/verify_repository.py"
VERIFY_SPEC = importlib.util.spec_from_file_location("verify_repository_for_test", VERIFY_PATH)
if VERIFY_SPEC is None or VERIFY_SPEC.loader is None:
    raise RuntimeError("could not load verify_repository.py")
REPOSITORY_VERIFY = importlib.util.module_from_spec(VERIFY_SPEC)
VERIFY_SPEC.loader.exec_module(REPOSITORY_VERIFY)


def capability(identity: str, operation_id: str, display_name: str | None = None) -> dict[str, str]:
    return {
        "id": identity,
        "operation_id": operation_id,
        "display_name": display_name or identity.replace("-", " ").title(),
        "binding_status": "unbound",
    }


REPRESENTATIVE_LOOP_SCOPES = {
    "read-only-ci-triage": {
        "allowed_paths": [],
        "allowed_tools": [capability("fixture-observer", "workspace.observe")],
        "allowed_actions": [],
        "state": {"kind": "none", "location": "", "retention": {"mode": "none"}},
    },
    "bounded-local-cleanup": {
        "allowed_paths": [
            "reports/loop-output/local-report-loop-v1/report.json"
        ],
        "allowed_tools": [capability("report-writer", "workspace.write")],
        "allowed_actions": [],
        "state": {"kind": "none", "location": "", "retention": {"mode": "none"}},
    },
    "external-read-only-draft": {
        "allowed_paths": [],
        "allowed_tools": [capability("external-observer", "external.read")],
        "allowed_actions": [],
        "state": {"kind": "none", "location": "", "retention": {"mode": "none"}},
    },
}


def base_contract() -> dict:
    card = {
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
    digest = hashlib.sha256(
        json.dumps(card, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "artifact_type": "loop-contract-proposal",
        "schema_version": "1.0",
        "proposal_id": "local-report-loop-v1",
        "objective": "Create a bounded local report from repeated fixture inputs.",
        "evidence_refs": ["source:local-report-readiness-v1", "workspace:fixtures/run-history.json"],
        "readiness": {
            "outcome": "supervised_loop",
            "card": card,
            "card_ref": "source:local-report-readiness-v1",
            "card_sha256": digest,
            "permission_scope": "least-privilege",
            "requested_autonomy": "supervised",
            "data_handling": "ordinary",
        },
        "semantic_review": {"required": True, "status": "pending"},
        "trigger": {"type": "manual", "description": "A human proposes a run."},
        "inputs": ["authorized fixture inputs"],
        "scope": {
            "allowed_paths": [
                "reports/loop-output/local-report-loop-v1/report.json",
                "reports/loop-output/local-report-loop-v1/state.json",
            ],
            "allowed_tools": [
                capability("fixture-observer", "workspace.observe"),
                capability("report-writer", "workspace.write"),
            ],
            "allowed_actions": [
                capability("write-report", "workspace.write")
            ],
            "prohibited_actions": ["activate", "schedule", "install", "publish", "message", "merge", "deploy"],
        },
        "state": {
            "kind": "workspace-file",
            "location": "reports/loop-output/local-report-loop-v1/state.json",
            "retention": {"mode": "bounded", "max_records": 30, "max_age_days": 30},
        },
        "acceptance": {
            "checks": ["Every fixture produces exactly one report row."],
            "verifier": {"required": True, "status": "pending"},
        },
        "dry_run": {
            "cases": [{"id": "fixture-one", "description": "A representative historical fixture.", "expected_evidence": "One correct report row and no prohibited action."}],
            "pass_condition": "All cases satisfy every acceptance check.",
            "result": "pending",
            "evidence_refs": [],
        },
        "limits": {"max_iterations": 5, "max_retries": 1, "max_elapsed_minutes": 10},
        "terminal_states": ["complete", "blocked", "needs-approval", "failed"],
        "approvals": [
            {"action": "activate", "required": True, "approver": "human"},
            {"action": "fixture-observer", "required": True, "approver": "human"},
            {"action": "report-writer", "required": True, "approver": "human"},
            {"action": "write-report", "required": True, "approver": "human"},
        ],
        "rollback": "Discard the local report artifacts.",
        "metrics": ["correct report rows", "elapsed minutes"],
        "lifecycle": {"proposal_status": "draft", "activation_status": "pending", "scheduler_status": "inactive"},
}


def bind_card(contract: dict, **changes: str) -> None:
    card = contract["readiness"]["card"]
    card.update(changes)
    result = VALIDATOR.READINESS_SCORER.score(card)
    contract["readiness"]["outcome"] = result["outcome"]
    for name in ("permission_scope", "requested_autonomy", "data_handling"):
        contract["readiness"][name] = card[name]
    canonical = json.dumps(card, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    contract["readiness"]["card_sha256"] = hashlib.sha256(canonical).hexdigest()


def read_only_contract() -> dict:
    contract = base_contract()
    bind_card(contract, action_scope="read-only", permission_scope="none", state_scope="none")
    contract["scope"]["allowed_paths"] = []
    contract["scope"]["allowed_tools"] = [
        capability("fixture-observer", "workspace.observe")
    ]
    contract["scope"]["allowed_actions"] = []
    contract["approvals"] = [
        {"action": "activate", "required": True, "approver": "human"},
        {"action": "fixture-observer", "required": True, "approver": "human"},
    ]
    contract["state"] = {"kind": "none", "location": "", "retention": {"mode": "none"}}
    return contract


def run_cli(*arguments: str, input_bytes: bytes | None = None, cwd: Path = ROOT) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *arguments], cwd=cwd, input=input_bytes,
        capture_output=True, check=False, timeout=5,
    )


class LoopContractTests(unittest.TestCase):
    def assert_rejected(self, contract: dict, message: str | None = None) -> None:
        if message:
            with self.assertRaisesRegex(VALIDATOR.ContractError, message):
                VALIDATOR.validate_contract(contract)
        else:
            with self.assertRaises(VALIDATOR.ContractError):
                VALIDATOR.validate_contract(contract)

    def test_valid_supervised_and_read_only_pending_proposals(self) -> None:
        for contract in (base_contract(), read_only_contract()):
            self.assertIs(VALIDATOR.validate_contract(contract), contract)

    def test_root_and_nested_schemas_are_closed_and_duplicates_rejected(self) -> None:
        missing = base_contract(); missing.pop("limits")
        self.assert_rejected(missing, "contract has missing fields")
        unknown = base_contract(); unknown["enabled"] = False
        self.assert_rejected(unknown, "contract has unknown fields")
        nested = base_contract(); nested["readiness"]["verified"] = True
        self.assert_rejected(nested, "readiness has unknown fields")
        with self.assertRaisesRegex(VALIDATOR.ContractError, "duplicate JSON key"):
            VALIDATOR.parse_json('{"objective":"one","objective":"two"}')

    def test_repository_manifest_loader_rejects_duplicate_json_keys(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary_root = Path(directory)
            manifest = temporary_root / "manifest.json"
            manifest.write_text('{"name":"one","name":"two"}', encoding="utf-8")
            original_root = REPOSITORY_VERIFY.ROOT
            REPOSITORY_VERIFY.ROOT = temporary_root
            try:
                with contextlib.redirect_stderr(io.StringIO()) as diagnostics:
                    with self.assertRaises(SystemExit):
                        REPOSITORY_VERIFY.load_json(manifest)
                self.assertIn("duplicate JSON key", diagnostics.getvalue())
            finally:
                REPOSITORY_VERIFY.ROOT = original_root

    def test_artifact_and_readiness_card_binding_are_mandatory(self) -> None:
        mutations = (
            ("artifact", lambda c: c.update(artifact_type="loop-contract"), "artifact_type"),
            ("outcome", lambda c: c["readiness"].update(outcome="normal_skill"), "does not permit"),
            ("ref", lambda c: c["readiness"].update(card_ref="source:other"), "appear exactly"),
            ("digest-upper", lambda c: c["readiness"].update(card_sha256="A" * 64), "lowercase SHA-256"),
            ("digest-short", lambda c: c["readiness"].update(card_sha256="a" * 63), "lowercase SHA-256"),
            ("autonomy", lambda c: c["readiness"].update(requested_autonomy="advisory"), "declarations do not match"),
            ("broad", lambda c: c["readiness"].update(permission_scope="broad"), "declarations do not match"),
            ("secret", lambda c: c["readiness"].update(data_handling="embedded-secret"), "declarations do not match"),
        )
        for name, mutate, message in mutations:
            with self.subTest(name=name):
                contract = base_contract(); mutate(contract)
                self.assert_rejected(contract, message)

    def test_embedded_card_digest_and_scorer_outcome_are_recomputed(self) -> None:
        contract = base_contract()
        contract["readiness"]["card"]["value"] = "plausible"
        self.assert_rejected(contract, "does not match the canonical")

        contract = base_contract()
        contract["readiness"]["card"]["value"] = "plausible"
        canonical = json.dumps(contract["readiness"]["card"], sort_keys=True, separators=(",", ":")).encode()
        contract["readiness"]["card_sha256"] = hashlib.sha256(canonical).hexdigest()
        self.assert_rejected(contract, "recomputed scorer outcome")

        contract = base_contract()
        reordered = dict(reversed(list(contract["readiness"]["card"].items())))
        contract["readiness"]["card"] = reordered
        self.assertIs(VALIDATOR.validate_contract(contract), contract)

    def test_every_replay_loop_outcome_has_an_exact_representative_contract(self) -> None:
        cases = VALIDATOR.READINESS_SCORER.load_json(READINESS_REPLAY_PATH)
        observed_loop_ids: set[str] = set()
        for case in cases:
            result = VALIDATOR.READINESS_SCORER.score(case["card"])
            if result["outcome"] not in {"read_only_triage_loop", "supervised_loop"}:
                continue
            case_id = case["id"]
            observed_loop_ids.add(case_id)
            with self.subTest(case=case_id):
                representative = copy.deepcopy(REPRESENTATIVE_LOOP_SCOPES[case_id])
                contract = base_contract()
                card = copy.deepcopy(case["card"])
                contract["readiness"].update(
                    outcome=result["outcome"],
                    card=card,
                    card_sha256=hashlib.sha256(
                        json.dumps(
                            card,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode("utf-8")
                    ).hexdigest(),
                    permission_scope=card["permission_scope"],
                    requested_autonomy=card["requested_autonomy"],
                    data_handling=card["data_handling"],
                )
                contract["scope"]["allowed_paths"] = representative["allowed_paths"]
                contract["scope"]["allowed_tools"] = representative["allowed_tools"]
                contract["scope"]["allowed_actions"] = representative["allowed_actions"]
                contract["state"] = representative["state"]
                capabilities = (
                    representative["allowed_tools"]
                    + representative["allowed_actions"]
                )
                contract["approvals"] = [
                    {"action": "activate", "required": True, "approver": "human"},
                    *[
                        {
                            "action": item["id"],
                            "required": True,
                            "approver": "human",
                        }
                        for item in capabilities
                    ],
                ]
                self.assertEqual(contract["readiness"]["card"], case["card"])
                self.assertIs(VALIDATOR.validate_contract(contract), contract)
        self.assertEqual(observed_loop_ids, set(REPRESENTATIVE_LOOP_SCOPES))

    def test_semantic_review_is_exactly_required_and_pending(self) -> None:
        for semantic_review in (
            {"required": False, "status": "pending"},
            {"required": True, "status": "complete"},
            {"required": True, "status": "pending", "reviewer": "self"},
        ):
            contract = base_contract(); contract["semantic_review"] = semantic_review
            self.assert_rejected(contract)

    def test_read_only_outcome_has_ordinary_observation_only_scope_and_no_workspace_state(self) -> None:
        cases = []
        sensitive = read_only_contract(); sensitive["readiness"].update(data_handling="host-managed-sensitive", permission_scope="least-privilege")
        cases.append(sensitive)
        local = read_only_contract()
        local["scope"]["allowed_paths"] = ["reports/loop-output/local-report-loop-v1/output.json"]
        local["scope"]["allowed_tools"] = [capability("local-writer", "workspace.write")]
        local["approvals"].append({"action":"local-writer","required":True,"approver":"human"})
        cases.append(local)
        unused_write = read_only_contract(); unused_write["scope"]["allowed_paths"] = ["reports/loop-output/unused"]
        cases.append(unused_write)
        workspace_state = read_only_contract()
        workspace_state["scope"]["allowed_paths"]=["reports/loop-output/local-report-loop-v1/state.json"]
        workspace_state["state"]={"kind":"workspace-file","location":"reports/loop-output/local-report-loop-v1/state.json","retention":{"mode":"bounded","max_records":10,"max_age_days":10}}
        cases.append(workspace_state)
        for contract in cases:
            self.assert_rejected(contract)

    def test_manual_card_cannot_be_mislabeled_as_a_supervised_loop(self) -> None:
        contract = base_contract()
        contract["readiness"]["card"]["permission_scope"] = "broad"
        canonical = json.dumps(contract["readiness"]["card"], sort_keys=True, separators=(",", ":")).encode()
        contract["readiness"]["card_sha256"] = hashlib.sha256(canonical).hexdigest()
        contract["readiness"]["permission_scope"] = "broad"
        self.assert_rejected(contract, "recomputed scorer outcome")

    def test_capability_schema_category_effect_and_v1_denials(self) -> None:
        invalid_entries = (
            ({"id":"reader","operation_id":"workspace.observe","display_name":"Reader"}, "missing fields"),
            ({"id":"reader","operation_id":"workspace.observe","display_name":"Reader","binding_status":"unbound","runtime_ref":"tool"}, "unknown fields"),
            ({"id":"reader","operation_id":"workspace.observe","display_name":"Reader","binding_status":"unbound","category":"observation","effect":"read-only"}, "unknown fields"),
            ({"id":"reader","operation_id":"workspace.delete","display_name":"Reader","binding_status":"unbound"}, "operation_id is not supported"),
            ({"id":"reader","operation_id":"lifecycle.activate","display_name":"Reader","binding_status":"unbound"}, "operation_id is not supported"),
            ({"id":"reader","operation_id":"workspace.observe","display_name":"Reader","binding_status":"bound"}, "unbound and non-executable"),
        )
        for entry, message in invalid_entries:
            contract = base_contract(); contract["scope"]["allowed_actions"] = [entry]
            self.assert_rejected(contract, message)

    def test_lifecycle_semantic_aliases_are_denied_conservatively(self) -> None:
        aliases = (
            "activate-loop", "activated-loop", "activating-loop", "activation-client", "enable-agent", "enablement-client",
            "scheduler-client", "create-cron-job", "timer-client", "periodic-runner",
            "launchd-client", "systemd-client", "create-at-job", "install-plugin",
            "installer-client", "publish-package", "publisher-client",
        )
        for alias in aliases:
            with self.subTest(alias=alias):
                contract = base_contract()
                contract["scope"]["allowed_actions"] = [capability("candidate-operation", "workspace.write", alias)]
                self.assert_rejected(contract, "lifecycle capability aliases")

    def test_destructive_semantic_aliases_are_rejected_regardless_of_declaration(self) -> None:
        for token in ("delete", "destroy", "revoke", "wipe", "terminate", "drop", "purge", "truncate", "erase"):
            contract = base_contract()
            contract["scope"]["allowed_actions"] = [
                capability("candidate-operation", "workspace.write", f"{token} record")
            ]
            self.assert_rejected(contract, "destructive capability aliases")

    def test_reproduced_obvious_aliases_are_denied_but_display_names_never_define_semantics(self) -> None:
        denied = (
            "start-recurring-run", "remove-record", "post-webhook", "deploy-production",
            "call-api", "curl-post", "sendemail", "mail-client", "slack-notifier",
            "keychain-reader", "vault-reader", "launch-agent", "background-job",
            "windows-task", "schtasks-client", "turn-on-loop",
        )
        for display in denied:
            contract = base_contract()
            contract["scope"]["allowed_actions"] = [
                capability("candidate-operation", "workspace.write", display)
            ]
            self.assert_rejected(contract, "obvious unsafe capability aliases")

        proposal = base_contract()
        proposal["scope"]["allowed_actions"] = [
            capability("unbound-proposal", "workspace.write", "Arbitrary future host label")
        ]
        proposal["approvals"].append({"action":"unbound-proposal","required":True,"approver":"human"})
        self.assertIs(VALIDATOR.validate_contract(proposal), proposal)
        self.assertEqual(proposal["scope"]["allowed_actions"][0]["binding_status"], "unbound")

    def test_mandatory_lifecycle_denies_remain_exact(self) -> None:
        for denied in VALIDATOR.MANDATORY_PROHIBITED_ACTIONS:
            contract = base_contract(); contract["scope"]["prohibited_actions"].remove(denied)
            self.assert_rejected(contract, "mandatory lifecycle denies")

    def test_every_allowed_capability_requires_exact_human_approval(self) -> None:
        for name in ("fixture-observer", "report-writer", "write-report"):
            contract = base_contract()
            contract["approvals"] = [item for item in contract["approvals"] if item["action"] != name]
            self.assert_rejected(contract, "every allowed capability requires exact human approval")

    def test_external_system_requires_supervision_least_privilege_exact_approval(self) -> None:
        contract = base_contract()
        contract["scope"]["allowed_actions"] = [capability("create-draft-record", "external.write")]
        bind_card(contract, action_scope="external-reversible")
        self.assert_rejected(contract, "exact human approval")
        contract["approvals"].append({"action":"create-draft-record","required":True,"approver":"human"})
        self.assertIs(VALIDATOR.validate_contract(contract), contract)
        bind_card(contract, permission_scope="none")
        self.assert_rejected(contract)

    def test_external_read_operation_has_closed_supervised_readiness_scope(self) -> None:
        contract = base_contract()
        contract["scope"]["allowed_paths"] = []
        contract["scope"]["allowed_tools"] = [capability("external-observer", "external.read")]
        contract["scope"]["allowed_actions"] = []
        contract["state"] = {"kind":"none","location":"","retention":{"mode":"none"}}
        contract["approvals"] = [
            {"action":"activate","required":True,"approver":"human"},
            {"action":"external-observer","required":True,"approver":"human"},
        ]
        bind_card(contract, action_scope="external-read-only", state_scope="none")
        self.assertEqual(contract["readiness"]["outcome"], "supervised_loop")
        self.assertIs(VALIDATOR.validate_contract(contract), contract)

    def test_prohibited_action_tokens_are_enforced_against_display_names(self) -> None:
        contract = base_contract()
        contract["scope"]["prohibited_actions"].append("archive-record")
        contract["scope"]["allowed_actions"] = [
            capability("candidate-operation", "workspace.write", "Review archive-record proposal")
        ]
        self.assert_rejected(contract, "display name conflicts with a prohibited action")

    def test_credential_access_requires_sensitive_data_least_privilege_supervision_and_exact_approval(self) -> None:
        contract = base_contract()
        contract["scope"]["allowed_tools"] = [capability("host-credential-reader", "credential.read")]
        contract["scope"]["allowed_actions"] = []
        contract["scope"]["allowed_paths"] = []
        contract["state"] = {"kind":"none","location":"","retention":{"mode":"none"}}
        bind_card(contract, action_scope="read-only", state_scope="none", data_handling="host-managed-sensitive")
        self.assert_rejected(contract, "exact human approval")
        contract["approvals"].append({"action":"host-credential-reader","required":True,"approver":"human"})
        self.assertIs(VALIDATOR.validate_contract(contract), contract)
        bind_card(contract, permission_scope="none")
        self.assert_rejected(contract)

    def test_sensitive_data_without_credential_capability_is_rejected(self) -> None:
        contract = base_contract(); bind_card(contract, data_handling="host-managed-sensitive")
        self.assert_rejected(contract, "requires a credential-access")

    def test_high_confidence_embedded_secret_patterns_are_rejected(self) -> None:
        patterns = (
            "xox" + "b-" + "A" * 24,
            "glpat-" + "A" * 24,
            "sk_live_" + "A" * 24,
            "AIza" + "A" * 35,
            "ASIA" + "A" * 16,
            "aws_secret_access_key=" + "A" * 40,
            "Authorization: Bearer " + "A" * 32,
            "eyJ" + "A" * 12 + "." + "B" * 12 + "." + "C" * 12,
            "ghp_" + "A" * 24,
            "sk-" + "A" * 24,
            "hf_" + "A" * 24,
            "npm_" + "A" * 24,
            "pypi-" + "A" * 36,
            "-----BEGIN " + "PRIVATE KEY-----",
            "-----BEGIN " + "ENCRYPTED PRIVATE KEY-----",
            "-----BEGIN " + "PGP PRIVATE KEY BLOCK-----",
            "https://user:" + "password@example.invalid",
        )
        for value in patterns:
            with self.subTest(prefix=value[:8]):
                contract = base_contract(); contract["inputs"] = [value]
                self.assert_rejected(contract, "embedded credential material")

    def test_generic_assignments_queries_and_adjacent_split_secrets_are_rejected(self) -> None:
        assignment_names = ("api_key", "access_token", "client_secret", "password", "token", "secret")
        for name in assignment_names:
            contract = base_contract()
            contract["inputs"] = [name + "=" + "A" * 24]
            self.assert_rejected(contract, "embedded credential material")
            query = base_contract()
            query["inputs"] = ["?" + name + "=" + "B" * 24]
            self.assert_rejected(query, "embedded credential material")

        for split in (
            ["ghp_", "A" * 24],
            ["sk-", "B" * 24],
            ["api_key=", "C" * 24],
            ["gh", "p_", "D" * 10, "E" * 14],
            ["to", "ken", "=", "F" * 8, "G" * 8],
        ):
            contract = base_contract(); contract["inputs"] = split
            self.assert_rejected(contract, "split embedded credential material")

        boundary = base_contract()
        boundary["inputs"] = [
            "token=",
            "H" * VALIDATOR.MAX_STRING_LENGTH,
            "I" * (
                VALIDATOR.MAX_SECRET_ADJACENT_CHARS
                - VALIDATOR.MAX_STRING_LENGTH
                - len("token=")
            ),
        ]
        self.assertEqual(
            sum(map(len, boundary["inputs"])),
            VALIDATOR.MAX_SECRET_ADJACENT_CHARS,
        )
        self.assert_rejected(boundary, "split embedded credential material")

        for split in (
            ["gh", "p_", "J" * 10, "K" * 14],
            ["to", "ken", "=", "L" * 8, "M" * 8],
        ):
            result = run_cli(
                "--contract", "-",
                input_bytes=json.dumps(
                    {**base_contract(), "inputs": split}
                ).encode("utf-8"),
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn(b"split embedded credential material", result.stderr)
            self.assertNotIn(b"ghp_", result.stderr)
            self.assertNotIn(b"token=", result.stderr)
            self.assertNotIn(b"Traceback", result.stderr)

        observed_lengths: list[int] = []
        original_adjacent_scan = VALIDATOR._contains_adjacent_secret
        try:
            VALIDATOR._contains_adjacent_secret = (
                lambda value: observed_lengths.append(len(value)) or False
            )
            VALIDATOR._scan_secret_material(
                ["N" * VALIDATOR.MAX_STRING_LENGTH] * 3
            )
        finally:
            VALIDATOR._contains_adjacent_secret = original_adjacent_scan
        self.assertEqual(observed_lengths[-1], VALIDATOR.MAX_SECRET_ADJACENT_CHARS)
        self.assertLessEqual(
            max(observed_lengths), VALIDATOR.MAX_SECRET_ADJACENT_CHARS
        )

    def test_secret_bearing_keys_are_rejected_without_echoing_key(self) -> None:
        contract = base_contract(); contract["custom_authorization_token"] = "reference-only"
        with self.assertRaisesRegex(VALIDATOR.ContractError, "embedded credential field") as caught:
            VALIDATOR.validate_contract(contract)
        self.assertNotIn("custom_authorization_token", str(caught.exception))

    def test_portable_paths_reject_ambiguous_control_plane_and_nonportable_forms(self) -> None:
        unsafe = (
            "../reports", "/tmp/reports", "~/reports", "$WORK/reports", "reports/*", ".",
            "C:\\reports", "C:reports", "reports\\out", "reports//out", "reports/./out",
            "reports/../out", "reports/out/", "reports/has space", "reports/\x00out",
            ".git/config", ".env", ".env.production", ".ssh/config", ".github/workflows",
            ".gitlab-ci.yml", "ci/Jenkinsfile",
        )
        for path in unsafe:
            with self.subTest(path=repr(path)):
                contract = base_contract(); contract["scope"]["allowed_paths"] = [path]
                self.assert_rejected(contract)

    def test_write_paths_are_confined_and_reject_control_sensitive_and_windows_device_names(self) -> None:
        allowed = base_contract()
        allowed["scope"]["allowed_paths"] = [
            "loop-data/local-report-loop-v1/results.json",
            "loop-data/local-report-loop-v1/state.json",
        ]
        allowed["state"]["location"] = "loop-data/local-report-loop-v1/state.json"
        self.assertIs(VALIDATOR.validate_contract(allowed), allowed)

        unsafe = (
            "output/report.json", "reports/other/report.json",
            "loop-data/local-report-loop-v1", "reports/loop-output/local-report-loop-v1",
            "loop-data/another-proposal/report.json",
            "reports/loop-output/local-report-loop-v1/nested/report.json",
            "reports/loop-output/local-report-loop-v1/AGENTS.md",
            "loop-data/local-report-loop-v1/CLAUDE.md", "loop-data/local-report-loop-v1/SKILL.md",
            "loop-data/local-report-loop-v1/package.json", "loop-data/local-report-loop-v1/build.py",
            "loop-data/local-report-loop-v1/secret.json", "loop-data/local-report-loop-v1/api-token.json",
            "loop-data/local-report-loop-v1/CON", "loop-data/local-report-loop-v1/con.txt",
            "loop-data/local-report-loop-v1/PRN.json", "loop-data/local-report-loop-v1/AUX.txt",
            "loop-data/local-report-loop-v1/NUL.log", "loop-data/local-report-loop-v1/CLOCK$",
            "loop-data/local-report-loop-v1/COM1.txt", "loop-data/local-report-loop-v1/LPT9.log",
            "loop-data/local-report-loop-v1/trailing.", "loop-data/local-report-loop-v1/report.md",
            "loop-data/local-report-loop-v1/REPORT.json",
        )
        for path in unsafe:
            with self.subTest(path=path):
                contract = base_contract(); contract["scope"]["allowed_paths"] = [path]
                self.assert_rejected(contract)

        collision = base_contract()
        collision["scope"]["allowed_paths"] = [
            "reports/loop-output/local-report-loop-v1/report.json",
            "reports/loop-output/local-report-loop-v1/REPORT.json",
        ]
        self.assert_rejected(collision, "case-insensitive duplicate targets")

        mixed_case_state = base_contract()
        mixed_case_state["state"]["location"] = (
            "reports/loop-output/local-report-loop-v1/State.json"
        )
        self.assert_rejected(mixed_case_state, "canonical lowercase output components")

    def test_evidence_references_use_closed_non_authorizing_grammar(self) -> None:
        valid = base_contract()
        valid["evidence_refs"].append("workspace:docs/triage-case.json")
        self.assertIs(VALIDATOR.validate_contract(valid), valid)
        invalid = (
            "file:x/../../secret", "workspace:x/../../secret", "workspace:C:secret",
            "workspace:x\\secret", "source:Uppercase", "https://user:" + "pass@example.invalid",
            "unknown:item", "workspace:x/\u202ey",
        )
        for ref in invalid:
            with self.subTest(ref=repr(ref)):
                contract = base_contract(); contract["evidence_refs"].append(ref)
                self.assert_rejected(contract)

    def test_unicode_control_format_surrogate_and_separator_spoofing_is_rejected_without_echo(self) -> None:
        for character in ("\u0085", "\u009b", "\u202e", "\u2066", "\u200f", "\u2028", "\ud800"):
            contract = base_contract(); contract["objective"] = f"safe{character}spoof"
            with self.assertRaisesRegex(VALIDATOR.ContractError, "unsupported control characters") as caught:
                VALIDATOR.validate_contract(contract)
            self.assertNotIn(character, str(caught.exception))
            escaped_surrogate = character == "\ud800"
            result = run_cli(
                "--contract", "-",
                input_bytes=json.dumps(contract, ensure_ascii=escaped_surrogate).encode("utf-8"),
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn(b"unsupported control characters", result.stderr)
            self.assertNotIn(b"Traceback", result.stderr)
            result.stderr.decode("utf-8", errors="strict")
            if escaped_surrogate:
                self.assertNotIn(b"\\ud800", result.stderr.lower())
            else:
                self.assertNotIn(character.encode("utf-8"), result.stderr)

    def test_local_workspace_requires_allowed_paths_and_state_containment(self) -> None:
        contract = base_contract(); contract["scope"]["allowed_paths"] = []
        self.assert_rejected(contract, "require allowed_paths")
        outside = base_contract()
        outside["scope"]["allowed_paths"] = ["reports/loop-output/local-report-loop-v1/report.json"]
        outside["state"]["location"] = "reports/loop-output/local-report-loop-v1/state.json"
        self.assert_rejected(outside, "exactly equal")
        equal = base_contract()
        equal["scope"]["allowed_paths"]=["reports/loop-output/local-report-loop-v1/state.json"]
        self.assertIs(VALIDATOR.validate_contract(equal), equal)

    def test_host_managed_mutable_state_is_rejected_in_v1(self) -> None:
        contract = base_contract()
        contract["state"] = {"kind":"host-managed","location":"ci-triage.state_v1","retention":{"mode":"bounded","max_records":50,"max_age_days":90}}
        self.assert_rejected(contract, "host-managed mutable state is prohibited")

    def test_workspace_state_requires_exact_namespaced_target_and_workspace_write_capability(self) -> None:
        missing_capability = base_contract()
        missing_capability["scope"]["allowed_tools"] = [
            capability("external-writer", "external.write")
        ]
        missing_capability["scope"]["allowed_actions"] = []
        missing_capability["approvals"] = [
            {"action":"activate","required":True,"approver":"human"},
            {"action":"external-writer","required":True,"approver":"human"},
        ]
        bind_card(missing_capability, action_scope="external-reversible")
        self.assert_rejected(missing_capability, "requires a local-workspace capability")

        collision = base_contract()
        collision["state"]["location"] = "loop-data/another-proposal/state.json"
        self.assert_rejected(collision, "proposal-namespaced")

    def test_state_and_retention_are_coherent_and_closed(self) -> None:
        bad_states = (
            {"kind":"none","location":"state","retention":{"mode":"none"}},
            {"kind":"none","location":"","retention":{"mode":"bounded","max_records":1,"max_age_days":1}},
            {"kind":"workspace-file","location":"reports/loop-output/local-report-loop-v1/state.json","retention":{"mode":"none","max_records":1,"max_age_days":1}},
            {"kind":"workspace-file","location":"reports/loop-output/local-report-loop-v1/state.json","retention":{"mode":"bounded","max_records":0,"max_age_days":1}},
        )
        for state in bad_states:
            contract = base_contract(); contract["state"] = state
            self.assert_rejected(contract)

    def test_terminal_states_are_the_exact_closed_unique_set(self) -> None:
        for states in (
            ["complete", "blocked", "failed"],
            ["complete", "blocked", "needs-approval", "failed", "timeout"],
            ["complete", "blocked", "needs-approval", "failed", "failed"],
        ):
            contract = base_contract(); contract["terminal_states"] = states
            self.assert_rejected(contract)

    def test_v1_limits_have_exact_practical_bounds_including_zero_retries(self) -> None:
        valid = base_contract(); valid["limits"]={"max_iterations":50,"max_retries":0,"max_elapsed_minutes":240}
        self.assertIs(VALIDATOR.validate_contract(valid), valid)
        for field, value in (("max_iterations",0),("max_iterations",51),("max_retries",-1),("max_retries",6),("max_elapsed_minutes",0),("max_elapsed_minutes",241)):
            contract = base_contract(); contract["limits"][field] = value
            self.assert_rejected(contract, f"limits.{field}")

    def test_every_non_pending_dry_run_result_requires_evidence(self) -> None:
        for result in ("passed", "failed"):
            contract = base_contract(); contract["dry_run"]["result"] = result
            self.assert_rejected(contract, "non-pending")
            contract["dry_run"]["evidence_refs"] = ["source:dry-run-fixture-one"]
            self.assertIs(VALIDATOR.validate_contract(contract), contract)

    def test_schedule_proposal_requires_distinct_schedule_and_activation_approvals(self) -> None:
        contract = base_contract(); contract["trigger"]["type"] = "schedule-proposal"
        self.assert_rejected(contract, "distinct human schedule approval")
        contract["approvals"].append({"action":"schedule","required":True,"approver":"human"})
        self.assertIs(VALIDATOR.validate_contract(contract), contract)
        self.assertEqual(contract["lifecycle"]["scheduler_status"], "inactive")

    def test_lifecycle_and_verifier_remain_draft_pending_inactive(self) -> None:
        mutations = (
            lambda c: c["acceptance"]["verifier"].update(status="verified"),
            lambda c: c["lifecycle"].update(proposal_status="ready"),
            lambda c: c["lifecycle"].update(activation_status="active"),
            lambda c: c["lifecycle"].update(scheduler_status="scheduled"),
        )
        for mutate in mutations:
            contract = base_contract(); mutate(contract)
            self.assert_rejected(contract)

    def test_cli_supports_bounded_stdin_and_unrelated_cwd(self) -> None:
        payload = json.dumps(base_contract()).encode()
        with tempfile.TemporaryDirectory() as directory:
            result = run_cli("--contract", "-", input_bytes=payload, cwd=Path(directory))
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertNotIn("valid", output)
        self.assertEqual(output["structurally_valid"], True)
        self.assertEqual(output["semantic_review_required"], True)
        self.assertEqual(output["activation_allowed"], False)

    def test_cli_rejects_invalid_bytes_deep_json_huge_int_and_oversize_without_traceback(self) -> None:
        payloads = (
            b"\xff\xfe", b"[" * 2000, b'{"n":' + b"9" * 5000 + b"}",
            b" " * (VALIDATOR.MAX_INPUT_BYTES + 1),
        )
        for payload in payloads:
            result = run_cli("--contract", "-", input_bytes=payload)
            self.assertEqual(result.returncode, 2)
            self.assertIn(b"ERROR:", result.stderr)
            self.assertNotIn(b"Traceback", result.stderr)

    def test_cli_rejects_symlink_and_fifo_without_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); target = root / "contract.json"
            target.write_text(json.dumps(base_contract()), encoding="utf-8")
            link = root / "contract-link.json"; link.symlink_to(target)
            result = run_cli("--contract", str(link))
            self.assertEqual(result.returncode, 2)
            self.assertIn(b"must not be a symlink", result.stderr)
            if hasattr(os, "mkfifo"):
                fifo = root / "contract.fifo"; os.mkfifo(fifo)
                result = run_cli("--contract", str(fifo))
                self.assertEqual(result.returncode, 2)
                self.assertIn(b"regular file", result.stderr)

    def test_cli_errors_do_not_emit_ansi_sensitive_fragments_or_raw_paths(self) -> None:
        payload = b'{"' + b"\\u001b" + b'[31msecret-token":"value"}'
        result = run_cli("--contract", "-", input_bytes=payload)
        self.assertEqual(result.returncode, 2)
        self.assertNotIn(b"\x1b", result.stderr)
        self.assertNotIn(b"secret-token", result.stderr)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "private-name-\x1b[31m.json"
            result = run_cli("--contract", str(path))
            self.assertNotIn(str(path).encode(), result.stderr)
            self.assertNotIn(b"\x1b", result.stderr)


if __name__ == "__main__":
    unittest.main()
