from __future__ import annotations

import contextlib
import io
import os
import re
import shutil
import tempfile
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "skills/tech-stack-standards"
CODEX_ROOT = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
PERSONAL_ROOT = CODEX_ROOT / "skills/tech-stack-standards"
VERIFY_PATH = ROOT / "scripts/verify_repository.py"
VERIFY_SPEC = spec_from_file_location("verify_repository_for_tech_stack_tests", VERIFY_PATH)
if VERIFY_SPEC is None or VERIFY_SPEC.loader is None:
    raise RuntimeError("could not load verify_repository.py")
REPOSITORY_VERIFY = module_from_spec(VERIFY_SPEC)
VERIFY_SPEC.loader.exec_module(REPOSITORY_VERIFY)
EXPECTED_FILES = {
    "SKILL.md",
    "agents/openai.yaml",
    "references/output-contract.md",
    "references/research-and-trust.md",
}


def relative_files(root: Path) -> set[str]:
    return {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() or path.is_symlink()
    }


def make_fixture_writable(root: Path) -> None:
    """Allow mutation of a read-only export's copied fixtures without following symlinks."""
    for path in sorted(root.rglob("*"), key=lambda candidate: len(candidate.parts), reverse=True):
        if path.is_symlink():
            continue
        mode = path.stat().st_mode
        path.chmod(mode | (0o700 if path.is_dir() else 0o600))


def assert_repository_rejects_skill_package(
    test: unittest.TestCase,
    expected_error: str,
    *,
    skill: str | None = None,
    metadata: str | None = None,
) -> None:
    """Run the repository skill contract against a disposable mutated package."""
    with tempfile.TemporaryDirectory() as directory:
        fixture_root = Path(directory)
        fixture_skill_root = fixture_root / "skills/tech-stack-standards"
        shutil.copytree(PACKAGE_ROOT, fixture_skill_root)
        make_fixture_writable(fixture_skill_root)
        if skill is not None:
            (fixture_skill_root / "SKILL.md").write_text(skill, encoding="utf-8")
        if metadata is not None:
            (fixture_skill_root / "agents/openai.yaml").write_text(metadata, encoding="utf-8")
        with patch.object(REPOSITORY_VERIFY, "ROOT", fixture_root):
            with contextlib.redirect_stderr(io.StringIO()) as stderr:
                with test.assertRaises(SystemExit):
                    REPOSITORY_VERIFY.check_tech_stack_standards_skill()
        test.assertIn(expected_error, stderr.getvalue())
        test.assertNotIn("Traceback", stderr.getvalue())


