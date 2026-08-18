from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SKILL_SOURCE = REPOSITORY_ROOT / "skills/implementation-quality-governance"
VERIFIER_PATH = REPOSITORY_ROOT / "scripts/verify_repository.py"
SPEC = importlib.util.spec_from_file_location("agent_workbench_repository_verifier", VERIFIER_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load verify_repository.py")
VERIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFIER)


class ImplementationQualityGovernanceVerifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory(prefix="awb-governance-verifier-")
        self.addCleanup(self.temporary_directory.cleanup)
        self.fixture_root = Path(self.temporary_directory.name)
        self.previous_root = VERIFIER.ROOT
        self.addCleanup(setattr, VERIFIER, "ROOT", self.previous_root)
        self.previous_digests = VERIFIER.GOVERNANCE_ARTIFACT_DIGESTS
        self.addCleanup(setattr, VERIFIER, "GOVERNANCE_ARTIFACT_DIGESTS", self.previous_digests)

    def create_valid_skill(self) -> Path:
        skill_root = self.fixture_root / "skills/implementation-quality-governance"
        skill_root.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(SKILL_SOURCE, skill_root)
        # A read-only export intentionally preserves source modes.  Normalize
        # this disposable fixture so each mutation test can write only inside
        # its own temporary tree without weakening the export under test.
        for directory, directory_names, file_names in os.walk(skill_root, topdown=False, followlinks=False):
            for name in (*directory_names, *file_names):
                path = Path(directory) / name
                if path.is_symlink():
                    continue
                path.chmod(0o755 if path.is_dir() else 0o644)
        skill_root.chmod(0o755)
        VERIFIER.ROOT = self.fixture_root
        return skill_root

    def create_valid_manifest_fixture(self) -> None:
        for relative_path in (
            ".codex-plugin/plugin.json",
            ".claude-plugin/plugin.json",
            ".claude-plugin/marketplace.json",
            ".agents/plugins/marketplace.json",
        ):
            source = REPOSITORY_ROOT / relative_path
            destination = self.fixture_root / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            destination.chmod(0o644)
        VERIFIER.ROOT = self.fixture_root

    def create_valid_planner_lifecycle_fixture(self) -> None:
        for relative_path in (
            "skills/orchestrate-task/SKILL.md",
            "skills/orchestrate-task/references/portable-contract.md",
            "skills/orchestrate-task/references/model-selection.md",
            "adapters/codex/.codex/agents/awb-planner.toml",
            "agents/awb-planner.md",
        ):
            source = REPOSITORY_ROOT / relative_path
            destination = self.fixture_root / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            destination.chmod(0o644)
        VERIFIER.ROOT = self.fixture_root

    def manifest_data(self, relative_path: str) -> dict[str, object]:
        return json.loads((self.fixture_root / relative_path).read_text(encoding="utf-8"))

    def write_manifest_data(self, relative_path: str, data: dict[str, object]) -> None:
        (self.fixture_root / relative_path).write_text(
            json.dumps(data, indent=2) + "\n", encoding="utf-8"
        )

    def assert_manifests_fail(self, expected_message: str) -> None:
        diagnostics = io.StringIO()
        with contextlib.redirect_stderr(diagnostics), self.assertRaises(SystemExit) as raised:
            VERIFIER.check_manifests()
        self.assertEqual(raised.exception.code, 1)
        self.assertIn(expected_message, diagnostics.getvalue())

    def assert_validation_fails(self, expected_message: str) -> None:
        diagnostics = io.StringIO()
        with contextlib.redirect_stderr(diagnostics), self.assertRaises(SystemExit) as raised:
            VERIFIER.check_implementation_quality_governance_skill()
        self.assertEqual(raised.exception.code, 1)
        self.assertIn(expected_message, diagnostics.getvalue())

    def replace_once(self, path: Path, old: str, new: str) -> None:
        contents = path.read_text(encoding="utf-8")
        self.assertIn(old, contents)
        path.write_text(contents.replace(old, new, 1), encoding="utf-8")

    def replace_description(self, skill_root: Path, value: str) -> None:
        path = skill_root / "SKILL.md"
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        for index, line in enumerate(lines):
            if line.startswith("description: "):
                lines[index] = f"description: {value}\n"
                path.write_text("".join(lines), encoding="utf-8")
                return
        self.fail("fixture SKILL.md has no description field")

    def allow_fixture_content_variation(self) -> None:
        skill_root = self.fixture_root / "skills/implementation-quality-governance"
        VERIFIER.GOVERNANCE_ARTIFACT_DIGESTS = {
            relative_path: hashlib.sha256((skill_root / relative_path).read_bytes()).hexdigest()
            for relative_path in VERIFIER.GOVERNANCE_ARTIFACT_PATHS
        }

    def symlink_or_skip(self, target: Path, link: Path, *, directory: bool) -> None:
        try:
            link.symlink_to(target, target_is_directory=directory)
        except (NotImplementedError, OSError) as error:
            self.skipTest(f"symlinks are unavailable on this platform: {error}")

    def test_valid_package_passes(self) -> None:
        self.create_valid_skill()
        VERIFIER.check_implementation_quality_governance_skill()

    def test_root_symlink_is_rejected_before_traversal(self) -> None:
        skill_root = self.create_valid_skill()
        external_skill = self.fixture_root / "external-skill"
        shutil.copytree(skill_root, external_skill)
        shutil.rmtree(skill_root)
        self.symlink_or_skip(external_skill, skill_root, directory=True)
        self.assert_validation_fails("skill root must not be a symlink")

    def test_nested_directory_symlink_is_rejected(self) -> None:
        skill_root = self.create_valid_skill()
        agents = skill_root / "agents"
        external_agents = self.fixture_root / "external-agents"
        shutil.copytree(agents, external_agents)
        shutil.rmtree(agents)
        self.symlink_or_skip(external_agents, agents, directory=True)
        self.assert_validation_fails("inventory is incorrect")

    def test_nested_file_symlink_is_rejected(self) -> None:
        skill_root = self.create_valid_skill()
        skill_file = skill_root / "SKILL.md"
        external_file = self.fixture_root / "external-skill.md"
        shutil.copy2(skill_file, external_file)
        skill_file.unlink()
        self.symlink_or_skip(external_file, skill_file, directory=False)
        self.assert_validation_fails("must contain only regular required files")

    def test_malformed_frontmatter_yaml_is_rejected(self) -> None:
        source_description = (
            "description: Mandatory quality governance for every implementation, bug fix, refactor, migration, "
            "API, UI, backend, database, infrastructure, dependency, test, security, performance, production "
            "configuration, CI/CD, deployment, release, or other production-facing or operational change, including "
            "authorized operations without a source edit. Require the smallest safe change in the correct architectural "
            "owner; apply risk-proportionate security, accessibility, privacy, data-integrity, dependency, performance, "
            "testing, rollout, documentation, and final-evidence gates."
        )
        cases = (
            ("reviewer-unterminated-flow", "description: [unterminated", "unambiguous plain string"),
            ("unterminated-double", 'description: "unterminated', "invalid double-quoted string"),
            ("unterminated-single", "description: 'unterminated", "unterminated single-quoted string"),
            ("flow-collection", "description: [value]", "unambiguous plain string"),
            ("implicit-boolean", "description: true", "unambiguous plain string"),
            (
                "duplicate-key",
                f"{source_description}\ndescription: duplicate",
                "invalid frontmatter field",
            ),
            (
                "continuation",
                f"{source_description}\n  continuation: invalid",
                "unsupported frontmatter indentation, comment, or continuation",
            ),
        )
        for name, replacement, diagnostic in cases:
            with self.subTest(case=name):
                skill_root = self.create_valid_skill()
                self.replace_once(skill_root / "SKILL.md", source_description, replacement)
                self.assert_validation_fails(diagnostic)
                shutil.rmtree(skill_root)

    def test_malformed_openai_yaml_is_rejected(self) -> None:
        display_name = '  display_name: "Implementation Quality Governance"'
        cases = (
            ("reviewer-invalid-escape", display_name, r'  display_name: "bad\q"', "invalid double-quoted string"),
            ("unterminated-double", display_name, '  display_name: "unterminated', "invalid double-quoted string"),
            ("unterminated-single", display_name, "  display_name: 'unterminated", "unterminated single-quoted string"),
            ("flow-collection", display_name, "  display_name: [value]", "must be a quoted string"),
            ("bad-indentation", display_name, '   display_name: "Implementation Quality Governance"', "unsupported metadata indentation"),
            ("continuation", display_name, display_name + "\n    continuation", "unsupported metadata indentation"),
            ("duplicate-key", display_name, display_name + "\n" + display_name, "invalid interface metadata"),
            ("unknown-key", display_name, display_name + '\n  unexpected: "value"', "invalid interface metadata"),
            ("invalid-boolean", "  allow_implicit_invocation: true", "  allow_implicit_invocation: yes", "must be exactly true"),
        )
        for name, old, replacement, diagnostic in cases:
            with self.subTest(case=name):
                skill_root = self.create_valid_skill()
                self.replace_once(skill_root / "agents/openai.yaml", old, replacement)
                self.assert_validation_fails(diagnostic)
                shutil.rmtree(skill_root)

    def test_unquoted_yaml_dates_and_timestamps_are_rejected(self) -> None:
        for value in ("2026-08-11", "2026-08-11T12:34:56", "2026-08-11 12:34:56+08:00", "2026-08-11t12:34:56.123Z"):
            with self.subTest(value=value):
                skill_root = self.create_valid_skill()
                self.replace_description(skill_root, value)
                self.assert_validation_fails("unambiguous plain string")
                shutil.rmtree(skill_root)

    def test_quoted_yaml_dates_and_timestamps_are_accepted(self) -> None:
        for value in ('"2026-08-11"', "'2026-08-11 12:34:56+08:00'"):
            with self.subTest(value=value):
                skill_root = self.create_valid_skill()
                self.replace_description(skill_root, value)
                artifact = VERIFIER.read_governance_artifact(skill_root / "SKILL.md", skill_root)
                frontmatter, _ = VERIFIER.parse_implementation_quality_governance_frontmatter(artifact)
                self.assertEqual(frontmatter["description"], value[1:-1])
                shutil.rmtree(skill_root)

    def test_unquoted_implicit_scalar_corpus_is_rejected(self) -> None:
        for value in ("true", "null", "yes", "on", "0x1f", "0b101", "1_000", "1.", "2026-08-11"):
            with self.subTest(value=value):
                skill_root = self.create_valid_skill()
                self.replace_description(skill_root, value)
                self.assert_validation_fails("unambiguous plain string")
                shutil.rmtree(skill_root)

    def test_quoted_numeric_like_scalars_are_accepted(self) -> None:
        for value in ('"0x1f"', "'0b101'", '"1_000"', "'1.'"):
            with self.subTest(value=value):
                skill_root = self.create_valid_skill()
                self.replace_description(skill_root, value)
                artifact = VERIFIER.read_governance_artifact(skill_root / "SKILL.md", skill_root)
                frontmatter, _ = VERIFIER.parse_implementation_quality_governance_frontmatter(artifact)
                self.assertEqual(frontmatter["description"], value[1:-1])
                shutil.rmtree(skill_root)

    def test_forbidden_yaml_scalar_characters_are_rejected(self) -> None:
        for character in ("\x00", "\x7f", "\x80", "\u0084", "\u009f", "\ufffe", "\uffff"):
            with self.subTest(plain_code_point=f"U+{ord(character):04X}"):
                skill_root = self.create_valid_skill()
                self.replace_description(skill_root, "Valid" + character)
                self.assert_validation_fails(f"U+{ord(character):04X}")
                shutil.rmtree(skill_root)

        display_name = '  display_name: "Implementation Quality Governance"'
        for value, code_point in (
            ('  display_name: "bad\\u0000"', "U+0000"),
            ('  display_name: "bad\\ud800"', "U+D800"),
            (f'  display_name: "bad{chr(0x7F)}"', "U+007F"),
            (f'  display_name: "bad{chr(0xFFFE)}"', "U+FFFE"),
        ):
            with self.subTest(quoted_code_point=code_point):
                skill_root = self.create_valid_skill()
                self.replace_once(skill_root / "agents/openai.yaml", display_name, value)
                self.assert_validation_fails(code_point)
                shutil.rmtree(skill_root)

    def test_required_inventory_fails_when_focused_suite_is_absent(self) -> None:
        focused_suite = "tests/test_implementation_quality_governance_verifier.py"
        self.assertIn(focused_suite, VERIFIER.REQUIRED_FILES)
        for item in VERIFIER.REQUIRED_FILES:
            if item == focused_suite:
                continue
            path = self.fixture_root / item
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture\n", encoding="utf-8")
        VERIFIER.ROOT = self.fixture_root
        diagnostics = io.StringIO()
        with contextlib.redirect_stderr(diagnostics), self.assertRaises(SystemExit) as raised:
            VERIFIER.check_required_files()
        self.assertEqual(raised.exception.code, 1)
        self.assertIn(f"missing required file: {focused_suite}", diagnostics.getvalue())

    def test_hollow_body_and_required_references_are_rejected(self) -> None:
        cases = (
            ("empty-body", "SKILL.md", "body must be nonempty"),
            ("missing-core-section", "SKILL.md", "missing a required core invariant"),
            ("missing-reference-link", "SKILL.md", "link each required reference exactly once"),
            ("empty-reference", "references/runtime-and-delivery.md", "must be nonempty"),
            ("wrong-reference-heading", "references/runtime-and-delivery.md", "expected heading"),
        )
        for name, relative_path, diagnostic in cases:
            with self.subTest(case=name):
                skill_root = self.create_valid_skill()
                path = skill_root / relative_path
                if name == "empty-body":
                    text = path.read_text(encoding="utf-8")
                    path.write_text(text.split("\n---\n", 1)[0] + "\n---\n", encoding="utf-8")
                elif name == "missing-core-section":
                    self.replace_once(path, "## Risk And Evidence", "## Risk")
                elif name == "missing-reference-link":
                    self.replace_once(path, "references/runtime-and-delivery.md", "references/missing.md")
                elif name == "empty-reference":
                    path.write_text("", encoding="utf-8")
                else:
                    path.write_text("# Wrong Heading\n", encoding="utf-8")
                self.assert_validation_fails(diagnostic)
                shutil.rmtree(skill_root)

    def test_required_reference_targets_must_be_exact(self) -> None:
        target = "references/runtime-and-delivery.md"
        for suffix in ("#part", "#", "?query", "./runtime-and-delivery.md", "%2Eruntime-and-delivery.md"):
            with self.subTest(suffix=suffix):
                skill_root = self.create_valid_skill()
                self.replace_once(skill_root / "SKILL.md", target, target + suffix)
                self.assert_validation_fails("link each required reference exactly once")
                shutil.rmtree(skill_root)

    def test_required_reference_angle_targets_are_structural(self) -> None:
        target = "references/runtime-and-delivery.md"
        skill_root = self.create_valid_skill()
        self.replace_once(skill_root / "SKILL.md", target, f"<{target}>")
        self.allow_fixture_content_variation()
        VERIFIER.check_implementation_quality_governance_skill()
        shutil.rmtree(skill_root)

        for replacement in (f"<<{target}>>", f"<{target}", f"{target}>", f"ref<{target}", "<>"):
            with self.subTest(replacement=replacement):
                skill_root = self.create_valid_skill()
                self.replace_once(skill_root / "SKILL.md", target, replacement)
                self.assert_validation_fails("link each required reference exactly once")
                shutil.rmtree(skill_root)

    def test_canonical_markdown_scanner_delimiters_and_escape_parity(self) -> None:
        target = "references/runtime-and-delivery.md"
        canonical = f"[runtime]({target})"

        def targets(text: str) -> list[str]:
            return [target for target, _ in VERIFIER.canonical_markdown_links(text)]

        self.assertEqual(targets(canonical), [target])

        for name, text in (
            ("backtick-fence", f"```\n{canonical}\n```"),
            ("tilde-fence", f"~~~~\n{canonical}\n~~~~"),
            ("three-space-fence", f"   ~~~\n{canonical}\n   ~~~"),
            ("short-fence-closer", f"````\n{canonical}\n```\n{canonical}"),
            ("nonmatching-fence-closer", f"~~~\n{canonical}\n```\n{canonical}"),
            ("fence-closer-with-text", f"```\n{canonical}\n``` text\n{canonical}"),
            ("unclosed-tilde-fence", f"~~~\n{canonical}"),
            ("single-inline", f"`{canonical}`"),
            ("double-inline-cross-line", f"``start\n{canonical}\nend``"),
            ("triple-inline", f"text ```{canonical}``` tail"),
            ("unclosed-inline", f"``start\n{canonical}"),
            ("comment", f"<!-- {canonical} -->"),
            ("image", f"!{canonical}"),
            ("odd-link-escape", rf"\{canonical}"),
            ("three-link-escapes", rf"\\\{canonical}"),
            ("even-image-escape", rf"\\!{canonical}"),
            ("four-image-escapes", rf"\\\\!{canonical}"),
            ("even-comment-escape", rf"\\<!-- {canonical} -->"),
            ("four-comment-escapes", rf"\\\\<!-- {canonical} -->"),
        ):
            with self.subTest(case=name):
                self.assertEqual(targets(text), [])

        for name, text in (
            ("four-space-not-fence", f"    ```\n{canonical}"),
            ("even-link-escape", rf"\\{canonical}"),
            ("four-link-escapes", rf"\\\\{canonical}"),
            ("odd-image-escape", rf"\!{canonical}"),
            ("three-image-escapes", rf"\\\!{canonical}"),
            ("odd-comment-escape", rf"\<!-- {canonical} -->"),
            ("three-comment-escapes", rf"\\\<!-- {canonical} -->"),
        ):
            with self.subTest(case=name):
                self.assertEqual(targets(text), [target])

    def test_canonical_markdown_scanner_suppresses_tab_indented_code(self) -> None:
        target = "references/runtime-and-delivery.md"
        canonical = f"[runtime]({target})"

        def targets(text: str) -> list[str]:
            return [value for value, _ in VERIFIER.canonical_markdown_links(text)]

        for name, text in (
            ("top-level-tab", f"\t{canonical}"),
            ("one-space-tab", f" \t{canonical}"),
            ("three-space-tab", f"   \t{canonical}"),
            ("multiple-tabs", f"\t\t{canonical}"),
            ("list-continuation-tab", f"- item\n\t{canonical}"),
            ("list-continuation-space-tab", f"- item\n \t{canonical}"),
        ):
            with self.subTest(case=name):
                self.assertEqual(targets(text), [])

        self.assertEqual(targets(f"   {canonical}"), [target])

    def test_public_metadata_requires_all_codex_description_capabilities(self) -> None:
        replacements = {
            "orchestration": "Evidence-backed agent loop discovery and implementation quality governance.",
            "loop discovery": "Portable task orchestration and implementation quality governance.",
            "governance and quality": "Portable task orchestration and evidence-backed agent loop discovery.",
        }
        for field_path in (
            ("description",),
            ("interface", "shortDescription"),
            ("interface", "longDescription"),
        ):
            for capability, replacement in replacements.items():
                with self.subTest(field=field_path, capability=capability):
                    self.create_valid_manifest_fixture()
                    manifest = self.manifest_data(".codex-plugin/plugin.json")
                    target: object = manifest
                    for key in field_path[:-1]:
                        target = target[key]
                    target[field_path[-1]] = replacement
                    self.write_manifest_data(".codex-plugin/plugin.json", manifest)
                    label = (
                        "Codex manifest description"
                        if field_path == ("description",)
                        else f"Codex interface.{field_path[-1]}"
                    )
                    self.assert_manifests_fail(
                        f"{label} must meaningfully cover {capability}"
                    )

    def test_codex_descriptions_reject_negation_contradiction_and_keyword_lists(self) -> None:
        mutations = (
            "No subagents. Never discover loops. Do not govern quality.",
            "Orchestrate with subagents, but never do so; discover loops, but forbid discovery; govern quality, but reject governance.",
            "Orchestration subagents discovery recurring loops governance quality.",
        )
        for field_path in (
            ("description",),
            ("interface", "shortDescription"),
            ("interface", "longDescription"),
        ):
            for replacement in mutations:
                with self.subTest(field=field_path, replacement=replacement):
                    self.create_valid_manifest_fixture()
                    manifest = self.manifest_data(".codex-plugin/plugin.json")
                    target: object = manifest
                    for key in field_path[:-1]:
                        target = target[key]
                    target[field_path[-1]] = replacement
                    self.write_manifest_data(".codex-plugin/plugin.json", manifest)
                    label = (
                        "Codex manifest description"
                        if field_path == ("description",)
                        else f"Codex interface.{field_path[-1]}"
                    )
                    self.assert_manifests_fail(
                        f"{label} must match its approved capability description"
                    )

    def test_codex_default_prompts_are_exact_distinct_named_skill_set(self) -> None:
        required_skills = (
            "$orchestrate-task",
            "$discover-loops",
            "$implementation-quality-governance",
        )
        for name, mutate, diagnostic in (
            (
                "too-few",
                lambda prompts: prompts[:2],
                "Codex manifest must have exactly three default prompts",
            ),
            (
                "duplicate",
                lambda prompts: [prompts[0], prompts[0], prompts[2]],
                "Codex default prompts must be distinct",
            ),
        ):
            with self.subTest(case=name):
                self.create_valid_manifest_fixture()
                manifest = self.manifest_data(".codex-plugin/plugin.json")
                prompts = manifest["interface"]["defaultPrompt"]
                manifest["interface"]["defaultPrompt"] = mutate(prompts)
                self.write_manifest_data(".codex-plugin/plugin.json", manifest)
                self.assert_manifests_fail(diagnostic)

        for skill_name in required_skills:
            for mutation, replacement in (
                ("removed", "Agent Workbench"),
                ("replaced", skill_name + "-replacement"),
            ):
                with self.subTest(skill=skill_name, mutation=mutation):
                    self.create_valid_manifest_fixture()
                    manifest = self.manifest_data(".codex-plugin/plugin.json")
                    manifest["interface"]["defaultPrompt"] = [
                        prompt.replace(skill_name, replacement)
                        for prompt in manifest["interface"]["defaultPrompt"]
                    ]
                    self.write_manifest_data(".codex-plugin/plugin.json", manifest)
                    self.assert_manifests_fail(
                        "Codex default prompts must contain exactly one prompt naming each required skill"
                    )

    def test_codex_default_prompts_reject_expansion_negation_and_cooccurrence(self) -> None:
        required_skills = (
            "$orchestrate-task",
            "$discover-loops",
            "$implementation-quality-governance",
        )
        for prompt_index, skill_name in enumerate(required_skills):
            mutations = (
                lambda prompt: prompt + " Also use $rogue-skill.",
                lambda prompt: f"Never use {skill_name}.",
                lambda prompt: f"Use {skill_name}, but do not use it.",
                lambda prompt: f"Keywords only: {skill_name} orchestration loops quality.",
            )
            for mutation in mutations:
                with self.subTest(skill=skill_name, mutation=mutation):
                    self.create_valid_manifest_fixture()
                    manifest = self.manifest_data(".codex-plugin/plugin.json")
                    prompts = manifest["interface"]["defaultPrompt"]
                    prompts[prompt_index] = mutation(prompts[prompt_index])
                    self.write_manifest_data(".codex-plugin/plugin.json", manifest)
                    self.assert_manifests_fail(
                        f"Codex {skill_name} default prompt must match its approved contract"
                    )

    def test_claude_descriptions_are_exact_and_shape_checked(self) -> None:
        surfaces = (
            (".claude-plugin/plugin.json", ("description",), "Claude manifest description"),
            (".claude-plugin/marketplace.json", ("description",), "Claude marketplace root description"),
            (".claude-plugin/marketplace.json", ("metadata", "description"), "Claude marketplace metadata.description"),
            (".claude-plugin/marketplace.json", ("plugins", 0, "description"), "Claude marketplace plugin description"),
        )
        mutations: tuple[object, ...] = (
            "Never orchestrate, discover loops, or govern quality.",
            "Portable task orchestration with extra unauthorized scope.",
            7,
        )
        for relative_path, field_path, label in surfaces:
            for mutation in mutations:
                with self.subTest(surface=label, mutation=mutation):
                    self.create_valid_manifest_fixture()
                    data = self.manifest_data(relative_path)
                    target: object = data
                    for key in field_path[:-1]:
                        target = target[key]
                    target[field_path[-1]] = mutation
                    self.write_manifest_data(relative_path, data)
                    self.assert_manifests_fail(label)

        self.create_valid_manifest_fixture()
        marketplace = self.manifest_data(".claude-plugin/marketplace.json")
        marketplace["metadata"]["description"] = marketplace["plugins"][0]["description"]
        self.write_manifest_data(".claude-plugin/marketplace.json", marketplace)
        self.assert_manifests_fail("Claude marketplace metadata.description")

    def test_skill_and_openai_agent_metadata_match_exact_contracts(self) -> None:
        skill_root = self.create_valid_skill()
        self.replace_description(skill_root, '"Never govern quality."')
        self.allow_fixture_content_variation()
        self.assert_validation_fails("description must match its approved contract")
        shutil.rmtree(skill_root)

        skill_root = self.create_valid_skill()
        self.replace_once(
            skill_root / "agents/openai.yaml",
            'short_description: "Risk-proportionate change quality and evidence"',
            'short_description: "Risk-proportionate change quality and evidence plus extra scope"',
        )
        self.allow_fixture_content_variation()
        self.assert_validation_fails("OpenAI metadata must match its approved contract")
        shutil.rmtree(skill_root)

        for skill_name in ("orchestrate-task", "discover-loops"):
            for name, old, new in (
                ("negated-prompt", "default_prompt: ", "default_prompt: \"Never use this skill.\" # "),
                ("malformed-type", "short_description: ", "short_description: false # "),
            ):
                with self.subTest(skill=skill_name, mutation=name):
                    source = REPOSITORY_ROOT / f"skills/{skill_name}/agents/openai.yaml"
                    path = self.fixture_root / f"{skill_name}-{name}.yaml"
                    shutil.copy2(source, path)
                    path.chmod(0o644)
                    text = path.read_text(encoding="utf-8")
                    line = next(line for line in text.splitlines() if old in line)
                    path.write_text(text.replace(line, "  " + new + line.split(old, 1)[1], 1), encoding="utf-8")
                    VERIFIER.ROOT = self.fixture_root
                    diagnostics = io.StringIO()
                    with contextlib.redirect_stderr(diagnostics), self.assertRaises(SystemExit):
                        VERIFIER.check_public_openai_agent_contract(path, skill_name)
                    self.assertIn("OpenAI", diagnostics.getvalue())

    def test_public_metadata_requires_governance_capability(self) -> None:
        cases = (
            (
                ".claude-plugin/plugin.json",
                "keywords",
                "Claude manifest must include loop-discovery, agent-loop, pr-evidence, and quality-governance keywords",
            ),
            (
                ".claude-plugin/marketplace.json",
                "description",
                "Claude marketplace root description must match its approved contract",
            ),
            (
                ".claude-plugin/marketplace.json",
                "tags",
                "Claude marketplace tags must include loop-discovery, agent-loop, pr-evidence, and quality-governance",
            ),
        )
        for relative_path, mutation, diagnostic in cases:
            with self.subTest(path=relative_path, mutation=mutation):
                self.create_valid_manifest_fixture()
                manifest = self.manifest_data(relative_path)
                if mutation == "description":
                    if relative_path.endswith("marketplace.json"):
                        manifest["description"] = "Portable workflows: orchestrate-task and discover-loops."
                        manifest["metadata"]["description"] = manifest["description"]
                    else:
                        manifest["description"] = "Portable task orchestration and agent loop discovery."
                elif mutation == "keywords":
                    manifest["keywords"] = [value for value in manifest["keywords"] if value != "quality-governance"]
                elif mutation == "tags":
                    manifest["plugins"][0]["tags"] = [
                        value for value in manifest["plugins"][0]["tags"] if value != "quality-governance"
                    ]
                self.write_manifest_data(relative_path, manifest)
                self.assert_manifests_fail(diagnostic)

    def test_public_metadata_type_checks_fail_closed(self) -> None:
        cases = (
            (".codex-plugin/plugin.json", ("description",), None, "Codex manifest description must be a non-empty string"),
            (".claude-plugin/plugin.json", ("description",), {}, "Claude manifest description must be a non-empty string"),
            (".codex-plugin/plugin.json", ("keywords",), ["quality-governance", []], "Codex manifest keywords must be an array of strings"),
            (".claude-plugin/plugin.json", ("keywords",), ["quality-governance", 1], "Claude manifest keywords must be an array of strings"),
            (".codex-plugin/plugin.json", ("interface", "shortDescription"), 1, "Codex interface.shortDescription must be a non-empty string"),
            (".codex-plugin/plugin.json", ("interface", "longDescription"), {}, "Codex interface.longDescription must be a non-empty string"),
            (".codex-plugin/plugin.json", ("interface", "defaultPrompt"), "prompt", "Codex default prompts must be an array of strings"),
            (".codex-plugin/plugin.json", ("interface", "defaultPrompt"), ["valid", None], "Codex default prompts must be an array of strings"),
            (".codex-plugin/plugin.json", ("interface", "defaultPrompt"), ["valid", [], "valid"], "Codex default prompts must be an array of strings"),
            (".claude-plugin/marketplace.json", ("description",), None, "Claude marketplace root description must be a non-empty string"),
            (".claude-plugin/marketplace.json", ("metadata", "description"), 3, "Claude marketplace metadata.description must be a non-empty string"),
            (".claude-plugin/marketplace.json", ("plugins", 0, "description"), {}, "Claude marketplace plugin description must be a non-empty string"),
            (".claude-plugin/marketplace.json", ("plugins", 0, "keywords"), ["quality-governance", []], "Claude marketplace keywords must be an array of strings"),
            (".claude-plugin/marketplace.json", ("plugins", 0, "tags"), ["quality-governance", False], "Claude marketplace tags must be an array of strings"),
        )
        for relative_path, path, value, diagnostic in cases:
            with self.subTest(path=relative_path, field=path):
                self.create_valid_manifest_fixture()
                manifest = self.manifest_data(relative_path)
                target: object = manifest
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value
                self.write_manifest_data(relative_path, manifest)
                self.assert_manifests_fail(diagnostic)

    def test_governance_required_links_only_count_in_top_level_tables(self) -> None:
        target = "references/runtime-and-delivery.md"
        canonical = f"[runtime]({target})"
        top_level_table = f"| Change or concern | Read |\n| --- | --- |\n| Runtime | {canonical} |"
        self.assertEqual(VERIFIER.governance_table_links(top_level_table), [(target, 3)])

        for name, text in (
            ("unordered-child-parent-dedent", f"- parent\n  - child\n    text\n  | Rule | {canonical} |"),
            ("ordered-child-parent-dedent", f"1. parent\n   1. child\n      text\n   | Rule | {canonical} |"),
            ("multiple-nesting", f"- parent\n  - child\n    - grandchild\n      | Rule | {canonical} |"),
            ("lazy-continuation", f"- parent\n| Change or concern | Read |\n| --- | --- |\n| Runtime | {canonical} |"),
            ("blockquote-list", f"> - parent\n> | Change or concern | Read |\n> | --- | --- |\n> | Runtime | {canonical} |"),
            ("indented-lookalike", f"  | Change or concern | Read |\n  | --- | --- |\n  | Runtime | {canonical} |"),
            ("fenced-lookalike", f"```\n{top_level_table}\n```"),
            ("comment-lookalike", f"<!--\n{top_level_table}\n-->"),
        ):
            with self.subTest(case=name):
                self.assertEqual(VERIFIER.governance_table_links(text), [])

    def test_moving_required_table_link_into_a_container_fails(self) -> None:
        target = "references/runtime-and-delivery.md"
        source_line = f"| Production runtime, reliability, performance, observability, infrastructure, CI/CD, deployment, release, or real rollout | [runtime and delivery]({target}) |"
        for prefix in ("> ", "- ", "1. ", "  "):
            with self.subTest(prefix=prefix):
                skill_root = self.create_valid_skill()
                self.replace_once(skill_root / "SKILL.md", source_line, prefix + source_line)
                self.allow_fixture_content_variation()
                self.assert_validation_fails("link each required reference exactly once")
                shutil.rmtree(skill_root)

    def test_governance_table_schema_only_reads_visible_second_cells(self) -> None:
        target = "references/runtime-and-delivery.md"
        canonical = f"[runtime]({target})"
        header = "| Change or concern | Read |\n| --- | --- |"

        def links(row: str, *, heading: str = header) -> list[tuple[str, int]]:
            return VERIFIER.governance_table_links(f"{heading}\n{row}")

        self.assertEqual(links(f"| Runtime | {canonical} |"), [(target, 3)])
        self.assertEqual(links(f"| {canonical} | plain text |"), [])
        self.assertEqual(links(f"| Runtime | plain text | {canonical} |"), [])
        self.assertEqual(links(f"| Runtime | {canonical} | ignored |"), [])
        self.assertEqual(links("| Runtime |"), [])
        self.assertEqual(links(f"| Runtime | {canonical} {canonical} |"), [(target, 3), (target, 3)])
        self.assertEqual(links(f"| Runtime \\| detail | {canonical} |"), [(target, 3)])
        self.assertEqual(links(f"| Runtime \\\\| detail | {canonical} |"), [])
        self.assertEqual(links(f"| Runtime | `{canonical}` |"), [])
        self.assertEqual(links(f"| Runtime | {canonical} |", heading="| Change Or Concern | Read |\n| --- | --- |"), [])
        self.assertEqual(links(f"| Runtime | {canonical} |", heading="| Change or concern | Read |\n| -- | --- |"), [])

        current_links = VERIFIER.governance_table_links(
            (SKILL_SOURCE / "SKILL.md").read_text(encoding="utf-8")
        )
        self.assertEqual(len(current_links), 5)

    def test_excess_table_cells_cannot_satisfy_required_link_checks(self) -> None:
        target = "references/runtime-and-delivery.md"
        source_line = f"| Production runtime, reliability, performance, observability, infrastructure, CI/CD, deployment, release, or real rollout | [runtime and delivery]({target}) |"
        skill_root = self.create_valid_skill()
        self.replace_once(
            skill_root / "SKILL.md",
            source_line,
            f"| Production runtime | ignored | [runtime and delivery]({target}) |",
        )
        self.allow_fixture_content_variation()
        self.assert_validation_fails("link each required reference exactly once")
        shutil.rmtree(skill_root)

    def test_raw_html_blocks_cannot_satisfy_required_table_links(self) -> None:
        target = "references/runtime-and-delivery.md"
        canonical = f"[runtime]({target})"
        table = f"| Change or concern | Read |\n| --- | --- |\n| Runtime | {canonical} |"
        for name, text in (
            ("div", f"<div class=\"raw\">\n{table}\n</div>"),
            ("pre", f"<pre>\n{table}\n</pre>"),
            ("script", f"<SCRIPT type=text/plain>\n{table}\n</ScRiPt>"),
            ("details", f"<details open>\n{table}\n</details>"),
            ("style", f"<style>\n{table}\n</style>"),
            ("textarea", f"<textarea>\n{table}\n</textarea>"),
            ("table", f"<table>\n{table}\n</table>"),
            ("blockquote", f"<blockquote>\n{table}\n</blockquote>"),
            ("nested-div", f"<div>\n<div>\n{table}\n</div>\n{table}\n</div>"),
            ("comment", f"<!--\n{table}\n-->"),
            ("processing", f"<?instruction\n{table}\n?>"),
            ("declaration", f"<!DOCTYPE html\n{table}\n>"),
            ("cdata", f"<![CDATA[\n{table}\n]]>"),
        ):
            with self.subTest(case=name):
                self.assertEqual(VERIFIER.governance_table_links(text), [])

        self.assertEqual(
            VERIFIER.governance_table_links(f"<div>\n{table}\n</div>\n\n{table}"),
            [(target, 9)],
        )

    def test_raw_html_table_move_fails_required_link_checks(self) -> None:
        target = "references/runtime-and-delivery.md"
        source_line = f"| Production runtime, reliability, performance, observability, infrastructure, CI/CD, deployment, release, or real rollout | [runtime and delivery]({target}) |"
        skill_root = self.create_valid_skill()
        self.replace_once(skill_root / "SKILL.md", source_line, f"<div>\n{source_line}\n</div>")
        self.allow_fixture_content_variation()
        self.assert_validation_fails("contains possible raw HTML at line")
        shutil.rmtree(skill_root)

    def test_raw_html_wrappers_without_closing_blank_are_rejected(self) -> None:
        target = "references/runtime-and-delivery.md"
        source_line = f"| Production runtime, reliability, performance, observability, infrastructure, CI/CD, deployment, release, or real rollout | [runtime and delivery]({target}) |"
        for tag in ("div", "summary"):
            with self.subTest(tag=tag):
                skill_root = self.create_valid_skill()
                self.replace_once(
                    skill_root / "SKILL.md",
                    source_line,
                    f"<{tag}>\ninside wrapper\n</{tag}>\n{source_line}",
                )
                self.allow_fixture_content_variation()
                self.assert_validation_fails("contains possible raw HTML at line")
                shutil.rmtree(skill_root)

    def test_raw_html_candidate_forms_are_rejected(self) -> None:
        candidates = (
            ("standard-open", "<div>"),
            ("custom-open", '<quality-panel data-mode="strict">'),
            ("type-7", "<span>"),
            ("closing-only", "</DIV>"),
            ("incomplete-open", '<DiV class="raw"'),
            ("incomplete-custom-close", "</quality-panel"),
            ("mixed-case-attribute-unclosed", '<SuMmArY DATA-state="open"'),
            ("comment", "<!-- unclosed"),
            ("processing-instruction", "<?target unclosed"),
            ("declaration", "<!DoCtYpE html"),
            ("cdata", "<![cDaTa[ unclosed"),
            ("bare-incomplete-declaration", "<!"),
            ("incomplete-comment", "<!-"),
            ("incomplete-cdata", "<!["),
        )
        for name, candidate in candidates:
            with self.subTest(case=name):
                skill_root = self.create_valid_skill()
                path = skill_root / "references/runtime-and-delivery.md"
                path.write_text(
                    path.read_text(encoding="utf-8") + f"\n   {candidate}\n",
                    encoding="utf-8",
                )
                self.allow_fixture_content_variation()
                self.assert_validation_fails("contains possible raw HTML at line")
                shutil.rmtree(skill_root)

    def test_inline_raw_html_candidate_forms_are_rejected(self) -> None:
        marker = "TEST_SECRET_INLINE_RAW_HTML_1937"
        candidates = (
            ("prose-open", f"ordinary prose <span data-secret={marker}>inside"),
            ("prose-close", f"ordinary prose </SPAN data-secret={marker}>"),
            ("custom", f"ordinary prose <quality-panel data-secret={marker}>"),
            ("table", f"| concern | text <div data-secret={marker}> |"),
            ("list", f"- ordinary prose <span data-secret={marker}>"),
            ("blockquote", f"> ordinary prose <span data-secret={marker}>"),
            ("comment", f"ordinary prose <!-- {marker}"),
            ("processing", f"ordinary prose <?target {marker}"),
            ("declaration", f"ordinary prose <!DOCTYPE {marker}"),
            ("cdata", f"ordinary prose <![CDATA[ {marker}"),
            ("incomplete", f"ordinary prose <! {marker}"),
            ("unmatched-code-opener", f"ordinary ` prose <span data-secret={marker}>"),
        )
        for name, candidate in candidates:
            with self.subTest(case=name):
                skill_root = self.create_valid_skill()
                try:
                    path = skill_root / "references/runtime-and-delivery.md"
                    original = path.read_text(encoding="utf-8")
                    physical_line = len(original.splitlines()) + 1
                    path.write_text(original + candidate + "\n", encoding="utf-8")
                    self.allow_fixture_content_variation()
                    diagnostics = io.StringIO()
                    with contextlib.redirect_stderr(diagnostics), self.assertRaises(SystemExit):
                        VERIFIER.check_implementation_quality_governance_skill()
                    rendered = diagnostics.getvalue()
                    self.assertIn(
                        "skills/implementation-quality-governance/references/runtime-and-delivery.md "
                        f"contains possible raw HTML at line {physical_line}",
                        rendered,
                    )
                    self.assertNotIn(marker, rendered)
                finally:
                    shutil.rmtree(skill_root, ignore_errors=True)

    def test_inline_code_and_cross_block_raw_html_are_deliberately_rejected(self) -> None:
        marker = "TEST_SECRET_CROSS_BLOCK_HTML_9142"
        cases = (
            ("type-1", f"`<script data-secret={marker}>`", 1),
            ("type-2", f"`<!-- {marker} -->`", 1),
            ("type-3", f"`<?target {marker}?>`", 1),
            ("type-4", f"`<!DOCTYPE {marker}>`", 1),
            ("type-5", f"`<![CDATA[ {marker} ]]>`", 1),
            ("type-6", f"`<div data-secret={marker}>`", 1),
            ("type-7", f"`<span data-secret={marker}>`", 1),
            ("paragraph-crossing", f"text `\n<div data-secret={marker}>\n`", 2),
            ("atx-crossing", f"text `\n# heading\n<div data-secret={marker}>\n`", 3),
            ("setext-crossing", f"text `\nheading\n---\n<div data-secret={marker}>\n`", 4),
            ("thematic-crossing", f"text `\n---\n<div data-secret={marker}>\n`", 3),
            (
                "table-cells",
                f"| Left | Right |\n| --- | --- |\n| `text | <span data-secret={marker}> |\n| ` | end |",
                3,
            ),
            ("crlf", f"text `\r\n<div data-secret={marker}>\r\n`", 2),
            ("tab-inline", f"text\t`<span data-secret={marker}>`", 1),
            ("unmatched-variable-run", f"text ````` <span data-secret={marker}>", 1),
        )
        for name, fragment, line_offset in cases:
            with self.subTest(case=name):
                skill_root = self.create_valid_skill()
                try:
                    path = skill_root / "references/runtime-and-delivery.md"
                    original = path.read_bytes()
                    physical_line = len(original.decode("utf-8").splitlines()) + 1 + line_offset
                    path.write_bytes(original + b"\n" + fragment.encode("utf-8") + b"\n")
                    self.allow_fixture_content_variation()
                    diagnostics = io.StringIO()
                    with contextlib.redirect_stderr(diagnostics), self.assertRaises(SystemExit):
                        VERIFIER.check_implementation_quality_governance_skill()
                    rendered = diagnostics.getvalue()
                    self.assertIn(
                        "skills/implementation-quality-governance/references/runtime-and-delivery.md "
                        f"contains possible raw HTML at line {physical_line}",
                        rendered,
                    )
                    self.assertNotIn(marker, rendered)
                finally:
                    shutil.rmtree(skill_root, ignore_errors=True)

    def test_ambiguous_unicode_lines_and_whitespace_are_rejected_physically(self) -> None:
        marker = "TEST_SECRET_UNICODE_LAYOUT_6418"
        cases = (
            ("next-line", f"prose\u0085    <script data-secret={marker}>", 1),
            ("line-separator", f"prose\u2028    <script data-secret={marker}>", 1),
            ("paragraph-separator", f"prose\u2029    <script data-secret={marker}>", 1),
            ("nonbreaking-blank", f"paragraph\n\u00a0\n    <script data-secret={marker}>", 2),
            ("em-space-table", f"| concern | read |\n| --- | \u2003--- | {marker}", 2),
            ("zero-width-format", f"paragraph\u200b<script data-secret={marker}>", 1),
            ("ideographic-blank", f"paragraph\n\u3000\n    <script data-secret={marker}>", 2),
        )
        for name, fragment, line_offset in cases:
            with self.subTest(case=name):
                skill_root = self.create_valid_skill()
                try:
                    path = skill_root / "references/runtime-and-delivery.md"
                    original = path.read_text(encoding="utf-8")
                    physical_line = original.count("\n") + line_offset
                    path.write_text(original + fragment + "\n", encoding="utf-8")
                    self.allow_fixture_content_variation()
                    diagnostics = io.StringIO()
                    with contextlib.redirect_stderr(diagnostics), self.assertRaises(SystemExit):
                        VERIFIER.check_implementation_quality_governance_skill()
                    rendered = diagnostics.getvalue()
                    self.assertIn(
                        "skills/implementation-quality-governance/references/runtime-and-delivery.md "
                        f"contains ambiguous Unicode whitespace or control at line {physical_line}",
                        rendered,
                    )
                    self.assertNotIn(marker, rendered)
                finally:
                    shutil.rmtree(skill_root, ignore_errors=True)

    def test_unicode_separator_cannot_synthesize_required_table_lines(self) -> None:
        marker = "TEST_SECRET_UNICODE_TABLE_8402"
        skill_root = self.create_valid_skill()
        path = skill_root / "SKILL.md"
        original = path.read_text(encoding="utf-8")
        source = "| Change or concern | Read |\n| --- | --- |"
        physical_line = original[: original.index(source)].count("\n") + 1
        self.replace_once(
            path,
            source,
            f"| Change or concern | Read |\u2028| --- | --- | {marker}",
        )
        self.allow_fixture_content_variation()
        diagnostics = io.StringIO()
        with contextlib.redirect_stderr(diagnostics), self.assertRaises(SystemExit):
            VERIFIER.check_implementation_quality_governance_skill()
        rendered = diagnostics.getvalue()
        self.assertIn(
            "skills/implementation-quality-governance/SKILL.md contains ambiguous Unicode "
            f"whitespace or control at line {physical_line}",
            rendered,
        )
        self.assertNotIn(marker, rendered)

    def test_physical_line_splitter_accepts_only_cr_lf_and_crlf(self) -> None:
        self.assertEqual(
            VERIFIER.governance_physical_lines("one\r\ntwo\rthree\nfour"),
            ["one", "two", "three", "four"],
        )
        self.assertEqual(
            VERIFIER.governance_physical_lines("one\u2028two\u2029three\u0085four"),
            ["one\u2028two\u2029three\u0085four"],
        )
        for newline in ("\r", "\r\n"):
            with self.subTest(newline=repr(newline)):
                skill_root = self.create_valid_skill()
                try:
                    path = skill_root / "SKILL.md"
                    path.write_text(
                        path.read_text(encoding="utf-8").replace("\n", newline),
                        encoding="utf-8",
                    )
                    self.allow_fixture_content_variation()
                    VERIFIER.check_implementation_quality_governance_skill()
                finally:
                    shutil.rmtree(skill_root, ignore_errors=True)

    def test_inline_raw_html_cannot_wrap_required_table_link(self) -> None:
        marker = "TEST_SECRET_INLINE_TABLE_WRAPPER_6014"
        target = "references/runtime-and-delivery.md"
        source_line = f"| Production runtime, reliability, performance, observability, infrastructure, CI/CD, deployment, release, or real rollout | [runtime and delivery]({target}) |"
        skill_root = self.create_valid_skill()
        path = skill_root / "SKILL.md"
        original = path.read_text(encoding="utf-8")
        physical_line = original[: original.index(source_line)].count("\n") + 1
        self.replace_once(
            path,
            f"[runtime and delivery]({target})",
            f"<span data-secret={marker}>[runtime and delivery]({target})</span>",
        )
        self.allow_fixture_content_variation()
        diagnostics = io.StringIO()
        with contextlib.redirect_stderr(diagnostics), self.assertRaises(SystemExit):
            VERIFIER.check_implementation_quality_governance_skill()
        rendered = diagnostics.getvalue()
        self.assertIn(
            "skills/implementation-quality-governance/SKILL.md "
            f"contains possible raw HTML at line {physical_line}",
            rendered,
        )
        self.assertNotIn(marker, rendered)

    def test_paragraph_interruptions_cannot_create_false_code_exemptions(self) -> None:
        marker = "TEST_SECRET_PARAGRAPH_HTML_4268"
        cases = (
            ("top-level-indent", f"paragraph\n    <script data-secret={marker}>", 2),
            (
                "ordered-two-fence",
                f"paragraph\n2. ```html\n   <div data-secret={marker}>\n   ```",
                3,
            ),
            (
                "nested-list-paragraph",
                f"- outer\n  - inner\n        <script data-secret={marker}>",
                3,
            ),
            (
                "list-paragraph-indent",
                f"- paragraph\n      <script data-secret={marker}>",
                2,
            ),
        )
        for name, fragment, line_offset in cases:
            with self.subTest(case=name):
                skill_root = self.create_valid_skill()
                try:
                    path = skill_root / "references/runtime-and-delivery.md"
                    original = path.read_text(encoding="utf-8")
                    physical_line = len(original.splitlines()) + line_offset
                    path.write_text(original + fragment + "\n", encoding="utf-8")
                    self.allow_fixture_content_variation()
                    diagnostics = io.StringIO()
                    with contextlib.redirect_stderr(diagnostics), self.assertRaises(SystemExit):
                        VERIFIER.check_implementation_quality_governance_skill()
                    rendered = diagnostics.getvalue()
                    self.assertIn(
                        "skills/implementation-quality-governance/references/runtime-and-delivery.md "
                        f"contains possible raw HTML at line {physical_line}",
                        rendered,
                    )
                    self.assertNotIn(marker, rendered)
                finally:
                    shutil.rmtree(skill_root, ignore_errors=True)

    def test_governance_markdown_resource_bounds_are_sanitized(self) -> None:
        max_bytes = getattr(VERIFIER, "MAX_GOVERNANCE_ARTIFACT_BYTES", 65_536)
        max_lines = getattr(VERIFIER, "MAX_GOVERNANCE_ARTIFACT_LINES", 1_000)
        max_line = getattr(VERIFIER, "MAX_GOVERNANCE_MARKDOWN_LINE_CHARS", 4_096)
        marker = "TEST_SECRET_GOVERNANCE_BOUND_8521"
        cases = (
            ("bytes", "x" * (max_bytes + 1), "exceeds the 65536-byte limit"),
            ("lines", ("line\n" * (max_lines + 1)), "exceeds the 1000-line limit"),
            ("line", "x" * (max_line + 1), "line 1 exceeds the 4096-character limit"),
        )
        for name, contents, expected in cases:
            with self.subTest(case=name):
                skill_root = self.create_valid_skill()
                try:
                    path = skill_root / "references/runtime-and-delivery.md"
                    path.write_text(contents + marker, encoding="utf-8")
                    self.allow_fixture_content_variation()
                    diagnostics = io.StringIO()
                    with contextlib.redirect_stderr(diagnostics), self.assertRaises(SystemExit):
                        VERIFIER.check_implementation_quality_governance_skill()
                    rendered = diagnostics.getvalue()
                    self.assertIn(
                        "skills/implementation-quality-governance/references/runtime-and-delivery.md",
                        rendered,
                    )
                    self.assertIn(expected, rendered)
                    self.assertNotIn(marker, rendered)
                finally:
                    shutil.rmtree(skill_root, ignore_errors=True)

    def test_sparse_oversize_artifact_is_rejected_before_payload_read(self) -> None:
        skill_root = self.create_valid_skill()
        path = skill_root / "references/runtime-and-delivery.md"
        with path.open("wb") as handle:
            handle.seek(VERIFIER.MAX_GOVERNANCE_ARTIFACT_BYTES + 8_000_000)
            handle.write(b"x")
        with mock.patch.object(VERIFIER.os, "read", wraps=VERIFIER.os.read) as read_call:
            diagnostics = io.StringIO()
            with contextlib.redirect_stderr(diagnostics), self.assertRaises(SystemExit):
                VERIFIER.read_governance_artifact(path, skill_root)
        read_call.assert_not_called()
        self.assertIn(
            "skills/implementation-quality-governance/references/runtime-and-delivery.md "
            "exceeds the 65536-byte limit",
            diagnostics.getvalue(),
        )

    def test_governance_validation_remains_bound_to_single_snapshot(self) -> None:
        skill_root = self.create_valid_skill()
        original_loader = VERIFIER.load_governance_snapshot
        original_reader = VERIFIER.read_governance_artifact
        loads: list[str] = []
        reads: list[str] = []

        def track_read(path: Path, root: Path) -> object:
            reads.append(str(path.relative_to(root)))
            return original_reader(path, root)

        def load_then_swap(root: Path) -> object:
            snapshot = original_loader(root)
            loads.extend(snapshot)
            (root / "references/runtime-and-delivery.md").write_text(
                "<div>swapped after snapshot</div>\n", encoding="utf-8"
            )
            return snapshot

        with mock.patch.object(
            VERIFIER, "read_governance_artifact", side_effect=track_read
        ), mock.patch.object(
            VERIFIER, "load_governance_snapshot", side_effect=load_then_swap
        ):
            VERIFIER.check_implementation_quality_governance_skill()
        self.assertCountEqual(loads, VERIFIER.GOVERNANCE_ARTIFACT_PATHS)
        self.assertCountEqual(reads, VERIFIER.GOVERNANCE_ARTIFACT_PATHS)
        self.assertEqual(len(reads), len(VERIFIER.GOVERNANCE_ARTIFACT_PATHS))

    def test_full_main_never_rereads_governance_artifacts_after_snapshot(self) -> None:
        skill_root = self.create_valid_skill()
        self.create_valid_planner_lifecycle_fixture()
        original_loader = VERIFIER.load_governance_snapshot
        original_reader = VERIFIER.read_governance_artifact
        original_read_text = Path.read_text
        reads: list[str] = []
        phases: list[str] = []

        def track_read(path: Path, root: Path) -> object:
            reads.append(str(path.relative_to(root)))
            return original_reader(path, root)

        def load_then_replace(root: Path) -> object:
            self.assertEqual(
                phases,
                [
                    "routing-replay",
                    "loop-readiness-replay",
                    "pr-evidence-replay",
                    "code-review-replay",
                    "unit-tests",
                ],
            )
            phases.append("snapshot")
            snapshot = original_loader(root)
            markdown_paths = sorted(
                root / relative_path
                for relative_path in VERIFIER.GOVERNANCE_ARTIFACT_PATHS
                if relative_path.endswith(".md")
            )
            outside = self.fixture_root / "outside.md"
            outside.write_text("outside\n", encoding="utf-8")

            markdown_paths[0].write_text("<div>swapped</div>\n", encoding="utf-8")
            markdown_paths[1].unlink()
            self.symlink_or_skip(outside, markdown_paths[1], directory=False)
            markdown_paths[2].unlink()
            try:
                os.mkfifo(markdown_paths[2])
            except (AttributeError, OSError) as error:
                self.skipTest(f"FIFOs are unavailable on this platform: {error}")
            with markdown_paths[3].open("wb") as handle:
                handle.seek(VERIFIER.MAX_GOVERNANCE_ARTIFACT_BYTES + 8_000_000)
                handle.write(b"x")
            markdown_paths[4].unlink()
            markdown_paths[5].write_text("<script>swapped</script>\n", encoding="utf-8")
            return snapshot

        def guard_governance_read_text(path: Path, *args: object, **kwargs: object) -> str:
            if path == skill_root or skill_root in path.parents:
                raise AssertionError(f"governance artifact was reread: {path.name}")
            return original_read_text(path, *args, **kwargs)

        def complete_verifier_subprocess(
            command: list[str], **kwargs: object
        ) -> object:
            if command[1:4] == ["-m", "unittest", "discover"]:
                phases.append("unit-tests")
            elif command[0] == "bash" and command[1].endswith("test-upload-github-attachment.sh"):
                phases.append("pr-evidence-replay")
            elif command[1].endswith("route_subagent.py"):
                phases.append("routing-replay")
            elif command[1].endswith("score_loop_readiness.py"):
                phases.append("loop-readiness-replay")
            elif command[1].endswith("select_review_scope.py"):
                phases.append("code-review-replay")
            else:
                self.fail(f"unexpected verifier subprocess: {command!r}")
            return mock.Mock(returncode=0, stdout="ok\n", stderr="")

        mocked_checks = (
            "check_required_files",
            "check_manifests",
            "check_skill",
            "check_discover_loops_skill",
            "check_pr_evidence_skill",
            "check_code_review_skills",
            "check_codex_profiles",
            "check_claude_profiles",
            "check_release_and_ci",
        )
        patches = [mock.patch.object(VERIFIER, name) for name in mocked_checks]
        with contextlib.ExitStack() as stack:
            for patcher in patches:
                stack.enter_context(patcher)
            stack.enter_context(
                mock.patch.object(
                    VERIFIER, "read_governance_artifact", side_effect=track_read
                )
            )
            stack.enter_context(
                mock.patch.object(
                    VERIFIER, "load_governance_snapshot", side_effect=load_then_replace
                )
            )
            stack.enter_context(
                mock.patch.object(Path, "read_text", new=guard_governance_read_text)
            )
            stack.enter_context(
                mock.patch.object(
                    VERIFIER.subprocess,
                    "run",
                    side_effect=complete_verifier_subprocess,
                )
            )
            VERIFIER.main()

        self.assertEqual(
            phases,
            [
                "routing-replay",
                "loop-readiness-replay",
                "pr-evidence-replay",
                "code-review-replay",
                "unit-tests",
                "snapshot",
            ],
        )
        self.assertCountEqual(reads, VERIFIER.GOVERNANCE_ARTIFACT_PATHS)
        self.assertEqual(len(reads), len(VERIFIER.GOVERNANCE_ARTIFACT_PATHS))

    def test_snapshot_link_scan_preserves_list_fences_across_unmarked_blanks(self) -> None:
        for name, text in (
            ("list", "- ```md\n\n  [x](missing.md)\n  ```"),
            (
                "nested-list",
                "- outer\n  - ```md\n\n    [x](missing.md)\n    ```",
            ),
        ):
            with self.subTest(case=name):
                self.assertEqual(
                    VERIFIER.governance_snapshot_markdown_links(text, "artifact"),
                    [],
                )

        for name, text in (
            ("quote", "> ```md\n\n> [x](missing.md)\n> ```"),
            (
                "list-quote",
                "- > ```md\n\n  > [x](missing.md)\n  > ```",
            ),
            (
                "quote-list",
                "> - ```md\n\n>   [x](missing.md)\n>   ```",
            ),
        ):
            with self.subTest(case=name):
                self.assertEqual(
                    VERIFIER.governance_snapshot_markdown_links(text, "artifact"),
                    [("missing.md", 3)],
                )

    def test_full_main_checks_bounded_snapshot_links_in_containers(self) -> None:
        self.create_valid_planner_lifecycle_fixture()
        mocked_checks = (
            "check_required_files", "check_manifests", "check_skill",
            "check_discover_loops_skill", "check_pr_evidence_skill",
            "check_code_review_skills", "check_codex_profiles",
            "check_claude_profiles", "check_replays_and_unit_tests",
            "check_release_and_ci",
        )

        def run_main() -> None:
            with contextlib.ExitStack() as stack:
                for name in mocked_checks:
                    stack.enter_context(mock.patch.object(VERIFIER, name))
                VERIFIER.main()

        for name, fragment, diagnostic in (
            ("parent", "> [broken](../../outside.md)", "broken skill-local link"),
            ("dot-relative", "- [broken](./missing.md)", "broken skill-local link"),
            ("fragment", "> [broken](#missing-fragment)", "unsupported local link fragment"),
        ):
            with self.subTest(case=name):
                skill_root = self.create_valid_skill()
                try:
                    path = skill_root / "references/runtime-and-delivery.md"
                    original = path.read_text(encoding="utf-8")
                    physical_line = len(VERIFIER.governance_physical_lines(original)) + 1
                    path.write_text(original + fragment + "\n", encoding="utf-8")
                    self.allow_fixture_content_variation()
                    diagnostics = io.StringIO()
                    with contextlib.redirect_stderr(diagnostics), self.assertRaises(SystemExit):
                        run_main()
                    self.assertIn(diagnostic, diagnostics.getvalue())
                    self.assertIn(f"at line {physical_line}", diagnostics.getvalue())
                finally:
                    shutil.rmtree(skill_root, ignore_errors=True)

        skill_root = self.create_valid_skill()
        try:
            path = skill_root / "references/runtime-and-delivery.md"
            path.write_text(
                path.read_text(encoding="utf-8")
                + "> [parent](../SKILL.md)\n"
                + "- [dot](./trust-and-domain-safety.md)\n"
                + "> [external](https://example.com/docs#section)\n",
                encoding="utf-8",
            )
            self.allow_fixture_content_variation()
            run_main()
        finally:
            shutil.rmtree(skill_root, ignore_errors=True)

    def test_reference_link_grammar_fails_closed_and_literals_remain_allowed(self) -> None:
        marker = "TEST_SECRET_REFERENCE_LINK_3617"
        cases = (
            ("full", f"[guide][runtime-{marker}]"),
            ("collapsed", f"[guide-{marker}][]"),
            ("image-full", f"![guide][runtime-{marker}]"),
            ("image-collapsed", f"![guide-{marker}][]"),
            ("definition", f"[runtime-{marker}]: ../SKILL.md"),
            ("container-definition", f"> [runtime-{marker}]: ../SKILL.md"),
            (
                "duplicate-definitions",
                f"[runtime-{marker}]: ../SKILL.md\n[runtime-{marker}]: ../SKILL.md",
            ),
        )
        for name, fragment in cases:
            with self.subTest(case=name):
                skill_root = self.create_valid_skill()
                try:
                    path = skill_root / "references/runtime-and-delivery.md"
                    original = path.read_text(encoding="utf-8")
                    physical_line = len(VERIFIER.governance_physical_lines(original)) + 1
                    path.write_text(original + fragment + "\n", encoding="utf-8")
                    self.allow_fixture_content_variation()
                    diagnostics = io.StringIO()
                    with contextlib.redirect_stderr(diagnostics), self.assertRaises(SystemExit):
                        VERIFIER.check_implementation_quality_governance_skill()
                    self.assertIn("unsupported reference-link syntax", diagnostics.getvalue())
                    self.assertIn(
                        "skills/implementation-quality-governance/references/runtime-and-delivery.md",
                        diagnostics.getvalue(),
                    )
                    self.assertIn(f"at line {physical_line}", diagnostics.getvalue())
                    self.assertNotIn(marker, diagnostics.getvalue())
                finally:
                    shutil.rmtree(skill_root, ignore_errors=True)

        skill_root = self.create_valid_skill()
        try:
            path = skill_root / "references/runtime-and-delivery.md"
            path.write_text(
                path.read_text(encoding="utf-8")
                + "Policy choices are [required] for release.\n"
                + "An unmatched shortcut image ![diagram] remains prose.\n"
                + "Nested [policy [required] text] remains prose.\n"
                + r"Escaped \[literal](missing-TEST_SECRET_REFERENCE_LINK_3617.md) remains prose."
                + "\n",
                encoding="utf-8",
            )
            self.allow_fixture_content_variation()
            VERIFIER.check_implementation_quality_governance_skill()
        finally:
            shutil.rmtree(skill_root, ignore_errors=True)

    def test_local_fragments_are_unsupported_without_heading_slug_emulation(self) -> None:
        marker = "TEST_SECRET_FALSE_ANCHOR_7192"
        for name, fragment, line_offset in (
            ("fragment-only", f"# Real Heading\n[jump](#real-heading-{marker})", 3),
            ("file-fragment", f"[jump](../SKILL.md#implementation-{marker})", 2),
            ("angle-fragment", f"[jump](<#real-heading-{marker}>)", 2),
            ("image-fragment", f"![jump](#real-heading-{marker})", 2),
        ):
            with self.subTest(case=name):
                skill_root = self.create_valid_skill()
                try:
                    path = skill_root / "references/runtime-and-delivery.md"
                    original = path.read_text(encoding="utf-8")
                    physical_line = (
                        len(VERIFIER.governance_physical_lines(original)) + line_offset
                    )
                    path.write_text(original + "\n" + fragment + "\n", encoding="utf-8")
                    self.allow_fixture_content_variation()
                    diagnostics = io.StringIO()
                    with contextlib.redirect_stderr(diagnostics), self.assertRaises(SystemExit):
                        VERIFIER.check_implementation_quality_governance_skill()
                    self.assertIn("unsupported local link fragment", diagnostics.getvalue())
                    self.assertIn(f"at line {physical_line}", diagnostics.getvalue())
                    self.assertNotIn(marker, diagnostics.getvalue())
                finally:
                    shutil.rmtree(skill_root, ignore_errors=True)

    def test_optional_titles_ambiguous_backticks_and_complex_links_fail_closed(self) -> None:
        marker = "TEST_SECRET_BOUNDED_LINK_8421"
        cases = (
            f'[title](../SKILL.md "{marker}")',
            f"[title](<../SKILL.md> '{marker}')",
            f'![title](../SKILL.md "{marker}")',
            f"`[hidden](missing-{marker}.md)",
            f"text ``\n[hidden](missing-{marker}.md)\n``",
            f"[outer [inner-{marker}]](../SKILL.md)",
            f"[escaped\\]](../SKILL-{marker}.md)",
        )
        for fragment in cases:
            with self.subTest(fragment=fragment[:24]):
                skill_root = self.create_valid_skill()
                try:
                    path = skill_root / "references/runtime-and-delivery.md"
                    original = path.read_text(encoding="utf-8")
                    physical_line = len(VERIFIER.governance_physical_lines(original)) + 1
                    path.write_text(original + fragment + "\n", encoding="utf-8")
                    self.allow_fixture_content_variation()
                    diagnostics = io.StringIO()
                    with contextlib.redirect_stderr(diagnostics), self.assertRaises(SystemExit):
                        VERIFIER.check_implementation_quality_governance_skill()
                    rendered = diagnostics.getvalue()
                    self.assertIn(
                        "skills/implementation-quality-governance/references/runtime-and-delivery.md",
                        rendered,
                    )
                    self.assertIn(f"at line {physical_line}", rendered)
                    self.assertNotIn(marker, rendered)
                finally:
                    shutil.rmtree(skill_root, ignore_errors=True)

    def test_multiline_bracket_constructs_fail_closed_on_the_opening_line(self) -> None:
        marker = "TEST_SECRET_MULTILINE_BRACKET_5198"
        cases = (
            ("link", f"[jump\n](missing-{marker}.md)"),
            ("image", f"![image\n](missing-{marker}.png)"),
            ("reference-definition", f"[guide\n]: missing-{marker}.md\n\n[guide]"),
            ("container-link", f"> [jump\n> ](../../{marker}.md)"),
            ("container-image", f"- ![image\n  ](../{marker}.png)"),
            ("fragment", f"[jump\n](#missing-{marker})"),
            ("reference-use", f"[guide\n][missing-{marker}]"),
            ("closing-continuation", f"](missing-{marker}.md)"),
        )
        for name, fragment in cases:
            with self.subTest(case=name):
                skill_root = self.create_valid_skill()
                try:
                    path = skill_root / "references/runtime-and-delivery.md"
                    original = path.read_text(encoding="utf-8")
                    physical_line = len(VERIFIER.governance_physical_lines(original)) + 1
                    path.write_text(original + fragment + "\n", encoding="utf-8")
                    self.allow_fixture_content_variation()
                    diagnostics = io.StringIO()
                    with contextlib.redirect_stderr(diagnostics), self.assertRaises(SystemExit):
                        VERIFIER.check_implementation_quality_governance_skill()
                    rendered = diagnostics.getvalue()
                    self.assertIn(
                        "skills/implementation-quality-governance/references/runtime-and-delivery.md "
                        f"has an ambiguous bracket construct at line {physical_line}",
                        rendered,
                    )
                    self.assertNotIn(marker, rendered)
                finally:
                    shutil.rmtree(skill_root, ignore_errors=True)

        skill_root = self.create_valid_skill()
        try:
            path = skill_root / "references/runtime-and-delivery.md"
            path.write_text(
                path.read_text(encoding="utf-8")
                + "Balanced [required] prose remains valid.\n"
                + "Nested [policy [required] text] remains valid.\n"
                + r"Escaped \[literal opener remains valid."
                + " A [valid](../SKILL.md) link may follow."
                + "\n",
                encoding="utf-8",
            )
            self.allow_fixture_content_variation()
            VERIFIER.check_implementation_quality_governance_skill()
        finally:
            shutil.rmtree(skill_root, ignore_errors=True)

    def test_external_link_schemes_are_exact_and_case_insensitive(self) -> None:
        skill_root = self.create_valid_skill()
        try:
            path = skill_root / "references/runtime-and-delivery.md"
            path.write_text(
                path.read_text(encoding="utf-8")
                + "[upper](HTTP://example.com/docs)\n"
                + "![mixed](hTTps://example.com/image.png)\n"
                + "[mail](MAILTO:quality@example.com)\n"
                + "![mail-image](mAiLtO:quality@example.com)\n",
                encoding="utf-8",
            )
            self.allow_fixture_content_variation()
            VERIFIER.check_implementation_quality_governance_skill()
        finally:
            shutil.rmtree(skill_root, ignore_errors=True)

        marker = "TEST_SECRET_EXTERNAL_SCHEME_4073"
        for target in (
            f"ftp://example.com/{marker}",
            f"javascript:{marker}",
            f"httpx://example.com/{marker}",
            f"https:example.com/{marker}",
            f"mailtox:{marker}@example.com",
        ):
            with self.subTest(target=target.split(":", 1)[0]):
                skill_root = self.create_valid_skill()
                try:
                    path = skill_root / "references/runtime-and-delivery.md"
                    original = path.read_text(encoding="utf-8")
                    physical_line = len(VERIFIER.governance_physical_lines(original)) + 1
                    path.write_text(original + f"[external]({target})\n", encoding="utf-8")
                    self.allow_fixture_content_variation()
                    diagnostics = io.StringIO()
                    with contextlib.redirect_stderr(diagnostics), self.assertRaises(SystemExit):
                        VERIFIER.check_implementation_quality_governance_skill()
                    rendered = diagnostics.getvalue()
                    self.assertIn(
                        "skills/implementation-quality-governance/references/runtime-and-delivery.md",
                        rendered,
                    )
                    self.assertIn(f"at line {physical_line}", rendered)
                    self.assertNotIn(marker, rendered)
                finally:
                    shutil.rmtree(skill_root, ignore_errors=True)

    def test_regular_to_fifo_open_race_is_nonblocking_and_rejected(self) -> None:
        skill_root = self.create_valid_skill()
        path = skill_root / "references/runtime-and-delivery.md"
        real_open = VERIFIER.os.open
        seen_flags: list[int] = []

        def swap_then_open(target: object, flags: int) -> int:
            seen_flags.append(flags)
            path.unlink()
            os.mkfifo(path)
            return real_open(target, flags)

        started = time.monotonic()
        diagnostics = io.StringIO()
        with mock.patch.object(VERIFIER.os, "open", side_effect=swap_then_open), \
             contextlib.redirect_stderr(diagnostics), self.assertRaises(SystemExit):
            VERIFIER.read_governance_artifact(path, skill_root)
        self.assertLess(time.monotonic() - started, 1.0)
        self.assertTrue(seen_flags)
        self.assertTrue(seen_flags[0] & VERIFIER.os.O_NONBLOCK)
        self.assertIn("changed identity before it could be read", diagnostics.getvalue())

    def test_regular_governance_artifact_opens_with_nonblocking_safety_flag(self) -> None:
        skill_root = self.create_valid_skill()
        path = skill_root / "references/runtime-and-delivery.md"
        artifact = VERIFIER.read_governance_artifact(path, skill_root)
        self.assertEqual(artifact.path, path)
        self.assertEqual(len(artifact.identity), 5)

    def test_governance_container_depth_bound_is_sanitized(self) -> None:
        max_depth = getattr(VERIFIER, "MAX_GOVERNANCE_CONTAINER_DEPTH", 64)
        marker = "TEST_SECRET_GOVERNANCE_DEPTH_3075"
        skill_root = self.create_valid_skill()
        path = skill_root / "references/runtime-and-delivery.md"
        original = path.read_text(encoding="utf-8")
        physical_line = len(original.splitlines()) + 1
        path.write_text(
            original + ("> " * (max_depth + 1)) + marker + "\n",
            encoding="utf-8",
        )
        self.allow_fixture_content_variation()
        diagnostics = io.StringIO()
        with contextlib.redirect_stderr(diagnostics), self.assertRaises(SystemExit):
            VERIFIER.check_implementation_quality_governance_skill()
        rendered = diagnostics.getvalue()
        self.assertIn(
            "skills/implementation-quality-governance/references/runtime-and-delivery.md "
            f"exceeds the container depth limit at line {physical_line}",
            rendered,
        )
        self.assertNotIn(marker, rendered)

    def test_governance_container_scanning_scales_linearly(self) -> None:
        def traced_steps(depth: int) -> int:
            steps = 0

            def trace(frame: object, event: str, argument: object) -> object:
                del argument
                nonlocal steps
                if event == "line" and getattr(frame, "f_code").co_filename == str(VERIFIER_PATH):
                    steps += 1
                return trace

            previous = sys.gettrace()
            sys.settrace(trace)
            try:
                VERIFIER.governance_markdown_content(
                    ("> " * depth) + "- " + ("> " * depth) + "content",
                    None,
                )
            finally:
                sys.settrace(previous)
            return steps

        small_steps = traced_steps(6)
        large_steps = traced_steps(24)
        self.assertLess(large_steps, small_steps * 5)

    def test_raw_html_suppression_scales_near_artifact_limit(self) -> None:
        def elapsed(repetitions: int) -> float:
            text = "<div>" + ("<div" * repetitions)
            started = time.process_time()
            VERIFIER.governance_raw_html_suppressed_lines(text)
            return time.process_time() - started

        small = elapsed(3_000)
        large = elapsed(12_000)
        self.assertLess(large, max(0.05, small * 8))

    def test_raw_html_preflight_covers_every_governance_markdown_artifact(self) -> None:
        for relative_path in sorted(
            path for path in VERIFIER.GOVERNANCE_ARTIFACT_PATHS if path.endswith(".md")
        ):
            with self.subTest(path=relative_path):
                skill_root = self.create_valid_skill()
                path = skill_root / relative_path
                path.write_text(
                    path.read_text(encoding="utf-8") + "\n<review-wrapper>\n",
                    encoding="utf-8",
                )
                self.allow_fixture_content_variation()
                self.assert_validation_fails("contains possible raw HTML at line")
                shutil.rmtree(skill_root)

    def test_raw_html_preflight_preserves_code_and_non_candidates(self) -> None:
        additions = (
            "```html\n<div data-mode=raw>\n<!\n<!-\n<![\n</div>\n```",
            "~~~info`allowed\n<div data-mode=raw>\n</div>\n~~~",
            "    <summary open",
            "\t<quality-panel>",
            "    <!",
            "\t<!",
            "    <!-",
            "\t<![",
            "<https://example.com/path>",
            "<person@example.com>",
            "   < ordinary less-than prose",
            "ordinary prose uses < comparison",
            "ordinary prose uses 3 < 5 and 7 > 2",
        )
        skill_root = self.create_valid_skill()
        path = skill_root / "references/runtime-and-delivery.md"
        path.write_text(
            path.read_text(encoding="utf-8") + "\n" + "\n\n".join(additions) + "\n",
            encoding="utf-8",
        )
        self.allow_fixture_content_variation()
        VERIFIER.check_implementation_quality_governance_skill()

    def test_raw_html_in_commonmark_containers_is_rejected(self) -> None:
        marker = "TEST_SECRET_CONTAINER_HTML_7639"
        cases = (
            ("inline-list", f"- <script data-secret={marker}>", 1),
            ("inline-ordered-list", f"1. <script data-secret={marker}>", 1),
            ("blockquote", f"> <script data-secret={marker}>", 1),
            ("nested-quote-list", f"> - <script data-secret={marker}>", 1),
            ("mixed-list-quote", f"- > <script data-secret={marker}>", 1),
            ("list-continuation", f"- item\n  <script data-secret={marker}>", 2),
            ("four-column-list-continuation", f"- item\n    <script data-secret={marker}>", 2),
            ("quote-list-continuation", f"> - item\n>   <script data-secret={marker}>", 2),
            ("list-quote-continuation", f"- > item\n  > <script data-secret={marker}>", 2),
            ("list-space-tab", f"- item\n  \t<div data-secret={marker}>", 2),
            ("list-mixed-tab-space", f"- item\n \t<div data-secret={marker}>", 2),
            ("quote-tab", f"> \t<div data-secret={marker}>", 1),
            ("inner-quote-exit", f"- > item\n    <div data-secret={marker}>", 2),
            (
                "nested-quote-exit",
                f"> - > item\n>     <div data-secret={marker}>",
                2,
            ),
            (
                "ordered-inner-exit",
                f"- outer\n  1. inner\n    <div data-secret={marker}>",
                3,
            ),
            (
                "ordered-width-transition",
                f"9. outer\n   10. inner\n      <div data-secret={marker}>",
                3,
            ),
            ("blank-inner-exit", f"- > item\n\n    <div data-secret={marker}>", 3),
            (
                "container-fence-inner-exit",
                f"- > ```html\n  > safe\n    <div data-secret={marker}>",
                3,
            ),
            ("escaped-list-fence", f"- ```html\n<script data-secret={marker}>", 2),
            ("escaped-quote-fence", f"> ```html\n<script data-secret={marker}>", 2),
            (
                "nested-list-continuation",
                f"- outer\n  - inner\n    <script data-secret={marker}>",
                3,
            ),
        )
        for name, fragment, line_offset in cases:
            with self.subTest(case=name):
                skill_root = self.create_valid_skill()
                path = skill_root / "references/runtime-and-delivery.md"
                original = path.read_text(encoding="utf-8")
                physical_line = len(original.splitlines()) + line_offset
                path.write_text(original + fragment + "\n", encoding="utf-8")
                self.allow_fixture_content_variation()
                diagnostics = io.StringIO()
                with contextlib.redirect_stderr(diagnostics), self.assertRaises(SystemExit):
                    VERIFIER.check_implementation_quality_governance_skill()
                rendered = diagnostics.getvalue()
                self.assertIn(
                    "skills/implementation-quality-governance/references/runtime-and-delivery.md "
                    f"contains possible raw HTML at line {physical_line}",
                    rendered,
                )
                self.assertNotIn(marker, rendered)
                shutil.rmtree(skill_root)

    def test_indented_established_blockquote_markers_cannot_hide_raw_html(self) -> None:
        marker = "TEST_SECRET_INDENTED_QUOTE_HTML_6842"
        cases = (
            ("script", f"***\n>\n    > <script data-secret={marker}>x</script>", 3),
            ("comment", f"***\n>\n    > <!-- {marker} -->", 3),
            ("declaration", f"***\n>\n    > <!DOCTYPE {marker}>", 3),
            ("cdata", f"***\n>\n    > <![CDATA[{marker}]]>", 3),
            ("standard-tag", f"***\n>\n    > <div data-secret={marker}>", 3),
            ("custom-tag", f"***\n>\n    > <quality-panel data-secret={marker}>", 3),
            ("tab-marker", f"***\n>\n\t> <script data-secret={marker}>", 3),
            ("space-tab-marker", f"***\n>\n \t> <script data-secret={marker}>", 3),
            ("nested-quotes", f"***\n>>\n    >> <script data-secret={marker}>", 3),
            ("list-quote", f"- >\n      > <script data-secret={marker}>", 2),
            (
                "quote-list-quote",
                f"> - >\n>       > <script data-secret={marker}>",
                2,
            ),
        )
        for name, fragment, line_offset in cases:
            with self.subTest(case=name):
                skill_root = self.create_valid_skill()
                try:
                    path = skill_root / "references/runtime-and-delivery.md"
                    original = path.read_text(encoding="utf-8")
                    physical_line = (
                        len(VERIFIER.governance_physical_lines(original)) + line_offset
                    )
                    path.write_text(original + fragment + "\n", encoding="utf-8")
                    self.allow_fixture_content_variation()
                    diagnostics = io.StringIO()
                    with contextlib.redirect_stderr(diagnostics), self.assertRaises(SystemExit):
                        VERIFIER.check_implementation_quality_governance_skill()
                    rendered = diagnostics.getvalue()
                    self.assertIn(
                        "skills/implementation-quality-governance/references/runtime-and-delivery.md "
                        f"contains possible raw HTML at line {physical_line}",
                        rendered,
                    )
                    self.assertNotIn(marker, rendered)
                finally:
                    shutil.rmtree(skill_root, ignore_errors=True)

        for fragment in (
            "***\n>\n    <script>",
            "***\n>\n\t<script>",
            "- >\n      <script>",
        ):
            with self.subTest(true_code=fragment):
                skill_root = self.create_valid_skill()
                try:
                    path = skill_root / "references/runtime-and-delivery.md"
                    path.write_text(
                        path.read_text(encoding="utf-8") + fragment + "\n",
                        encoding="utf-8",
                    )
                    self.allow_fixture_content_variation()
                    VERIFIER.check_implementation_quality_governance_skill()
                finally:
                    shutil.rmtree(skill_root, ignore_errors=True)

    def test_nested_container_tab_layouts_fail_closed(self) -> None:
        marker = "TEST_SECRET_NESTED_CONTAINER_TAB_2951"
        cases = (
            ("nested-quotes", f">>> \t<script data-secret={marker}>"),
            ("quotes-list", f">>- \t<script data-secret={marker}>"),
            ("list-nested-quotes", f"- >>> \t<script data-secret={marker}>"),
            ("ordered-nested-quotes", f"1. >>> \t<script data-secret={marker}>"),
            ("spaced-nested-quotes", f"> > > \t<script data-secret={marker}>"),
        )
        for name, fragment in cases:
            with self.subTest(case=name):
                skill_root = self.create_valid_skill()
                try:
                    path = skill_root / "references/runtime-and-delivery.md"
                    original = path.read_text(encoding="utf-8")
                    physical_line = original.count("\n") + 1
                    path.write_text(original + fragment + "\n", encoding="utf-8")
                    self.allow_fixture_content_variation()
                    diagnostics = io.StringIO()
                    with contextlib.redirect_stderr(diagnostics), self.assertRaises(SystemExit):
                        VERIFIER.check_implementation_quality_governance_skill()
                    rendered = diagnostics.getvalue()
                    self.assertIn(
                        "skills/implementation-quality-governance/references/runtime-and-delivery.md "
                        f"has ambiguous container tab layout at line {physical_line}",
                        rendered,
                    )
                    self.assertNotIn(marker, rendered)
                finally:
                    shutil.rmtree(skill_root, ignore_errors=True)

    def test_unmarked_blank_container_exit_terminates_quote_fence(self) -> None:
        marker = "TEST_SECRET_BLANK_QUOTE_FENCE_2846"
        cases = (
            (
                "quote",
                f"> ```html\n\n> <script data-secret={marker}>\n> ```",
                3,
            ),
            (
                "list-quote",
                f"- > ```html\n\n  > <script data-secret={marker}>\n  > ```",
                3,
            ),
            (
                "quote-list",
                f"> - ```html\n\n>   <script data-secret={marker}>\n>   ```",
                3,
            ),
        )
        for name, fragment, line_offset in cases:
            with self.subTest(case=name):
                skill_root = self.create_valid_skill()
                try:
                    path = skill_root / "references/runtime-and-delivery.md"
                    original = path.read_text(encoding="utf-8")
                    physical_line = len(original.splitlines()) + line_offset
                    path.write_text(original + fragment + "\n", encoding="utf-8")
                    self.allow_fixture_content_variation()
                    diagnostics = io.StringIO()
                    with contextlib.redirect_stderr(diagnostics), self.assertRaises(SystemExit):
                        VERIFIER.check_implementation_quality_governance_skill()
                    rendered = diagnostics.getvalue()
                    self.assertIn(
                        "skills/implementation-quality-governance/references/runtime-and-delivery.md "
                        f"contains possible raw HTML at line {physical_line}",
                        rendered,
                    )
                    self.assertNotIn(marker, rendered)
                finally:
                    shutil.rmtree(skill_root, ignore_errors=True)

    def test_quote_tab_overflow_cannot_create_fake_fence(self) -> None:
        marker = "TEST_SECRET_QUOTE_TAB_FENCE_7381"
        cases = (
            (
                "quote-backtick",
                f">\t  ```html\n> <script data-secret={marker}>\n> ```",
            ),
            (
                "quote-tilde",
                f">\t  ~~~html\n> <script data-secret={marker}>\n> ~~~",
            ),
            (
                "one-digit-list-quote-backtick",
                f"1. >\t  ```html\n   > <script data-secret={marker}>\n   > ```",
            ),
            (
                "one-digit-list-quote-tilde",
                f"1. >\t  ~~~html\n   > <script data-secret={marker}>\n   > ~~~",
            ),
            (
                "two-digit-list-quote-backtick",
                f"10. >\t  ```html\n    > <script data-secret={marker}>\n    > ```",
            ),
            (
                "two-digit-list-quote-tilde",
                f"10. >\t  ~~~html\n    > <script data-secret={marker}>\n    > ~~~",
            ),
        )
        for name, fragment in cases:
            with self.subTest(case=name):
                skill_root = self.create_valid_skill()
                try:
                    path = skill_root / "references/runtime-and-delivery.md"
                    original = path.read_text(encoding="utf-8")
                    physical_line = len(original.splitlines()) + 3
                    path.write_text(original + "\n" + fragment + "\n", encoding="utf-8")
                    self.allow_fixture_content_variation()
                    diagnostics = io.StringIO()
                    with contextlib.redirect_stderr(diagnostics), self.assertRaises(SystemExit):
                        VERIFIER.check_implementation_quality_governance_skill()
                    rendered = diagnostics.getvalue()
                    self.assertIn(
                        "skills/implementation-quality-governance/references/runtime-and-delivery.md "
                        f"contains possible raw HTML at line {physical_line}",
                        rendered,
                    )
                    self.assertNotIn(marker, rendered)
                finally:
                    shutil.rmtree(skill_root, ignore_errors=True)

    def test_raw_html_preflight_preserves_commonmark_container_code(self) -> None:
        cases = (
            "- ```html\n  <script>\n  ```",
            "- ```html\n\n  <script>\n  ```",
            "> ~~~html\n> <script>\n> ~~~",
            "> ```html\n>\n> <script>\n> ```",
            "> - ```html\n>   <script>\n>   ```",
            "    <script>",
            "-     <script>",
            "- item\n\n      <script>",
            "- item\n\n  \t  <script>",
            ">     <script>",
            "> \t  <script>",
            ">\t  <script>",
            "1. >\t  <script>",
            "10. >\t  <script>",
            "paragraph\n\n    <script>",
            "paragraph\n1. ```html\n   <div>\n   ```",
            "paragraph\n\n2. ```html\n   <div>\n   ```",
            "- outer\n  - inner\n\n        <script>",
        )
        for fragment in cases:
            with self.subTest(fragment=fragment):
                skill_root = self.create_valid_skill()
                path = skill_root / "references/runtime-and-delivery.md"
                path.write_text(
                    path.read_text(encoding="utf-8") + "\n" + fragment + "\n",
                    encoding="utf-8",
                )
                self.allow_fixture_content_variation()
                VERIFIER.check_implementation_quality_governance_skill()
                shutil.rmtree(skill_root)

    def test_headings_and_breaks_end_paragraph_state_before_true_code(self) -> None:
        cases = (
            "# heading\n    <script>",
            "### heading ###\n    <script>",
            "***\n    <script>",
            "___\n    <script>",
            "paragraph\n---\n    <script>",
            "paragraph\n===\n    <script>",
            "> # heading\n>     <script>",
        )
        for fragment in cases:
            with self.subTest(fragment=fragment):
                skill_root = self.create_valid_skill()
                try:
                    path = skill_root / "references/runtime-and-delivery.md"
                    path.write_text(
                        path.read_text(encoding="utf-8") + fragment + "\n",
                        encoding="utf-8",
                    )
                    self.allow_fixture_content_variation()
                    VERIFIER.check_implementation_quality_governance_skill()
                finally:
                    shutil.rmtree(skill_root, ignore_errors=True)

    def test_angle_wrapped_markdown_destinations_are_not_raw_html(self) -> None:
        self.assertFalse(VERIFIER.governance_line_contains_raw_html("[x](<a>)"))
        self.assertFalse(VERIFIER.governance_line_contains_raw_html("![x](<a>)"))
        self.assertFalse(
            VERIFIER.governance_line_contains_raw_html(
                "[long destination](<references/runtime-and-delivery.md>)"
            )
        )
        self.assertFalse(
            VERIFIER.governance_line_contains_raw_html(r"![escaped](<a\>b>)")
        )
        for destination in ("</docs>", "<?query>", "<!important>"):
            self.assertFalse(
                VERIFIER.governance_line_contains_raw_html(f"[x]({destination})")
            )
        self.assertTrue(
            VERIFIER.governance_line_contains_raw_html("`[x](<a b>)`")
        )

        skill_root = self.create_valid_skill()
        try:
            path = skill_root / "SKILL.md"
            self.replace_once(
                path,
                "[runtime and delivery](references/runtime-and-delivery.md)",
                "[runtime and delivery](<references/runtime-and-delivery.md>)",
            )
            reference = skill_root / "references/runtime-and-delivery.md"
            reference.write_text(
                reference.read_text(encoding="utf-8")
                + "![short](<https://example.com/assets/runtime.png>)\n"
                + r"![escaped](<https://example.com/a\>b>)"
                + "\n",
                encoding="utf-8",
            )
            self.allow_fixture_content_variation()
            VERIFIER.check_implementation_quality_governance_skill()
        finally:
            shutil.rmtree(skill_root, ignore_errors=True)

    def test_angle_destination_lookalikes_do_not_hide_raw_html(self) -> None:
        marker = "TEST_SECRET_ANGLE_DESTINATION_7194"
        cases = (
            f"<span data-secret={marker}>[x](<a>)</span>",
            f"[x](<a></a data-secret={marker}>)",
            f"[x](<a>)<span data-secret={marker}>",
            f"[x](<a data-secret={marker}>",
            f"[x] (<a data-secret={marker}>)",
            rf"\[x](<a data-secret={marker}>)",
        )
        for fragment in cases:
            with self.subTest(fragment=fragment):
                skill_root = self.create_valid_skill()
                try:
                    path = skill_root / "references/runtime-and-delivery.md"
                    original = path.read_text(encoding="utf-8")
                    physical_line = original.count("\n") + 1
                    path.write_text(original + fragment + "\n", encoding="utf-8")
                    self.allow_fixture_content_variation()
                    diagnostics = io.StringIO()
                    with contextlib.redirect_stderr(diagnostics), self.assertRaises(SystemExit):
                        VERIFIER.check_implementation_quality_governance_skill()
                    rendered = diagnostics.getvalue()
                    self.assertIn(
                        "skills/implementation-quality-governance/references/runtime-and-delivery.md "
                        f"contains possible raw HTML at line {physical_line}",
                        rendered,
                    )
                    self.assertNotIn(marker, rendered)
                finally:
                    shutil.rmtree(skill_root, ignore_errors=True)

    def test_noninterrupting_markers_and_lazy_continuations_reject_raw_html(self) -> None:
        marker = "TEST_SECRET_LAZY_PARAGRAPH_5261"
        cases = (
            ("empty-bullet", f"paragraph\n*\n      <script data-secret={marker}>", 3),
            ("empty-ordered", f"paragraph\n1.\n       <script data-secret={marker}>", 3),
            ("overindented-bullet", f"paragraph\n    *\n      <script data-secret={marker}>", 3),
            ("lazy-quote", f"> paragraph\n    <script data-secret={marker}>", 2),
            ("lazy-list-quote", f"- > paragraph\n    <script data-secret={marker}>", 2),
        )
        for name, fragment, offset in cases:
            with self.subTest(case=name):
                skill_root = self.create_valid_skill()
                try:
                    path = skill_root / "references/runtime-and-delivery.md"
                    original = path.read_text(encoding="utf-8")
                    physical_line = original.count("\n") + offset
                    path.write_text(original + fragment + "\n", encoding="utf-8")
                    self.allow_fixture_content_variation()
                    diagnostics = io.StringIO()
                    with contextlib.redirect_stderr(diagnostics), self.assertRaises(SystemExit):
                        VERIFIER.check_implementation_quality_governance_skill()
                    rendered = diagnostics.getvalue()
                    self.assertIn(f"contains possible raw HTML at line {physical_line}", rendered)
                    self.assertNotIn(marker, rendered)
                finally:
                    shutil.rmtree(skill_root, ignore_errors=True)

    def test_invalid_backtick_fence_info_cannot_hide_raw_html(self) -> None:
        marker = "TEST_SECRET_INVALID_FENCE_5184"
        skill_root = self.create_valid_skill()
        path = skill_root / "references/runtime-and-delivery.md"
        original = path.read_text(encoding="utf-8")
        physical_line = len(original.splitlines()) + 2
        path.write_text(
            original + f"```invalid`info\n<div data-secret={marker}>\n",
            encoding="utf-8",
        )
        self.allow_fixture_content_variation()
        diagnostics = io.StringIO()
        with contextlib.redirect_stderr(diagnostics), self.assertRaises(SystemExit):
            VERIFIER.check_implementation_quality_governance_skill()
        rendered = diagnostics.getvalue()
        self.assertIn(
            "skills/implementation-quality-governance/references/runtime-and-delivery.md "
            f"contains possible raw HTML at line {physical_line}",
            rendered,
        )
        self.assertNotIn(marker, rendered)

    def test_raw_html_diagnostic_uses_trusted_label_and_physical_line_only(self) -> None:
        marker = "TEST_SECRET_RAW_HTML_9472"
        for prefix in ("<!", "<!-", "<!["):
            with self.subTest(prefix=prefix):
                skill_root = self.create_valid_skill()
                path = skill_root / "references/runtime-and-delivery.md"
                original = path.read_text(encoding="utf-8")
                physical_line = len(original.splitlines()) + 1
                path.write_text(
                    original + f"{prefix}\n{marker}\n", encoding="utf-8"
                )
                self.allow_fixture_content_variation()
                diagnostics = io.StringIO()
                with contextlib.redirect_stderr(diagnostics), self.assertRaises(SystemExit):
                    VERIFIER.check_implementation_quality_governance_skill()
                rendered = diagnostics.getvalue()
                self.assertIn(
                    "skills/implementation-quality-governance/references/runtime-and-delivery.md "
                    f"contains possible raw HTML at line {physical_line}",
                    rendered,
                )
                self.assertNotIn(marker, rendered)
                shutil.rmtree(skill_root)

    def test_markdown_lookalikes_do_not_satisfy_required_links(self) -> None:
        target = "references/runtime-and-delivery.md"
        for name, replacement, expected in (
            ("escaped", rf"\[runtime]({target})", "link each required reference exactly once"),
            ("inline-code", f"`[runtime]({target})`", "link each required reference exactly once"),
            ("angle-destination", f"<!-- [runtime]({target}) -->", "link each required reference exactly once"),
            ("image", f"![runtime]({target})", "link each required reference exactly once"),
        ):
            with self.subTest(case=name):
                skill_root = self.create_valid_skill()
                try:
                    self.replace_once(skill_root / "SKILL.md", target, replacement)
                    self.allow_fixture_content_variation()
                    self.assert_validation_fails(expected)
                finally:
                    shutil.rmtree(skill_root, ignore_errors=True)

    def test_canonical_markdown_scanner_excludes_container_lines(self) -> None:
        target = "references/runtime-and-delivery.md"
        canonical = f"[runtime]({target})"

        def targets(text: str) -> list[str]:
            return [target for target, _ in VERIFIER.canonical_markdown_links(text)]

        for name, text in (
            ("blockquote-tilde-fence", f"> ~~~\n> {canonical}\n> ~~~"),
            ("blockquote-backtick-fence", f"> ```\n> {canonical}\n> ```"),
            ("list-tilde-fence", f"- ~~~\n  {canonical}\n  ~~~"),
            ("nested-list-backtick-fence", f"  - > ```\n    > {canonical}\n    > ```"),
            ("blockquote-indented-code", f">     {canonical}"),
            ("list-indented-code", f"-     {canonical}"),
            ("normal-blockquote-link", f"> {canonical}"),
            ("normal-ordered-list-link", f"1. {canonical}"),
        ):
            with self.subTest(case=name):
                self.assertEqual(targets(text), [])

        top_level_links = [
            value
            for value, _ in VERIFIER.canonical_markdown_links(
                (SKILL_SOURCE / "SKILL.md").read_text(encoding="utf-8")
            )
        ]
        self.assertEqual(top_level_links.count(target), 1)

    def test_canonical_markdown_scanner_consumes_malformed_suffixes_linearly(self) -> None:
        def scan_repeated(count: int) -> tuple[list[tuple[str, int]], float]:
            text = "[](" * count
            started = time.monotonic()
            links = VERIFIER.canonical_markdown_links(text)
            return links, time.monotonic() - started

        small_links, small_elapsed = scan_repeated(10_000)
        large_links, large_elapsed = scan_repeated(20_000)
        self.assertEqual(small_links, [])
        self.assertEqual(large_links, [])
        self.assertLess(large_elapsed, 3.0)
        self.assertLess(large_elapsed, max(0.5, small_elapsed * 8 + 0.25))

    def test_canonical_markdown_scanner_rejects_noncanonical_destinations(self) -> None:
        target = "references/runtime-and-delivery.md"

        def targets(destination: str) -> list[str]:
            return [
                value
                for value, _ in VERIFIER.canonical_markdown_links(
                    f"[runtime]({destination})"
                )
            ]

        self.assertEqual(targets(target), [target])
        self.assertEqual(targets(f"<{target}>"), [target])
        for destination in (
            f"{target}#part",
            f"{target}#",
            f"{target}?query",
            f"{target}?",
            "references/%72untime-and-delivery.md",
            "./references/runtime-and-delivery.md",
            "../references/runtime-and-delivery.md",
            "/references/runtime-and-delivery.md",
            "https://example.invalid/runtime-and-delivery.md",
            "scheme:runtime-and-delivery.md",
            r"references\runtime-and-delivery.md",
            "references//runtime-and-delivery.md",
            "references/./runtime-and-delivery.md",
            "references/../runtime-and-delivery.md",
            "references/runtime and delivery.md",
            "references/runtime\x1f-and-delivery.md",
            "references/runtime(and)-delivery.md",
            "references/runtime-and-delivery.md(",
            f"<{target}> title",
        ):
            with self.subTest(destination=destination):
                self.assertEqual(targets(destination), [])

        self.assertEqual(
            [value for value, _ in VERIFIER.canonical_markdown_links(f"[runtime]({target}))")],
            [],
        )

    def test_noncanonical_destinations_cannot_satisfy_required_link_checks(self) -> None:
        target = "references/runtime-and-delivery.md"
        for destination in (
            f"{target}#part",
            f"{target}?query",
            "./references/runtime-and-delivery.md",
            "references/runtime(and)-delivery.md",
            r"references\runtime-and-delivery.md",
        ):
            with self.subTest(destination=destination):
                skill_root = self.create_valid_skill()
                self.replace_once(skill_root / "SKILL.md", target, destination)
                self.allow_fixture_content_variation()
                self.assert_validation_fails("link each required reference exactly once")
                shutil.rmtree(skill_root)

    def test_canonical_markdown_scanner_consumes_images_atomically(self) -> None:
        target = "references/runtime-and-delivery.md"
        canonical = f"[ordinary]({target})"

        def targets(text: str) -> list[str]:
            return [value for value, _ in VERIFIER.canonical_markdown_links(text)]

        for name, text in (
            ("reviewer-reproduction", f"![image {canonical}]({target})"),
            ("nested-label", f"![image [nested {canonical}]]({target})"),
            ("multiple-inner-links", f"![image {canonical} {canonical}]({target})"),
            ("escaped-label-brackets", f"![image \\[ordinary\\]({target})]({target})"),
            ("angle-parenthesized-destination", f"![image {canonical}](<{target}>)"),
            ("angle-destination", f"![image {canonical}]<{target}>"),
            ("unclosed-label", f"![image {canonical}"),
            ("unclosed-destination", f"![image {canonical}]("),
            ("unclosed-angle-destination", f"![image {canonical}]<{target}"),
            ("zero-image-escapes", f"!{canonical}"),
            ("two-image-escapes", rf"\\!{canonical}"),
            ("four-image-escapes", rf"\\\\!{canonical}"),
        ):
            with self.subTest(case=name):
                self.assertEqual(targets(text), [])

        for name, text in (
            ("one-image-escape", rf"\!{canonical}"),
            ("three-image-escapes", rf"\\\!{canonical}"),
            ("adjacent-real-link", f"![image {canonical}]({target}) {canonical}"),
        ):
            with self.subTest(case=name):
                self.assertEqual(targets(text), [target])

    def test_image_contents_cannot_satisfy_required_link_checks(self) -> None:
        target = "references/runtime-and-delivery.md"
        skill_root = self.create_valid_skill()
        self.replace_once(
            skill_root / "SKILL.md",
            f"[runtime and delivery]({target})",
            f"![image [ordinary]({target})]({target})",
        )
        self.allow_fixture_content_variation()
        self.assert_validation_fails("link each required reference exactly once")
        shutil.rmtree(skill_root)

    def test_canonical_markdown_scanner_handles_large_unclosed_nested_image(self) -> None:
        started = time.monotonic()
        self.assertEqual(VERIFIER.canonical_markdown_links("![" + "[" * 40_000), [])
        self.assertLess(time.monotonic() - started, 3.0)

    def test_approved_digests_reject_substantive_mutations(self) -> None:
        for relative_path in sorted(VERIFIER.GOVERNANCE_ARTIFACT_PATHS):
            with self.subTest(path=relative_path):
                skill_root = self.create_valid_skill()
                path = skill_root / relative_path
                path.write_bytes(path.read_bytes() + b"\n")
                self.assert_validation_fails("differs from its approved digest")
                shutil.rmtree(skill_root)

    def test_digest_inventory_must_contain_exactly_seven_artifact_keys(self) -> None:
        self.create_valid_skill()
        for name, digests in (
            ("missing", {key: value for key, value in VERIFIER.GOVERNANCE_ARTIFACT_DIGESTS.items() if key != "SKILL.md"}),
            ("extra", {**VERIFIER.GOVERNANCE_ARTIFACT_DIGESTS, "extra.md": "0" * 64}),
        ):
            with self.subTest(case=name):
                VERIFIER.GOVERNANCE_ARTIFACT_DIGESTS = digests
                self.assert_validation_fails("approved digest inventory is incorrect")

    def test_ancestor_symlink_and_root_containment_are_rejected(self) -> None:
        external_skills = self.fixture_root / "external-skills"
        shutil.copytree(SKILL_SOURCE, external_skills / "implementation-quality-governance")
        root = self.fixture_root / "ancestor-symlink"
        root.mkdir()
        try:
            (root / "skills").symlink_to(external_skills, target_is_directory=True)
        except (NotImplementedError, OSError) as error:
            self.skipTest(f"symlinks are unavailable on this platform: {error}")
        VERIFIER.ROOT = root
        self.assert_validation_fails("skills directory must not be a symlink")

        root_link = self.fixture_root / "repository-root-link"
        root_link.symlink_to(root, target_is_directory=True)
        VERIFIER.ROOT = root_link
        self.assert_validation_fails("repository root must not be a symlink")

    def test_governance_diagnostics_and_utf8_failures_are_sanitized(self) -> None:
        marker = "TEST_SECRET_MARKER_8421"
        skill_root = self.create_valid_skill()
        self.replace_once(
            skill_root / "agents/openai.yaml",
            '  display_name: "Implementation Quality Governance"',
            f'  {marker}: "{marker}"',
        )
        diagnostics = io.StringIO()
        with contextlib.redirect_stderr(diagnostics), self.assertRaises(SystemExit):
            VERIFIER.check_implementation_quality_governance_skill()
        self.assertNotIn(marker, diagnostics.getvalue())
        shutil.rmtree(skill_root)

        for relative_path in ("SKILL.md", "agents/openai.yaml", "references/runtime-and-delivery.md"):
            with self.subTest(invalid_utf8=relative_path):
                skill_root = self.create_valid_skill()
                (skill_root / relative_path).write_bytes(b"\xff")
                self.assert_validation_fails("not readable UTF-8 text")
                shutil.rmtree(skill_root)

        skill_root = self.create_valid_skill()
        (skill_root / "SKILL.md").write_text(
            (skill_root / "SKILL.md").read_text(encoding="utf-8") + f"\n[link]({marker})\n",
            encoding="utf-8",
        )
        diagnostics = io.StringIO()
        with contextlib.redirect_stderr(diagnostics), self.assertRaises(SystemExit):
            VERIFIER.check_implementation_quality_governance_skill()
        self.assertNotIn(marker, diagnostics.getvalue())


if __name__ == "__main__":
    unittest.main()
