from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "skills/code-review/scripts/select_review_scope.py"
REPLAY_PATH = ROOT / "skills/code-review/tests/scope-cases.json"
SPEC = importlib.util.spec_from_file_location("code_review_scope", SCRIPT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load select_review_scope.py")
SELECTOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SELECTOR)
VERIFY_PATH = ROOT / "scripts/verify_repository.py"
VERIFY_SPEC = importlib.util.spec_from_file_location("code_review_repository_verifier", VERIFY_PATH)
if VERIFY_SPEC is None or VERIFY_SPEC.loader is None:
    raise RuntimeError("could not load verify_repository.py")
REPOSITORY_VERIFIER = importlib.util.module_from_spec(VERIFY_SPEC)
VERIFY_SPEC.loader.exec_module(REPOSITORY_VERIFIER)


class CodeReviewScopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = SELECTOR.load_json(REPLAY_PATH)
        cls.by_id = {case["id"]: case for case in cls.cases}

    def result(self, case_id: str) -> dict[str, object]:
        return SELECTOR.select_scope(copy.deepcopy(self.by_id[case_id]["card"]))

    def test_replay_covers_required_selection_and_composition_cases(self) -> None:
        required = {
            "explicit-pr-wins-when-probe-unavailable",
            "explicit-local-never-merges-pr-files",
            "unique-branch-pr",
            "detached-head-unique-oid-match",
            "conclusive-no-pr-falls-back-local",
            "branch-pr-ambiguity-needs-input",
            "probe-failure-is-not-no-pr",
            "monorepo-nearest-boundary-prevents-rn-leakage",
            "react-native-does-not-imply-react-web",
            "all-specialists-compose-in-fixed-order",
            "native-only-android-change-in-rn-package",
            "native-only-ios-change-in-expo-package",
            "ancestor-native-path-ignores-nested-rn-package",
            "root-web-change-ignores-nested-mobile-native-tree",
            "caller-adds-overlay-and-specialist-implies-js-ts",
            "caller-exact-set-replaces-auto-and-keeps-order",
            "removed-next-dependency-selects-react-web",
            "removed-nest-import-selects-node",
            "removed-react-native-dependency-does-not-infer-react-web",
            "removed-expo-import-does-not-infer-react-web",
        }
        self.assertEqual(set(self.by_id), required)
        self.assertEqual(SELECTOR.check_replay(REPLAY_PATH), 0)

    def test_explicit_local_contains_each_local_inventory_and_no_pr_files(self) -> None:
        result = self.result("explicit-local-never-merges-pr-files")
        self.assertEqual(result["changed_files"], ["staged.ts", "unstaged.ts", "new.ts"])
        self.assertNotIn("pr-only.ts", result["changed_files"])
        self.assertEqual(result["target"]["staged"], ["staged.ts"])
        self.assertEqual(result["target"]["unstaged"], ["unstaged.ts"])
        self.assertEqual(result["target"]["untracked"], ["new.ts"])

    def test_selected_pr_preserves_auditable_patch_and_refs(self) -> None:
        target = self.result("explicit-pr-wins-when-probe-unavailable")["target"]
        self.assertEqual(target["number"], 7)
        self.assertEqual(target["base_ref"], "main")
        self.assertEqual(target["head_ref"], "feature")
        self.assertEqual(target["head_oid"], "aaa")
        self.assertEqual(target["patch"], "")
        self.assertEqual(target["files"], ["src/view.tsx"])

    def test_probe_failure_never_falls_back_to_local(self) -> None:
        result = self.result("probe-failure-is-not-no-pr")
        self.assertEqual(result["status"], "needs_input")
        self.assertIsNone(result["target"])
        self.assertEqual(result["changed_files"], [])

    def test_detached_head_filters_by_exact_oid(self) -> None:
        result = self.result("detached-head-unique-oid-match")
        self.assertEqual(result["target"]["number"], 10)
        self.assertEqual(result["reason"], "detached-head-oid")

    def test_explicit_and_discovered_prs_allow_empty_patch_text(self) -> None:
        explicit = self.result("explicit-pr-wins-when-probe-unavailable")["target"]
        discovered = self.result("unique-branch-pr")["target"]
        self.assertEqual(explicit["patch"], "")
        self.assertEqual(discovered["patch"], "")
        card = copy.deepcopy(self.by_id["unique-branch-pr"]["card"])
        card["pr_probe"]["candidates"][0]["patch"] = None
        with self.assertRaisesRegex(SELECTOR.ScopeError, "patch must be a string"):
            SELECTOR.select_scope(card)

    def test_monorepo_detection_uses_nearest_boundary(self) -> None:
        result = self.result("monorepo-nearest-boundary-prevents-rn-leakage")
        self.assertEqual(result["overlays"], ["javascript-typescript", "react-nextjs"])
        web_evidence = "\n".join(result["overlay_evidence"]["react-nextjs"])
        self.assertIn("packages/web/package.json", web_evidence)
        self.assertNotIn("packages/mobile", web_evidence)

    def test_root_change_ignores_nested_mobile_native_tree(self) -> None:
        result = self.result("root-web-change-ignores-nested-mobile-native-tree")
        self.assertEqual(result["overlays"], ["javascript-typescript", "react-nextjs"])
        self.assertNotIn("react-native", result["overlay_evidence"])

    def test_native_only_android_and_ios_changes_select_rn_at_matching_boundary(self) -> None:
        for case_id, changed_path in (
            ("native-only-android-change-in-rn-package", "apps/mobile/android/app/src/main/java/com/example/MainActivity.kt"),
            ("native-only-ios-change-in-expo-package", "apps/mobile/ios/Mobile/AppDelegate.swift"),
        ):
            with self.subTest(case=case_id):
                result = self.result(case_id)
                self.assertEqual(result["overlays"], ["javascript-typescript", "react-native"])
                self.assertIn(
                    f"platform-file:{changed_path}",
                    result["overlay_evidence"]["react-native"],
                )

    def test_native_only_change_does_not_borrow_nested_package_evidence(self) -> None:
        result = self.result("ancestor-native-path-ignores-nested-rn-package")
        self.assertEqual(result["overlays"], [])
        self.assertEqual(result["overlay_evidence"], {})

    def test_react_native_does_not_implicitly_select_react_web(self) -> None:
        result = self.result("react-native-does-not-imply-react-web")
        self.assertIn("react-native", result["overlays"])
        self.assertNotIn("react-nextjs", result["overlays"])

    def test_removed_framework_evidence_selects_each_specialist(self) -> None:
        expectations = (
            (
                "removed-next-dependency-selects-react-web",
                "react-nextjs",
                "removed-dependency:next@package.json",
            ),
            (
                "removed-nest-import-selects-node",
                "node-nestjs",
                "removed-import:@nestjs/common@src/app.ts",
            ),
            (
                "removed-react-native-dependency-does-not-infer-react-web",
                "react-native",
                "removed-dependency:react-native@package.json",
            ),
            (
                "removed-expo-import-does-not-infer-react-web",
                "react-native",
                "removed-import:expo-router@src/router.ts",
            ),
        )
        for case_id, overlay, evidence in expectations:
            with self.subTest(case=case_id):
                result = self.result(case_id)
                self.assertIn(overlay, result["overlays"])
                self.assertIn(evidence, result["overlay_evidence"][overlay])

        for case_id in (
            "removed-react-native-dependency-does-not-infer-react-web",
            "removed-expo-import-does-not-infer-react-web",
        ):
            self.assertNotIn("react-nextjs", self.result(case_id)["overlays"])

    def test_all_overlays_have_one_fixed_composition_order(self) -> None:
        self.assertEqual(
            self.result("all-specialists-compose-in-fixed-order")["overlays"],
            list(SELECTOR.OVERLAY_ORDER),
        )

    def test_exact_and_add_overrides_expand_specialists_to_js_ts(self) -> None:
        added = self.result("caller-adds-overlay-and-specialist-implies-js-ts")
        exact = self.result("caller-exact-set-replaces-auto-and-keeps-order")
        self.assertEqual(added["overlays"], ["javascript-typescript", "node-nestjs"])
        self.assertEqual(exact["overlays"], ["javascript-typescript", "react-native"])
        self.assertIn(
            "implied-by-specialist-overlay",
            exact["overlay_evidence"]["javascript-typescript"],
        )
        self.assertIn(
            "caller-override:add:node-nestjs",
            added["overlay_evidence"]["node-nestjs"],
        )
        self.assertIn(
            "caller-override:implied-by:node-nestjs",
            added["overlay_evidence"]["javascript-typescript"],
        )
        self.assertIn(
            "caller-override:exact:react-native",
            exact["overlay_evidence"]["react-native"],
        )
        self.assertIn(
            "caller-override:implied-by:react-native",
            exact["overlay_evidence"]["javascript-typescript"],
        )

    def test_nest_namespace_detection_accepts_real_modules_only(self) -> None:
        card = copy.deepcopy(self.by_id["unique-branch-pr"]["card"])
        candidate = card["pr_probe"]["candidates"][0]
        candidate["files"] = ["src/worker.ts"]
        card["workspace_files"] = ["package.json", "src/worker.ts"]
        card["manifests"] = [{"path": "package.json", "dependencies": ["@nestjs/microservices"]}]
        card["imports"] = {"src/worker.ts": ["@nestjs/microservices"]}
        self.assertIn("node-nestjs", SELECTOR.select_scope(card)["overlays"])

        card["manifests"][0]["dependencies"] = ["@nestjsish/microservices"]
        card["imports"]["src/worker.ts"] = ["@nestjsish/microservices"]
        self.assertNotIn("node-nestjs", SELECTOR.select_scope(card)["overlays"])

    def test_expo_import_and_app_json_require_real_expo_evidence(self) -> None:
        card = copy.deepcopy(self.by_id["explicit-local-never-merges-pr-files"]["card"])
        card["local_changes"] = {"staged": ["app.json"], "unstaged": [], "untracked": []}
        card["workspace_files"] = ["package.json", "app.json"]
        card["manifests"] = [{"path": "package.json", "dependencies": ["expo-router"]}]
        card["imports"] = {}
        result = SELECTOR.select_scope(card)
        self.assertIn("react-native", result["overlays"])
        self.assertIn("config:app.json", result["overlay_evidence"]["react-native"])

        card["local_changes"] = {"staged": ["src/routes.ts"], "unstaged": [], "untracked": []}
        card["workspace_files"].append("src/routes.ts")
        card["manifests"] = [{"path": "package.json", "dependencies": []}]
        card["imports"] = {"src/routes.ts": ["expo-router"]}
        self.assertIn("react-native", SELECTOR.select_scope(card)["overlays"])

        card["local_changes"] = {"staged": ["app.json"], "unstaged": [], "untracked": []}
        card["imports"] = {}
        result = SELECTOR.select_scope(card)
        self.assertNotIn("react-native", result["overlays"])

    def test_unknown_overlay_and_ambiguous_override_are_rejected(self) -> None:
        card = copy.deepcopy(self.by_id["unique-branch-pr"]["card"])
        card["overlay_override"] = {"add": ["django"]}
        with self.assertRaisesRegex(SELECTOR.ScopeError, "unknown overlay IDs: django"):
            SELECTOR.select_scope(card)
        card["overlay_override"] = {"add": [], "exact": []}
        with self.assertRaisesRegex(SELECTOR.ScopeError, "overlay_override must be"):
            SELECTOR.select_scope(card)

    def test_overlay_provenance_requires_one_unique_rule_per_concern_and_row(self) -> None:
        name = "code-review-javascript-typescript"
        valid_body = (
            "## Mapped review concerns\n\n"
            "- [TEST-001] First normative concern.\n"
            "- [TEST-002] Second normative concern.\n\n"
            "Do not report unrelated preferences.\n"
        )
        valid_rows = (
            "| Rule ID | Concept | Applicability / version | Authoritative source | Last verified |\n"
            "| --- | --- | --- | --- | --- |\n"
            "| TEST-001 | First | Current TypeScript | [Source](https://www.typescriptlang.org/docs/) | 2026-08-11 |\n"
            "| TEST-002 | Second | Current TypeScript | [Source](https://www.typescriptlang.org/docs/) | 2026-08-11 |\n"
        )
        REPOSITORY_VERIFIER.validate_overlay_provenance(name, valid_body, valid_rows)

        duplicate_concern = valid_body.replace("[TEST-002]", "[TEST-001]")
        with self.assertRaisesRegex(
            REPOSITORY_VERIFIER.OverlayProvenanceError,
            "maps Rule ID TEST-001 to more than one concern",
        ):
            REPOSITORY_VERIFIER.validate_overlay_provenance(name, duplicate_concern, valid_rows)

        multi_id = valid_body.replace("[TEST-001]", "[TEST-001, TEST-003]", 1)
        with self.assertRaisesRegex(
            REPOSITORY_VERIFIER.OverlayProvenanceError,
            "exactly one Rule ID",
        ):
            REPOSITORY_VERIFIER.validate_overlay_provenance(name, multi_id, valid_rows)

        duplicate_row = valid_rows + valid_rows.splitlines()[-1] + "\n"
        with self.assertRaisesRegex(
            REPOSITORY_VERIFIER.OverlayProvenanceError,
            "repeats Rule ID TEST-002",
        ):
            REPOSITORY_VERIFIER.validate_overlay_provenance(name, valid_body, duplicate_row)

        missing_and_excess = valid_rows.replace("TEST-002", "TEST-003")
        with self.assertRaisesRegex(
            REPOSITORY_VERIFIER.OverlayProvenanceError,
            "missing=\\['TEST-002'\\], excess=\\['TEST-003'\\]",
        ):
            REPOSITORY_VERIFIER.validate_overlay_provenance(name, valid_body, missing_and_excess)
    def test_paths_are_normalized_and_repository_escape_is_rejected(self) -> None:
        card = copy.deepcopy(self.by_id["explicit-local-never-merges-pr-files"]["card"])
        card["local_changes"]["staged"] = ["src\\normalized.ts"]
        result = SELECTOR.select_scope(card)
        self.assertEqual(result["target"]["staged"], ["src/normalized.ts"])
        card["local_changes"]["staged"] = ["../outside.ts"]
        with self.assertRaisesRegex(SELECTOR.ScopeError, "must stay within the repository"):
            SELECTOR.select_scope(card)

    def test_normalized_manifest_and_import_key_collisions_are_rejected(self) -> None:
        base = copy.deepcopy(self.by_id["unique-branch-pr"]["card"])
        for field in ("manifests", "before_manifests"):
            for duplicate_path in ("./package.json", ".\\package.json"):
                with self.subTest(field=field, manifest_path=duplicate_path):
                    card = copy.deepcopy(base)
                    card[field] = [
                        {"path": "package.json", "dependencies": ["next"]},
                        {"path": duplicate_path, "dependencies": ["react-native"]},
                    ]
                    with self.assertRaisesRegex(
                        SELECTOR.ScopeError,
                        f"{field} contains duplicate normalized path: package.json",
                    ):
                        SELECTOR.select_scope(card)

        for field in ("imports", "before_imports"):
            for duplicate_key in ("./src/server.ts", "src\\server.ts"):
                with self.subTest(field=field, import_key=duplicate_key):
                    card = copy.deepcopy(base)
                    card[field] = {
                        "src/server.ts": ["next"],
                        duplicate_key: ["react-native"],
                    }
                    with self.assertRaisesRegex(
                        SELECTOR.ScopeError,
                        f"{field} contains duplicate normalized key: src/server.ts",
                    ):
                        SELECTOR.select_scope(card)

    def test_large_card_selection_remains_bounded_and_linear_enough(self) -> None:
        changed_files = [f"src/changed-{index:04d}.ts" for index in range(1000)]
        workspace_files = changed_files + [
            f"src/generated/file-{index:04d}.ts" for index in range(4000)
        ]
        card = copy.deepcopy(self.by_id["explicit-local-never-merges-pr-files"]["card"])
        card["local_changes"] = {
            "staged": changed_files,
            "unstaged": [],
            "untracked": [],
        }
        card["workspace_files"] = ["package.json", *workspace_files]
        card["manifests"] = [
            {"path": "package.json", "dependencies": ["react", "react-dom"]}
        ]
        card["imports"] = {}

        started = time.perf_counter()
        result = SELECTOR.select_scope(card)
        elapsed = time.perf_counter() - started
        print(f"large-card selector elapsed={elapsed:.4f}s files=5001 changed=1000")
        self.assertEqual(
            result["overlays"],
            ["javascript-typescript", "react-nextjs"],
        )
        self.assertLess(elapsed, 1.5)

    def test_card_schema_and_duplicate_json_keys_are_closed(self) -> None:
        card = copy.deepcopy(self.by_id["unique-branch-pr"]["card"])
        card["unknown"] = True
        with self.assertRaisesRegex(SELECTOR.ScopeError, "scope card has unknown fields"):
            SELECTOR.select_scope(card)
        with self.assertRaisesRegex(SELECTOR.ScopeError, "duplicate JSON key: git"):
            SELECTOR.parse_json('{"git": {}, "git": {}}')

    def test_cli_replay_works_from_an_unrelated_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, str(SCRIPT_PATH), "--replay", str(REPLAY_PATH)],
                cwd=directory,
                text=True,
                capture_output=True,
                check=False,
                timeout=10,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("20 cases", result.stdout)


if __name__ == "__main__":
    unittest.main()
