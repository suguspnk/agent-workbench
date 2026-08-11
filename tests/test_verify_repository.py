from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures"
PATH = ROOT / "scripts/verify_repository.py"
SPEC = importlib.util.spec_from_file_location("verify_repository", PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load verify_repository.py")
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)


class VerifyRepositoryNegativeTests(unittest.TestCase):
    def test_operator_codex_profile_is_read_only(self) -> None:
        path = ROOT / "adapters/codex/.codex/agents/awb-operator.toml"
        profile = VERIFY.parse_codex_profile(path)
        self.assertEqual(VERIFY.EXPECTED_ROLES["awb_operator"][2], "read-only")
        self.assertEqual(profile["sandbox_mode"], "read-only")
        self.assertIn("operation_authorization", profile["developer_instructions"])
        self.assertIn("Do not edit source", profile["developer_instructions"])

    def test_codex_profile_unknown_key_is_rejected(self) -> None:
        with self.assertRaises(SystemExit):
            VERIFY.parse_codex_profile(FIXTURES / "codex-unknown-key.toml")

    def test_codex_profile_duplicate_key_is_rejected(self) -> None:
        with self.assertRaises(SystemExit):
            VERIFY.parse_codex_profile(FIXTURES / "codex-duplicate-key.toml")

    def test_codex_profile_empty_description_is_rejected(self) -> None:
        with self.assertRaisesRegex(SystemExit, "1"):
            VERIFY.parse_codex_profile(FIXTURES / "codex-empty-description.toml")

    def test_claude_duplicate_frontmatter_is_rejected(self) -> None:
        with self.assertRaises(SystemExit):
            VERIFY.parse_frontmatter(FIXTURES / "claude-duplicate-frontmatter.md", VERIFY.CLAUDE_FRONTMATTER_KEYS)

    def test_claude_unknown_frontmatter_is_rejected(self) -> None:
        with self.assertRaises(SystemExit):
            VERIFY.parse_frontmatter(FIXTURES / "claude-unknown-frontmatter.md", VERIFY.CLAUDE_FRONTMATTER_KEYS)

    def test_claude_missing_description_is_rejected(self) -> None:
        with self.assertRaisesRegex(SystemExit, "1"):
            VERIFY.parse_claude_profile(FIXTURES / "claude-missing-description.md")

    def test_safe_reader_rejects_symlink_special_and_oversize_without_hanging(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root = Path(directory)
            target = root / "target.md"
            target.write_text("safe", encoding="utf-8")
            link = root / "link.md"
            link.symlink_to(target)
            with self.assertRaisesRegex(SystemExit, "1"):
                VERIFY.safe_read_text(link)
            real_parent = root / "real-parent"
            real_parent.mkdir()
            nested = real_parent / "nested.md"
            nested.write_text("safe", encoding="utf-8")
            linked_parent = root / "linked-parent"
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            with self.assertRaisesRegex(SystemExit, "1"):
                VERIFY.safe_read_text(linked_parent / "nested.md")
            fifo = root / "special.md"
            os.mkfifo(fifo)
            with self.assertRaisesRegex(SystemExit, "1"):
                VERIFY.safe_read_text(fifo)
            oversize = root / "oversize.md"
            oversize.write_bytes(b"x" * (VERIFY.MAX_ARTIFACT_BYTES + 1))
            with self.assertRaisesRegex(SystemExit, "1"):
                VERIFY.safe_read_text(oversize)

        with tempfile.TemporaryDirectory(dir=Path(tempfile.gettempdir()).resolve()) as directory:
            external = Path(directory) / "valid.txt"
            external.write_text("valid", encoding="utf-8")
            self.assertEqual(VERIFY.safe_read_text(external), "valid")

    def test_repository_json_loader_rejects_deep_and_excessive_nodes(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root = Path(directory)
            deep = root / "deep.json"
            deep.write_text("[" * (VERIFY.MAX_JSON_DEPTH + 1) + "]" * (VERIFY.MAX_JSON_DEPTH + 1), encoding="utf-8")
            with self.assertRaisesRegex(SystemExit, "1"):
                VERIFY.load_json(deep)
            nodes = root / "nodes.json"
            nodes.write_text("[" + ",".join("0" for _ in range(VERIFY.MAX_JSON_NODES)) + "]", encoding="utf-8")
            with self.assertRaisesRegex(SystemExit, "1"):
                VERIFY.load_json(nodes)

    def test_canonical_policy_mutation_and_appended_grants_are_rejected_in_both_harnesses(self) -> None:
        codex_path = ROOT / "adapters/codex/.codex/agents/awb-builder.toml"
        codex = VERIFY.parse_codex_profile(codex_path)["developer_instructions"]
        claude_path = ROOT / "agents/awb-builder.md"
        _, claude = VERIFY.parse_claude_profile(claude_path)
        for path, body in ((codex_path, codex), (claude_path, claude)):
            mutations = (
                body.replace(VERIFY.NON_OPERATOR_AUTHORIZATION, "network and credentials are permitted"),
                body.replace("never inline or propagate credentials", "inline and propagate credentials"),
                body + "\nInternet connectivity is permitted for convenience.\n",
                body + "\nWorkers may retrieve access tokens when useful.\n",
            )
            for mutated in mutations:
                with self.subTest(path=path, mutation=mutated[:40]), self.assertRaisesRegex(SystemExit, "1"):
                    VERIFY.validate_role_policy(path, "awb_builder", mutated)

    def test_external_verifier_policy_mutation_is_rejected_in_both_harnesses(self) -> None:
        codex_path = ROOT / "adapters/codex/.codex/agents/awb-verifier.toml"
        codex = VERIFY.parse_codex_profile(codex_path)["developer_instructions"]
        claude_path = ROOT / "agents/awb-verifier.md"
        _, claude = VERIFY.parse_claude_profile(claude_path)
        for path, body in ((codex_path, codex), (claude_path, claude)):
            mutations = (
                body.replace(VERIFY.VERIFIER_AUTHORIZATION, "network is allowed for verification"),
                body + "\nCredential retrieval can be enabled for verification.\n",
            )
            for mutated in mutations:
                with self.subTest(path=path), self.assertRaisesRegex(SystemExit, "1"):
                    VERIFY.validate_role_policy(path, "awb_verifier", mutated)

    def test_operator_owned_path_deletion_grants_are_rejected_in_both_harnesses(self) -> None:
        codex_path = ROOT / "adapters/codex/.codex/agents/awb-operator.toml"
        codex = VERIFY.parse_codex_profile(codex_path)["developer_instructions"]
        claude_path = ROOT / "agents/awb-operator.md"
        _, claude = VERIFY.parse_claude_profile(claude_path)
        for path, body in ((codex_path, codex), (claude_path, claude)):
            mutations = (
                body.replace(VERIFY.OPERATOR_AUTHORIZATION, "owned-path deletion is permitted"),
                body + "\nOwned-path deletion may be performed when convenient.\n",
            )
            for mutated in mutations:
                with self.subTest(path=path), self.assertRaisesRegex(SystemExit, "1"):
                    VERIFY.validate_role_policy(path, "awb_operator", mutated)

    def test_inverted_independent_identity_is_rejected_in_both_harnesses(self) -> None:
        codex_path = ROOT / "adapters/codex/.codex/agents/awb-reviewer.toml"
        codex = VERIFY.parse_codex_profile(codex_path)["developer_instructions"]
        claude_path = ROOT / "agents/awb-reviewer.md"
        _, claude = VERIFY.parse_claude_profile(claude_path)
        for path, body in ((codex_path, codex), (claude_path, claude)):
            mutated = body.replace("must differ from", "may match")
            with self.subTest(path=path), self.assertRaisesRegex(SystemExit, "1"):
                VERIFY.validate_role_policy(path, "awb_reviewer", mutated)


if __name__ == "__main__":
    unittest.main()
