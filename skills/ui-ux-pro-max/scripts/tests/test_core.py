#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Stdlib-only regression tests for core.py / design_system.py (unittest, not
pytest -- this project ships with zero external dependencies and the tests
shouldn't add one).

Run with:
    python -m unittest discover -s scripts/tests -v
or directly:
    python scripts/tests/test_core.py
"""

import sys
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

from core import BM25, detect_domain, search, search_stack, CSV_CONFIG, AVAILABLE_STACKS
import design_system as design_system_module
from design_system import generate_design_system, persist_design_system, DesignSystemGenerator


class TestTokenizer(unittest.TestCase):
    def test_short_domain_terms_are_kept(self):
        bm25 = BM25()
        tokens = bm25.tokenize("UI and UX design with 3D and AI")
        self.assertIn("ui", tokens)
        self.assertIn("3d", tokens)
        self.assertIn("ai", tokens)

    def test_stopwords_removed(self):
        bm25 = BM25()
        tokens = bm25.tokenize("this is for the team to do")
        for stopword in ("is", "for", "the", "to", "do"):
            self.assertNotIn(stopword, tokens)

    def test_synonym_normalization(self):
        bm25 = BM25()
        self.assertEqual(bm25.tokenize("e-commerce store"), bm25.tokenize("ecommerce store"))
        self.assertEqual(bm25.tokenize("dark-mode toggle"), bm25.tokenize("dark toggle"))


class TestSearchDomains(unittest.TestCase):
    """Known query -> expected top-domain sanity checks (not exact-row pinning,
    since data can grow; these assert the engine still finds *something*
    relevant for each domain's core vocabulary)."""

    def test_ui_is_searchable_in_style_domain(self):
        result = search("ui minimalism", domain="style", max_results=1)
        self.assertGreater(result["count"], 0, "literal 'ui' token must be searchable, not filtered by tokenizer")

    def test_accessibility_query_hits_ux(self):
        result = search("accessibility contrast wcag keyboard", domain="ux", max_results=3)
        self.assertGreater(result["count"], 0)

    def test_zero_result_query_reports_suggestions_not_error(self):
        result = search("zzqqxx totally made up gibberish", domain="ux", max_results=2)
        self.assertEqual(result["count"], 0)
        self.assertIn("suggestions", result)
        self.assertNotIn("error", result)

    def test_every_configured_domain_file_exists_and_is_searchable(self):
        for domain, config in CSV_CONFIG.items():
            with self.subTest(domain=domain):
                result = search("design", domain=domain, max_results=1)
                self.assertNotIn("error", result, f"domain '{domain}' failed: {result.get('error')}")

    def test_every_stack_file_exists_and_is_searchable(self):
        for stack in AVAILABLE_STACKS:
            with self.subTest(stack=stack):
                result = search_stack("performance", stack, max_results=1)
                self.assertNotIn("error", result, f"stack '{stack}' failed: {result.get('error')}")


class TestDomainDetection(unittest.TestCase):
    def test_style_keywords_route_to_style(self):
        self.assertEqual(detect_domain("glassmorphism dark ui"), "style")

    def test_accessibility_keywords_route_to_ux(self):
        self.assertEqual(detect_domain("accessibility contrast wcag"), "ux")

    def test_ambiguous_query_returns_runner_up(self):
        domain, runner_up = detect_domain("font pairing elegant crypto", return_scores=True)
        self.assertIsNotNone(domain)
        # runner_up may be None if the winning domain has no close second --
        # this just verifies the call shape works without raising.

    def test_empty_query_falls_back_to_style(self):
        self.assertEqual(detect_domain("...!!!???"), "style")


class TestPersistence(unittest.TestCase):
    def test_persist_then_skip_then_force(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = generate_design_system(
                "saas dashboard", "Test Project", persist=True,
                output_dir=tmp, confirm_write=True,
            )
            self.assertEqual(result["persistence"]["status"], "success")
            master = Path(result["persistence"]["master_file"])
            self.assertTrue(master.exists())
            original_content = master.read_text(encoding="utf-8")

            # Second persist without force must not overwrite.
            result2 = generate_design_system(
                "saas dashboard", "Test Project", persist=True,
                output_dir=tmp, confirm_write=True,
            )
            self.assertEqual(result2["persistence"]["status"], "skipped_exists")
            self.assertEqual(master.read_text(encoding="utf-8"), original_content)

            # With force=True it must overwrite.
            result3 = generate_design_system(
                "ecommerce luxury", "Test Project", persist=True,
                output_dir=tmp, force=True, confirm_write=True,
            )
            self.assertEqual(result3["persistence"]["status"], "success")

    def test_persist_writes_only_under_output_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = generate_design_system(
                "saas dashboard", "Scoped Project", persist=True,
                page="dashboard",
                output_dir=tmp, confirm_write=True,
            )
            expected = Path(tmp) / "design-system" / "scoped-project" / "MASTER.md"
            page = expected.parent / "pages" / "dashboard.md"
            self.assertTrue(expected.exists())
            self.assertTrue(page.exists())
            master_content = expected.read_text(encoding="utf-8")
            page_content = page.read_text(encoding="utf-8")
            self.assertIn("`pages/[page-name].md` relative to this file", master_content)
            self.assertIn(
                "Read this Master file first. Then check `pages/[page-name].md`",
                master_content,
            )
            self.assertNotIn("`design-system/pages/", master_content)
            self.assertIn("(`../MASTER.md`)", page_content)
            self.assertIn(
                "Read the Master file (`../MASTER.md`) first, then apply the rules "
                "in this file as overrides for this page only.",
                page_content,
            )
            self.assertNotIn("`design-system/MASTER.md`", page_content)
            self.assertTrue(Path(result["persistence"]["master_file"]).samefile(expected))

    def test_persist_requires_authorization_and_absolute_existing_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "authorization"):
                generate_design_system("saas", "Project", persist=True, output_dir=tmp)
            with self.assertRaisesRegex(ValueError, "absolute"):
                generate_design_system(
                    "saas", "Project", persist=True,
                    output_dir="relative/project", confirm_write=True,
                )
            with self.assertRaisesRegex(ValueError, "existing project"):
                generate_design_system(
                    "saas", "Project", persist=True,
                    output_dir=str(Path(tmp) / "missing"), confirm_write=True,
                )

    def test_page_preflight_skips_every_write_without_force(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "design-system" / "test-project"
            pages_dir = project_dir / "pages"
            pages_dir.mkdir(parents=True)
            page_file = pages_dir / "dashboard.md"
            page_file.write_text("keep page", encoding="utf-8")

            result = generate_design_system(
                "saas dashboard", "Test Project", persist=True,
                page="dashboard", output_dir=tmp, confirm_write=True,
            )

            self.assertEqual(result["persistence"]["status"], "skipped_exists")
            self.assertEqual(page_file.read_text(encoding="utf-8"), "keep page")
            self.assertFalse((project_dir / "MASTER.md").exists())

    def test_persist_rejects_symlink_target_without_external_write(self):
        with tempfile.TemporaryDirectory() as project_tmp, tempfile.TemporaryDirectory() as external_tmp:
            project_root = Path(project_tmp)
            external_root = Path(external_tmp)
            (project_root / "design-system").symlink_to(external_root, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "symbolic link"):
                generate_design_system(
                    "saas dashboard", "Symlink Project", persist=True,
                    output_dir=project_tmp, confirm_write=True,
                )

            self.assertFalse((external_root / "symlink-project" / "MASTER.md").exists())

    def test_persist_rejects_component_swapped_to_symlink_after_preflight(self):
        with tempfile.TemporaryDirectory() as project_tmp, tempfile.TemporaryDirectory() as external_tmp:
            project_root = Path(project_tmp)
            external_root = Path(external_tmp)
            design_system_dir = project_root / "design-system"
            project_dir = design_system_dir / "swap-project"
            displaced_dir = design_system_dir / "swap-project-original"
            design_system_dir.mkdir()
            project_dir.mkdir()
            external_master = external_root / "MASTER.md"
            external_master.write_text("do not replace", encoding="utf-8")

            from design_system import format_master_md as real_format_master_md

            def swap_component(design_system):
                content = real_format_master_md(design_system)
                project_dir.rename(displaced_dir)
                project_dir.symlink_to(external_root, target_is_directory=True)
                return content

            with mock.patch("design_system.format_master_md", side_effect=swap_component):
                with self.assertRaisesRegex(ValueError, "symbolic link"):
                    generate_design_system(
                        "saas dashboard", "Swap Project", persist=True,
                        output_dir=project_tmp, confirm_write=True,
                    )

            self.assertEqual(external_master.read_text(encoding="utf-8"), "do not replace")
            self.assertFalse((displaced_dir / "MASTER.md").exists())

    def test_force_commit_rejects_project_directory_relocated_immediately_before_replace(self):
        with tempfile.TemporaryDirectory() as project_tmp, tempfile.TemporaryDirectory() as external_tmp:
            project_root = Path(project_tmp)
            project_dir = project_root / "design-system" / "relocate-force"
            relocated_dir = Path(external_tmp) / "relocated-force"
            real_verify = design_system_module._verify_directory_chain
            real_replace = design_system_module.os.replace
            real_link = design_system_module.os.link
            real_unlink = design_system_module.os.unlink
            relocated = False
            post_relocation_mutations = []

            def relocate_before_commit(descriptors):
                nonlocal relocated
                if not relocated and list(project_dir.glob(".MASTER.md.tmp-*")):
                    project_dir.rename(relocated_dir)
                    relocated = True
                return real_verify(descriptors)

            def record_replace(src, dst, *, src_dir_fd=None, dst_dir_fd=None):
                if relocated:
                    post_relocation_mutations.append("replace")
                return real_replace(
                    src,
                    dst,
                    src_dir_fd=src_dir_fd,
                    dst_dir_fd=dst_dir_fd,
                )

            def record_link(src, dst, *, src_dir_fd=None, dst_dir_fd=None,
                            follow_symlinks=True):
                if relocated:
                    post_relocation_mutations.append("link")
                return real_link(
                    src,
                    dst,
                    src_dir_fd=src_dir_fd,
                    dst_dir_fd=dst_dir_fd,
                    follow_symlinks=follow_symlinks,
                )

            def record_unlink(path, *, dir_fd=None):
                if relocated:
                    post_relocation_mutations.append("unlink")
                return real_unlink(path, dir_fd=dir_fd)

            with mock.patch.object(
                design_system_module,
                "_verify_directory_chain",
                side_effect=relocate_before_commit,
            ), mock.patch.object(
                design_system_module.os, "replace", side_effect=record_replace
            ), mock.patch.object(
                design_system_module.os, "link", side_effect=record_link
            ), mock.patch.object(
                design_system_module.os, "unlink", side_effect=record_unlink
            ), mock.patch.object(
                design_system_module, "_require_secure_persistence_support"
            ):
                with self.assertRaisesRegex(
                    ValueError,
                    "root binding changed.*staging artifact was left orphaned",
                ):
                    generate_design_system(
                        "saas dashboard",
                        "Relocate Force",
                        persist=True,
                        output_dir=project_tmp,
                        force=True,
                        confirm_write=True,
                    )

            self.assertTrue(relocated)
            self.assertEqual(post_relocation_mutations, [])
            self.assertFalse((project_dir / "MASTER.md").exists())
            self.assertFalse((relocated_dir / "MASTER.md").exists())
            staging_files = list(relocated_dir.glob(".MASTER.md.tmp-*"))
            self.assertEqual(len(staging_files), 1)

    def test_no_overwrite_commit_rejects_project_directory_relocated_immediately_before_link(self):
        with tempfile.TemporaryDirectory() as project_tmp, tempfile.TemporaryDirectory() as external_tmp:
            project_root = Path(project_tmp)
            project_dir = project_root / "design-system" / "relocate-safe"
            relocated_dir = Path(external_tmp) / "relocated-safe"
            real_verify = design_system_module._verify_directory_chain
            real_replace = design_system_module.os.replace
            real_link = design_system_module.os.link
            real_unlink = design_system_module.os.unlink
            relocated = False
            post_relocation_mutations = []

            def relocate_before_commit(descriptors):
                nonlocal relocated
                if not relocated and list(project_dir.glob(".MASTER.md.tmp-*")):
                    project_dir.rename(relocated_dir)
                    relocated = True
                return real_verify(descriptors)

            def record_replace(src, dst, *, src_dir_fd=None, dst_dir_fd=None):
                if relocated:
                    post_relocation_mutations.append("replace")
                return real_replace(
                    src,
                    dst,
                    src_dir_fd=src_dir_fd,
                    dst_dir_fd=dst_dir_fd,
                )

            def record_link(src, dst, *, src_dir_fd=None, dst_dir_fd=None,
                            follow_symlinks=True):
                if relocated:
                    post_relocation_mutations.append("link")
                return real_link(
                    src,
                    dst,
                    src_dir_fd=src_dir_fd,
                    dst_dir_fd=dst_dir_fd,
                    follow_symlinks=follow_symlinks,
                )

            def record_unlink(path, *, dir_fd=None):
                if relocated:
                    post_relocation_mutations.append("unlink")
                return real_unlink(path, dir_fd=dir_fd)

            with mock.patch.object(
                design_system_module,
                "_verify_directory_chain",
                side_effect=relocate_before_commit,
            ), mock.patch.object(
                design_system_module.os, "replace", side_effect=record_replace
            ), mock.patch.object(
                design_system_module.os, "link", side_effect=record_link
            ), mock.patch.object(
                design_system_module, "_require_secure_persistence_support"
            ), mock.patch.object(
                design_system_module.os, "unlink", side_effect=record_unlink
            ):
                with self.assertRaisesRegex(
                    ValueError,
                    "root binding changed.*staging artifact was left orphaned",
                ):
                    generate_design_system(
                        "saas dashboard",
                        "Relocate Safe",
                        persist=True,
                        output_dir=project_tmp,
                        confirm_write=True,
                    )

            self.assertTrue(relocated)
            self.assertEqual(post_relocation_mutations, [])
            self.assertFalse((project_dir / "MASTER.md").exists())
            self.assertFalse((relocated_dir / "MASTER.md").exists())
            staging_files = list(relocated_dir.glob(".MASTER.md.tmp-*"))
            self.assertEqual(len(staging_files), 1)

    def test_force_commit_stays_in_retained_parent_when_replace_interposition_swaps_path(self):
        with tempfile.TemporaryDirectory() as project_tmp, tempfile.TemporaryDirectory() as external_tmp:
            project_root = Path(project_tmp)
            external_root = Path(external_tmp)
            project_dir = project_root / "design-system" / "replace-race"
            displaced_dir = project_root / "design-system" / "replace-race-original"
            external_master = external_root / "MASTER.md"
            external_master.write_text("external sentinel", encoding="utf-8")
            real_replace = design_system_module.os.replace
            interposed = False

            def swap_then_replace(src, dst, *, src_dir_fd=None, dst_dir_fd=None):
                nonlocal interposed
                if not interposed and str(src).startswith(".MASTER.md.tmp-"):
                    project_dir.rename(displaced_dir)
                    project_dir.symlink_to(external_root, target_is_directory=True)
                    interposed = True
                return real_replace(
                    src,
                    dst,
                    src_dir_fd=src_dir_fd,
                    dst_dir_fd=dst_dir_fd,
                )

            with mock.patch.object(
                design_system_module.os, "replace", side_effect=swap_then_replace
            ):
                with self.assertRaisesRegex(ValueError, "persistence directory changed"):
                    generate_design_system(
                        "saas dashboard",
                        "Replace Race",
                        persist=True,
                        output_dir=project_tmp,
                        force=True,
                        confirm_write=True,
                    )

            self.assertTrue(interposed)
            self.assertEqual(
                external_master.read_text(encoding="utf-8"),
                "external sentinel",
            )
            self.assertTrue((displaced_dir / "MASTER.md").exists())

    def test_no_overwrite_commit_stays_in_retained_parent_when_link_interposition_swaps_path(self):
        with tempfile.TemporaryDirectory() as project_tmp, tempfile.TemporaryDirectory() as external_tmp:
            project_root = Path(project_tmp)
            external_root = Path(external_tmp)
            project_dir = project_root / "design-system" / "link-race"
            displaced_dir = project_root / "design-system" / "link-race-original"
            external_sentinel = external_root / "sentinel.txt"
            external_sentinel.write_text("external sentinel", encoding="utf-8")
            real_link = design_system_module.os.link
            interposed = False

            def swap_then_link(src, dst, *, src_dir_fd=None, dst_dir_fd=None,
                               follow_symlinks=True):
                nonlocal interposed
                if not interposed and str(src).startswith(".MASTER.md.tmp-"):
                    project_dir.rename(displaced_dir)
                    project_dir.symlink_to(external_root, target_is_directory=True)
                    interposed = True
                return real_link(
                    src,
                    dst,
                    src_dir_fd=src_dir_fd,
                    dst_dir_fd=dst_dir_fd,
                    follow_symlinks=follow_symlinks,
                )

            with mock.patch.object(
                design_system_module.os, "link", side_effect=swap_then_link
            ), mock.patch.object(
                design_system_module, "_require_secure_persistence_support"
            ):
                with self.assertRaisesRegex(ValueError, "persistence root binding changed"):
                    generate_design_system(
                        "saas dashboard",
                        "Link Race",
                        persist=True,
                        output_dir=project_tmp,
                        confirm_write=True,
                    )

            self.assertTrue(interposed)
            self.assertEqual(
                external_sentinel.read_text(encoding="utf-8"),
                "external sentinel",
            )
            self.assertFalse((external_root / "MASTER.md").exists())
            self.assertTrue((displaced_dir / "MASTER.md").exists())

    def test_no_overwrite_staging_cleanup_failure_rolls_back_final(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "design-system" / "cleanup-failure"
            real_unlink = design_system_module.os.unlink
            injected = False

            def fail_first_staging_unlink(path, *, dir_fd=None):
                nonlocal injected
                if not injected and str(path).startswith(".MASTER.md.tmp-"):
                    injected = True
                    raise OSError("injected staging cleanup failure")
                return real_unlink(path, dir_fd=dir_fd)

            with mock.patch.object(
                design_system_module.os, "unlink", side_effect=fail_first_staging_unlink
            ), mock.patch.object(
                design_system_module, "_require_secure_persistence_support"
            ):
                with self.assertRaisesRegex(
                    ValueError,
                    "commit was rolled back after a post-link failure; no final file was committed",
                ):
                    generate_design_system(
                        "saas dashboard",
                        "Cleanup Failure",
                        persist=True,
                        output_dir=tmp,
                        confirm_write=True,
                    )

            self.assertTrue(injected)
            self.assertFalse((project_dir / "MASTER.md").exists())
            self.assertEqual(list(project_dir.glob(".MASTER.md.tmp-*")), [])

    def test_no_overwrite_post_link_verification_failure_rolls_back_final(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "design-system" / "verify-failure"
            real_lstat_at = design_system_module._lstat_at
            real_link = design_system_module.os.link
            link_completed = False
            verification_failed = False

            def record_link(src, dst, *, src_dir_fd=None, dst_dir_fd=None,
                            follow_symlinks=True):
                nonlocal link_completed
                result = real_link(
                    src,
                    dst,
                    src_dir_fd=src_dir_fd,
                    dst_dir_fd=dst_dir_fd,
                    follow_symlinks=follow_symlinks,
                )
                link_completed = True
                return result

            def fail_committed_target_stat(parent_fd, filename):
                nonlocal verification_failed
                if link_completed and filename == "MASTER.md" and not verification_failed:
                    verification_failed = True
                    return None
                return real_lstat_at(parent_fd, filename)

            with mock.patch.object(
                design_system_module,
                "_lstat_at",
                side_effect=fail_committed_target_stat,
            ), mock.patch.object(
                design_system_module.os, "link", side_effect=record_link
            ), mock.patch.object(
                design_system_module, "_require_secure_persistence_support"
            ):
                with self.assertRaisesRegex(
                    ValueError,
                    "commit was rolled back after a post-link failure; no final file was committed",
                ):
                    generate_design_system(
                        "saas dashboard",
                        "Verify Failure",
                        persist=True,
                        output_dir=tmp,
                        confirm_write=True,
                    )

            self.assertTrue(link_completed)
            self.assertTrue(verification_failed)
            self.assertFalse((project_dir / "MASTER.md").exists())
            self.assertEqual(list(project_dir.glob(".MASTER.md.tmp-*")), [])

    def test_no_overwrite_persistent_staging_cleanup_failure_reports_partial_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "design-system" / "partial-cleanup"
            real_unlink = design_system_module.os.unlink

            def fail_staging_unlink(path, *, dir_fd=None):
                if str(path).startswith(".MASTER.md.tmp-"):
                    raise OSError("injected persistent staging cleanup failure")
                return real_unlink(path, dir_fd=dir_fd)

            with mock.patch.object(
                design_system_module.os, "unlink", side_effect=fail_staging_unlink
            ), mock.patch.object(
                design_system_module, "_require_secure_persistence_support"
            ):
                with self.assertRaisesRegex(
                    ValueError,
                    "no final file is present, but its staging artifact could not be removed",
                ):
                    generate_design_system(
                        "saas dashboard",
                        "Partial Cleanup",
                        persist=True,
                        output_dir=tmp,
                        confirm_write=True,
                    )

            self.assertFalse((project_dir / "MASTER.md").exists())
            staging_files = list(project_dir.glob(".MASTER.md.tmp-*"))
            self.assertEqual(len(staging_files), 1)

    def test_no_overwrite_cleanup_and_rollback_failures_preserve_partial_commit_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "design-system" / "combined-failure"
            real_unlink = design_system_module.os.unlink

            def fail_staging_cleanup_and_final_rollback(path, *, dir_fd=None):
                if str(path).startswith(".MASTER.md.tmp-"):
                    raise OSError("injected staging cleanup failure")
                if path == "MASTER.md":
                    raise OSError("injected final rollback failure")
                return real_unlink(path, dir_fd=dir_fd)

            with mock.patch.object(
                design_system_module.os,
                "unlink",
                side_effect=fail_staging_cleanup_and_final_rollback,
            ), mock.patch.object(
                design_system_module, "_require_secure_persistence_support"
            ):
                with self.assertRaises(ValueError) as raised:
                    generate_design_system(
                        "saas dashboard",
                        "Combined Failure",
                        persist=True,
                        output_dir=tmp,
                        confirm_write=True,
                    )

            message = str(raised.exception)
            self.assertIn("the final file may remain committed", message)
            self.assertIn("injected final rollback failure", message)
            self.assertIn("staging artifact could not be removed", message)
            self.assertIn("injected staging cleanup failure", message)
            self.assertTrue((project_dir / "MASTER.md").is_file())
            staging_files = list(project_dir.glob(".MASTER.md.tmp-*"))
            self.assertEqual(len(staging_files), 1)
            self.assertTrue(staging_files[0].samefile(project_dir / "MASTER.md"))

    def test_persist_fails_closed_without_secure_filesystem_primitives(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(design_system_module.os, "supports_dir_fd", set()):
                with self.assertRaisesRegex(ValueError, "secure persistence is unsupported"):
                    generate_design_system(
                        "saas dashboard", "Unsupported Project", persist=True,
                        output_dir=tmp, confirm_write=True,
                    )

            self.assertFalse((Path(tmp) / "design-system").exists())

    def test_cli_requires_explicit_persistence_choices(self):
        script = SCRIPTS_DIR / "search.py"
        with tempfile.TemporaryDirectory() as tmp:
            missing_confirmation = subprocess.run(
                [
                    sys.executable, str(script), "saas", "--design-system",
                    "--persist", "--output-dir", tmp, "--no-overwrite",
                ],
                cwd=tmp,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(missing_confirmation.returncode, 2)
            self.assertIn("--confirm-write", missing_confirmation.stderr)
            self.assertFalse((Path(tmp) / "design-system").exists())

    def test_cli_persisted_guidance_retrieval_is_master_then_page_override(self):
        script = SCRIPTS_DIR / "search.py"
        with tempfile.TemporaryDirectory() as tmp:
            completed = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "saas dashboard",
                    "--design-system",
                    "--persist",
                    "--project-name",
                    "CLI Order",
                    "--output-dir",
                    tmp,
                    "--confirm-write",
                    "--no-overwrite",
                ],
                cwd=tmp,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            expected_dir = Path(tmp).resolve() / "design-system" / "cli-order"
            self.assertIn(f"Usage: Read {expected_dir}/MASTER.md first.", completed.stdout)
            self.assertIn(
                "Then apply pages/[page].md as an override for that page, if it exists.",
                completed.stdout,
            )
            self.assertNotIn("pages/[page].md first", completed.stdout)


class TestReasoningMatch(unittest.TestCase):
    def test_known_category_matches_exactly(self):
        gen = DesignSystemGenerator()
        rule = gen._find_reasoning_rule("SaaS (General)")
        self.assertTrue(rule, "exact-match category lookup should not fall through to fuzzy matching")

    def test_unknown_category_falls_back_gracefully(self):
        gen = DesignSystemGenerator()
        rule = gen._find_reasoning_rule("Totally Unknown Category XYZ")
        # Should not raise; may return {} which _apply_reasoning handles with defaults.
        self.assertIsInstance(rule, dict)


if __name__ == "__main__":
    unittest.main()