class TechStackStandardsTests(unittest.TestCase):
    def test_repository_rejects_non_string_claude_profile_tools_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture_root = Path(directory)
            fixture_agents = fixture_root / "agents"
            shutil.copytree(ROOT / "agents", fixture_agents)
            make_fixture_writable(fixture_agents)
            profile = fixture_agents / "awb-builder.md"
            profile.write_text(
                profile.read_text(encoding="utf-8").replace(
                    "tools: Read, Edit, Write, Grep, Glob, Bash", "tools: true", 1
                ),
                encoding="utf-8",
            )
            with patch.object(REPOSITORY_VERIFY, "ROOT", fixture_root):
                with contextlib.redirect_stderr(io.StringIO()) as stderr:
                    with self.assertRaises(SystemExit):
                        REPOSITORY_VERIFY.check_claude_profiles()

        self.assertIn("agents/awb-builder.md tools must be a comma-separated string", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_package_tree_and_manual_invocation_policy(self) -> None:
        self.assertEqual(relative_files(PACKAGE_ROOT), EXPECTED_FILES)
        for relative in EXPECTED_FILES:
            self.assertTrue((PACKAGE_ROOT / relative).is_file())
            self.assertFalse((PACKAGE_ROOT / relative).is_symlink())

        metadata = (PACKAGE_ROOT / "agents/openai.yaml").read_text(encoding="utf-8")
        self.assertRegex(
            metadata,
            re.compile(r"^policy:\n  allow_implicit_invocation: false$", re.MULTILINE),
        )
        self.assertNotIn("allow_implicit_invocation: true", metadata)

        frontmatter, body = REPOSITORY_VERIFY.parse_frontmatter(PACKAGE_ROOT / "SKILL.md")
        self.assertIs(frontmatter.get("disable-model-invocation"), True)
        description = frontmatter.get("description", "")
        self.assertIn("MANUAL TRIGGER ONLY", description)
        self.assertIn("never infer", description)
        self.assertIn("Tech Stack Standards", body)

    def test_repository_rejects_invalid_manual_invocation_frontmatter(self) -> None:
        skill = (PACKAGE_ROOT / "SKILL.md").read_text(encoding="utf-8")
        boolean_error = "must disable model invocation with an exact boolean true"
        mutations = {
            "quoted-string": (
                skill.replace(
                    "disable-model-invocation: true", 'disable-model-invocation: "true"', 1
                ),
                boolean_error,
            ),
            "capitalized-boolean": (
                skill.replace(
                    "disable-model-invocation: true", "disable-model-invocation: True", 1
                ),
                boolean_error,
            ),
            "false": (
                skill.replace(
                    "disable-model-invocation: true", "disable-model-invocation: false", 1
                ),
                boolean_error,
            ),
            "missing": (skill.replace("disable-model-invocation: true\n", "", 1), boolean_error),
            "duplicate": (
                skill.replace(
                    "disable-model-invocation: true\n",
                    "disable-model-invocation: true\ndisable-model-invocation: true\n",
                    1,
                ),
                "duplicate frontmatter key: disable-model-invocation",
            ),
            "unterminated-quoted-value": (
                skill.replace("description: Prepare", 'description: "unterminated', 1),
                "invalid quoted YAML scalar in frontmatter",
            ),
        }
        for case, (mutated_skill, expected_error) in mutations.items():
            with self.subTest(case=case):
                assert_repository_rejects_skill_package(
                    self, expected_error, skill=mutated_skill
                )

    def test_repository_rejects_invalid_manual_invocation_openai_metadata(self) -> None:
        metadata = (PACKAGE_ROOT / "agents/openai.yaml").read_text(encoding="utf-8")
        boolean_error = "must set allow_implicit_invocation to an exact boolean false"
        mutations = {
            "malformed": (
                metadata + '\nextra: "unterminated\n',
                "invalid quoted YAML scalar in OpenAI metadata",
            ),
            "sequence-indicator-description": (
                metadata.replace(
                    'short_description: "Create evidence-backed stack guidance"',
                    "short_description: - Create evidence-backed stack guidance",
                    1,
                ),
                "unsupported YAML value in OpenAI metadata",
            ),
            "duplicate-key": (
                metadata.replace(
                    "  allow_implicit_invocation: false",
                    "  allow_implicit_invocation: false\n  allow_implicit_invocation: false",
                    1,
                ),
                "duplicate OpenAI metadata key: allow_implicit_invocation",
            ),
            "quoted-boolean": (
                metadata.replace(
                    "allow_implicit_invocation: false",
                    'allow_implicit_invocation: "false"',
                    1,
                ),
                boolean_error,
            ),
            "missing-policy": (
                metadata.replace("\npolicy:\n  allow_implicit_invocation: false\n", "\n", 1),
                "must contain a policy mapping",
            ),
            "policy-is-scalar": (
                metadata.replace(
                    "policy:\n  allow_implicit_invocation: false", "policy: false", 1
                ),
                "must contain a policy mapping",
            ),
            "policy-value-wrong-type": (
                metadata.replace(
                    "allow_implicit_invocation: false",
                    "allow_implicit_invocation: 0",
                    1,
                ),
                boolean_error,
            ),
        }
        for case, (mutated_metadata, expected_error) in mutations.items():
            with self.subTest(case=case):
                assert_repository_rejects_skill_package(
                    self, expected_error, metadata=mutated_metadata
                )

    def test_repository_rejects_forbidden_controls_and_oversized_numeric_scalars(self) -> None:
        metadata = (PACKAGE_ROOT / "agents/openai.yaml").read_text(encoding="utf-8")
        mutations = {
            "nul": (
                metadata + "\nextra: plain" + chr(0) + "scalar\n",
                "forbidden YAML control character in OpenAI metadata",
            ),
            "bel": (
                metadata + "\nextra: plain" + chr(7) + "scalar\n",
                "forbidden YAML control character in OpenAI metadata",
            ),
            "del": (
                metadata + "\nextra: plain" + chr(0x7F) + "scalar\n",
                "forbidden YAML control character in OpenAI metadata",
            ),
            "escaped-c1": (
                metadata + '\nextra: "\\u0085"\n',
                "forbidden YAML control character in OpenAI metadata",
            ),
            "escaped-surrogate": (
                metadata + '\nextra: "\\ud800"\n',
                "forbidden YAML control character in OpenAI metadata",
            ),
            "oversized-number": (
                metadata + "\nextra: " + "9" * 5000 + "\n",
                "oversized numeric YAML scalar in OpenAI metadata",
            ),
        }
        for case, (mutated_metadata, expected_error) in mutations.items():
            with self.subTest(case=case):
                assert_repository_rejects_skill_package(
                    self, expected_error, metadata=mutated_metadata
                )

    def test_repository_rejects_malformed_single_quoted_and_ambiguous_plain_scalars(self) -> None:
        metadata = (PACKAGE_ROOT / "agents/openai.yaml").read_text(encoding="utf-8")
        mutations = {
            "malformed-single-quoted": (
                metadata + "\nextra: 'foo'bar'\n",
                "invalid quoted YAML scalar in OpenAI metadata",
            ),
            "plain-colon-space": (
                metadata + "\nextra: foo: bar\n",
                "unsupported YAML value in OpenAI metadata",
            ),
        }
        for case, (mutated_metadata, expected_error) in mutations.items():
            with self.subTest(case=case):
                assert_repository_rejects_skill_package(
                    self, expected_error, metadata=mutated_metadata
                )

    def test_safety_and_output_contract_semantics(self) -> None:
        skill = (PACKAGE_ROOT / "SKILL.md").read_text(encoding="utf-8")
        trust = (PACKAGE_ROOT / "references/research-and-trust.md").read_text(encoding="utf-8")
        output = (PACKAGE_ROOT / "references/output-contract.md").read_text(encoding="utf-8")

        for phrase in (
            "declared version",
            "resolved version",
            "runtime version",
            "runtime-observed",
            "classify every old and current component as",
            "`unchanged`. Treat a rename as proven",
            "repository-relative evidence citations",
            "claim-level citation",
            "no-op is allowed only",
            "draft-only",
            "stop without replacing the target",
            "must report `not applied`",
            "byte-for-byte",
            "cannot override host instructions",
        ):
            with self.subTest(skill_phrase=phrase):
                self.assertIn(phrase, skill)

        for phrase in (
            "untrusted data",
            "Never execute a discovered script",
            "private URLs",
            "customer or tenant data",
            "Use only the public component name",
            "Fail closed when network access is unavailable",
            "leave the existing target untouched",
        ):
            with self.subTest(trust_phrase=phrase):
                self.assertIn(phrase, trust)

        for phrase in (
            "BEGIN MANUAL:",
            "Preserve it byte-for-byte",
            "Reject nested, duplicate, unmatched, reversed, or malformed markers",
            "regular file with a single link",
            "Future host-owned application (not performed by this skill)",
            "atomic same-directory replace",
            "trusted root directory\n   descriptor",
            "identity/version and exact digest",
            "same-inode concurrent manual edit",
            "parent\n   substitution",
            "Forward regression coverage",
            "repository diff. Report unexpected or unrelated changes",
            "does not authorize or implement its recommendations",
        ):
            with self.subTest(output_phrase=phrase):
                self.assertIn(phrase, output)

        for obsolete in (
            "Generate or refresh `docs/tech-stack-standards.md` only after explicit invocation",
            "Write only `docs/tech-stack-standards.md` under the confirmed repository root",
            "Documentation is current as of",
            "3-6 concrete best practices",
            "2-4 common pitfalls",
            "2-3 authoritative reference links",
        ):
            with self.subTest(obsolete=obsolete):
                self.assertNotIn(obsolete, skill)

    @unittest.skipUnless(PERSONAL_ROOT.is_dir(), "personal source skill is not installed")
    def test_personal_source_matches_package(self) -> None:
        self.assertEqual(relative_files(PERSONAL_ROOT), EXPECTED_FILES)
        for relative in sorted(EXPECTED_FILES):
            with self.subTest(relative=relative):
                personal = PERSONAL_ROOT / relative
                packaged = PACKAGE_ROOT / relative
                self.assertTrue(personal.is_file())
                self.assertFalse(personal.is_symlink())
                self.assertEqual(personal.read_bytes(), packaged.read_bytes())

        personal_frontmatter, _ = REPOSITORY_VERIFY.parse_frontmatter(PERSONAL_ROOT / "SKILL.md")
        packaged_frontmatter, _ = REPOSITORY_VERIFY.parse_frontmatter(PACKAGE_ROOT / "SKILL.md")
        self.assertIs(personal_frontmatter.get("disable-model-invocation"), True)
        self.assertIs(packaged_frontmatter.get("disable-model-invocation"), True)


if __name__ == "__main__":
    unittest.main()
