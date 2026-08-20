from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


sys.dont_write_bytecode = True


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / ".github/ci/run_sandboxed_validation.py"
SPEC = importlib.util.spec_from_file_location("run_sandboxed_validation", HELPER)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load sandbox helper")
CI = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CI
SPEC.loader.exec_module(CI)
GATE_PATH = ROOT / ".github/ci/trusted_invariant_gate.py"
GATE_SPEC = importlib.util.spec_from_file_location("trusted_invariant_gate", GATE_PATH)
if GATE_SPEC is None or GATE_SPEC.loader is None:
    raise RuntimeError("could not load trusted invariant gate")
GATE = importlib.util.module_from_spec(GATE_SPEC)
sys.modules[GATE_SPEC.name] = GATE
GATE_SPEC.loader.exec_module(GATE)
GENERATOR_PATH = ROOT / ".github/ci/generate_trusted_validation_policy.py"
GENERATOR_SPEC = importlib.util.spec_from_file_location("generate_trusted_validation_policy", GENERATOR_PATH)
if GENERATOR_SPEC is None or GENERATOR_SPEC.loader is None:
    raise RuntimeError("could not load trusted policy generator")
GENERATOR = importlib.util.module_from_spec(GENERATOR_SPEC)
sys.modules[GENERATOR_SPEC.name] = GENERATOR
GENERATOR_SPEC.loader.exec_module(GENERATOR)
POLICY = ROOT / ".github/ci/trusted_validation_policy.json"
WORKFLOW = ROOT / ".github/workflows/validate.yml"
EXPECTED_IMAGES = {
    "3.11": "python:3.11.15-slim-bookworm@sha256:77923445c077d8eb971b14b2b114a1d9cd4a87edb4c75654820ca4832ee8cb15",
    "3.12": "python:3.12.13-slim-bookworm@sha256:72d3d75f2639ab82b34b29390ad3d6e0827c775befee94edda8e9976818f488d",
}


class SandboxCommandTests(unittest.TestCase):
    def test_reviewed_image_allowlist_is_exact(self) -> None:
        self.assertEqual(CI.ALLOWED_IMAGES, EXPECTED_IMAGES)
        workflow = WORKFLOW.read_text(encoding="utf-8")
        for image in EXPECTED_IMAGES.values():
            self.assertIn(image, workflow)

    def test_workflow_keeps_trusted_and_candidate_boundaries_separate(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("permissions:\n  contents: read\n\nconcurrency:", workflow)
        self.assertEqual(workflow.count("persist-credentials: false"), 4)
        self.assertEqual(workflow.count("actions/checkout@11d5960a326750d5838078e36cf38b85af677262"), 4)
        self.assertEqual(workflow.count("github.event.pull_request.head.repo.full_name"), 2)
        self.assertEqual(workflow.count("github.event.pull_request.head.sha"), 4)
        self.assertNotIn("github.event.pull_request.merge_commit_sha", workflow)
        self.assertIn("python3 -I trusted/.github/ci/run_sandboxed_validation.py", workflow)
        self.assertIn("trusted-invariants:", workflow)
        self.assertIn("candidate-behavior:", workflow)
        self.assertIn("needs: trusted-invariants", workflow)
        self.assertIn("--validation-mode trusted-invariants", workflow)
        self.assertIn("--validation-mode candidate-behavior", workflow)
        for forbidden in ("actions/setup-python@", "actions/cache@", "actions/upload-artifact@", "secrets.", "github.token"):
            self.assertNotIn(forbidden, workflow)

    def test_command_has_exact_isolation_contract_and_minimal_environment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory).resolve()
            image = CI.ALLOWED_IMAGES["3.11"]
            command = CI.build_docker_command(
                candidate, image, "3.11", "awb-validation-0123456789abcdefabcd", "candidate-behavior"
            )

        required = {
            "--platform=linux/amd64",
            "--pull=never",
            "--network=none",
            "--read-only",
            "--user=65532:65532",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true",
            "--pids-limit=128",
            "--memory=768m",
            "--memory-swap=768m",
            "--cpus=2",
            "--ulimit=nofile=1024:1024",
            "--ipc=none",
            "--init",
            "--log-driver=none",
            "--tmpfs=/tmp:rw,nosuid,nodev,noexec,size=268435456,mode=1777",
            "--tmpfs=/workspace/.git:ro,nosuid,nodev,noexec,size=65536,mode=000",
            "--workdir=/workspace",
        }
        self.assertTrue(required.issubset(command))
        self.assertIn(f"--mount=type=bind,src={candidate},dst=/workspace,readonly", command)
        self.assertIn(f"--mount=type=bind,src={HELPER},dst=/opt/awb/run_validation.py,readonly", command)
        self.assertEqual(
            [value for value in command if value.startswith("--mount=")],
            [
                f"--mount=type=bind,src={candidate},dst=/workspace,readonly",
                f"--mount=type=bind,src={HELPER},dst=/opt/awb/run_validation.py,readonly",
            ],
        )
        self.assertEqual(
            command[-9:],
            [image, "/usr/local/bin/python", "-I", "/opt/awb/run_validation.py", "--inside", "--validation-mode", "candidate-behavior", "--expected-python", "3.11"],
        )

        joined = "\n".join(command)
        for forbidden in ("docker.sock", "/github", "GITHUB_TOKEN", "ACTIONS_RUNTIME_TOKEN", "--privileged"):
            self.assertNotIn(forbidden, joined)
        env_values = [command[index + 1] for index, value in enumerate(command[:-1]) if value == "--env"]
        self.assertEqual(env_values, [f"{key}={value}" for key, value in CI.SAFE_CHILD_ENV.items()])

    def test_only_allowlisted_image_python_pair_and_safe_inputs_are_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = str(Path(directory).resolve())
            name = "awb-validation-0123456789abcdefabcd"
            sha = "a" * 40
            self.assertEqual(
                CI.validate_inputs(CI.ALLOWED_IMAGES["3.12"], "3.12", workspace, sha, name, "trusted-invariants"),
                Path(workspace),
            )
            cases = (
                ("python:3.12-slim", "3.12", workspace, sha, name, "trusted-invariants"),
                (CI.ALLOWED_IMAGES["3.12"], "3.11", workspace, sha, name, "trusted-invariants"),
                (CI.ALLOWED_IMAGES["3.12"], "3.12", workspace, "A" * 40, name, "trusted-invariants"),
                (CI.ALLOWED_IMAGES["3.12"], "3.12", workspace, sha, "unsafe-name", "trusted-invariants"),
                (CI.ALLOWED_IMAGES["3.12"], "3.12", workspace, sha, name, "unknown"),
            )
            for arguments in cases:
                with self.subTest(arguments=arguments), self.assertRaises(CI.SandboxError):
                    CI.validate_inputs(*arguments)

    def test_safe_child_environment_excludes_sensitive_parent_values(self) -> None:
        with mock.patch.dict(os.environ, {"GITHUB_TOKEN": "parent-secret", "HTTPS_PROXY": "http://proxy"}, clear=False):
            self.assertNotIn("GITHUB_TOKEN", CI.SAFE_CHILD_ENV)
            self.assertNotIn("HTTPS_PROXY", CI.SAFE_CHILD_ENV)
            self.assertNotIn("parent-secret", CI._host_environment().values())

    def test_trusted_mode_mounts_each_base_control_individually(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            command = CI.build_docker_command(
                Path(directory).resolve(), CI.ALLOWED_IMAGES["3.12"], "3.12",
                "awb-validation-0123456789abcdefabcd", "trusted-invariants",
            )
        mounts = [value for value in command if value.startswith("--mount=")]
        self.assertEqual(len(mounts), 5)
        for destination in (
            "/opt/awb/run_validation.py", "/opt/awb/trusted_invariant_gate.py",
            "/opt/awb/trusted_validation_policy.json", "/opt/awb/validate.yml",
        ):
            self.assertEqual(sum(f"dst={destination},readonly" in value for value in mounts), 1)


class CheckoutCredentialTests(unittest.TestCase):
    def _repository(self, root: Path) -> tuple[Path, str]:
        repository = root / "candidate"
        repository.mkdir()
        environment = {"HOME": "/nonexistent", "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}
        subprocess.run(["/usr/bin/git", "init", "-q", repository], check=True, env=environment)
        (repository / "file.txt").write_text("candidate", encoding="utf-8")
        subprocess.run(["/usr/bin/git", "-C", repository, "add", "file.txt"], check=True, env=environment)
        subprocess.run(
            ["/usr/bin/git", "-C", repository, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "candidate"],
            check=True,
            env=environment,
        )
        sha = subprocess.run(
            ["/usr/bin/git", "-C", repository, "rev-parse", "HEAD"],
            check=True,
            env=environment,
            text=True,
            capture_output=True,
        ).stdout.strip()
        return repository, sha

    def test_clean_checkout_and_matching_sha_are_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository, sha = self._repository(Path(directory))
            CI.verify_checkout_credentials(repository, sha)

    def test_modified_tracked_checkout_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository, sha = self._repository(Path(directory))
            (repository / "file.txt").write_text("changed after checkout", encoding="utf-8")
            with self.assertRaisesRegex(CI.SandboxError, "modified tracked files"):
                CI.verify_checkout_credentials(repository, sha)

    def test_credential_residue_and_mismatched_sha_are_rejected(self) -> None:
        settings = (
            ("http.https://github.com/.extraheader", "AUTHORIZATION: basic secret"),
            ("credential.helper", "store"),
            ("credential.https://github.com.helper", "store"),
            ("url.https://user:secret@github.com/.insteadOf", "https://github.com/"),
        )
        environment = {"HOME": "/nonexistent", "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}
        for key, value in settings:
            with self.subTest(key=key), tempfile.TemporaryDirectory() as directory:
                repository, sha = self._repository(Path(directory))
                subprocess.run(["/usr/bin/git", "-C", repository, "config", "--local", key, value], check=True, env=environment)
                with self.assertRaises(CI.SandboxError):
                    CI.verify_checkout_credentials(repository, sha)
        with tempfile.TemporaryDirectory() as directory:
            repository, sha = self._repository(Path(directory))
            (repository / ".git-credentials").write_text("https://user:secret@example.invalid", encoding="utf-8")
            with self.assertRaises(CI.SandboxError):
                CI.verify_checkout_credentials(repository, sha)
            (repository / ".git-credentials").unlink()
            (repository / ".git/.git-credentials").write_text("https://user:secret@example.invalid", encoding="utf-8")
            with self.assertRaises(CI.SandboxError):
                CI.verify_checkout_credentials(repository, sha)
            with self.assertRaises(CI.SandboxError):
                CI.verify_checkout_credentials(repository, "f" * 40)


class BoundedProcessTests(unittest.TestCase):
    def test_flood_is_bounded_nonzero_propagates_and_sensitive_output_is_safe(self) -> None:
        result = CI.run_bounded(
            [sys.executable, "-c", "import sys; sys.stdout.write('A' * 200000); raise SystemExit(7)"],
            env={"PATH": "/usr/bin:/bin"},
            timeout=5,
        )
        self.assertEqual(result.returncode, 7)
        self.assertTrue(result.truncated)
        self.assertLessEqual(len(result.output), CI.MAX_CAPTURE_BYTES + 32)
        token = "gh" + "p_1234567890abcdefghijkl"
        fine_grained = "github_" + "pat_1234567890abcdefghijkl"
        rendered = CI.sanitize_output(
            f"Authorization: Bearer {fine_grained}\nTOKEN={token}\x1b\x07",
            (token,),
        )
        self.assertNotIn("github_pat_", rendered)
        self.assertNotIn("ghp_", rendered)
        self.assertNotIn("\x1b", rendered)
        self.assertIn("\\u001b", rendered)

    def test_hanging_child_is_terminated(self) -> None:
        result = CI.run_bounded(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            env={"PATH": "/usr/bin:/bin"},
            timeout=0.05,
        )
        self.assertTrue(result.timed_out)
        self.assertNotEqual(result.returncode, 0)

    def test_host_cleanup_runs_on_success_failure_timeout_and_interruption(self) -> None:
        outcomes = (
            CI.ProcessResult(0, b"", False, False),
            CI.ProcessResult(3, b"failure", False, False),
            CI.ProcessResult(-15, b"timeout", False, True),
            KeyboardInterrupt(),
        )
        with tempfile.TemporaryDirectory() as directory:
            workspace = str(Path(directory).resolve())
            for outcome in outcomes:
                with self.subTest(outcome=outcome):
                    validation = outcome if isinstance(outcome, BaseException) else outcome
                    cleanup = CI.ProcessResult(0, b"", False, False)
                    side_effect = [validation, cleanup]
                    with (
                        mock.patch.object(CI, "verify_checkout_credentials"),
                        mock.patch.object(CI, "run_bounded", side_effect=side_effect) as bounded,
                    ):
                        if isinstance(outcome, KeyboardInterrupt):
                            with self.assertRaises(KeyboardInterrupt):
                                CI.host_main(workspace, "a" * 40, CI.ALLOWED_IMAGES["3.11"], "3.11", "candidate-behavior")
                        elif outcome.returncode or outcome.timed_out:
                            with self.assertRaises(CI.SandboxError):
                                CI.host_main(workspace, "a" * 40, CI.ALLOWED_IMAGES["3.11"], "3.11", "candidate-behavior")
                        else:
                            CI.host_main(workspace, "a" * 40, CI.ALLOWED_IMAGES["3.11"], "3.11", "candidate-behavior")
                    self.assertEqual(bounded.call_count, 2)

    def test_authoritative_success_message_cannot_be_candidate_stdout(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            mock.patch.object(CI, "verify_checkout_credentials"),
            mock.patch.object(
                CI, "run_bounded",
                side_effect=(
                    CI.ProcessResult(0, b"candidate says trusted checks passed", False, False),
                    CI.ProcessResult(0, b"", False, False),
                ),
            ),
            mock.patch("builtins.print") as rendered,
        ):
            CI.host_main(
                str(Path(directory).resolve()), "a" * 40, CI.ALLOWED_IMAGES["3.12"],
                "3.12", "trusted-invariants",
            )
        rendered.assert_called_once_with("Trusted repository invariants passed.")


class InsidePreflightTests(unittest.TestCase):
    def test_preflight_rejects_root_wrong_python_forbidden_env_and_extra_interface(self) -> None:
        expected = f"{sys.version_info.major}.{sys.version_info.minor}"
        with mock.patch.object(CI.os, "geteuid", return_value=0):
            with self.assertRaises(CI.SandboxError):
                CI.inside_container_main(expected, "candidate-behavior")
        with mock.patch.object(CI.os, "geteuid", return_value=65532), mock.patch.object(CI.os, "getegid", return_value=65532):
            with self.assertRaises(CI.SandboxError):
                CI.inside_container_main("0.0", "candidate-behavior")
        with (
            mock.patch.object(CI.os, "geteuid", return_value=65532),
            mock.patch.object(CI.os, "getegid", return_value=65532),
            mock.patch.dict(CI.os.environ, {**CI.SAFE_CHILD_ENV, "GITHUB_TOKEN": "secret"}, clear=True),
        ):
            with self.assertRaises(CI.SandboxError):
                CI.inside_container_main(expected, "candidate-behavior")
        with (
            mock.patch.object(CI.os, "geteuid", return_value=65532),
            mock.patch.object(CI.os, "getegid", return_value=65532),
            mock.patch.dict(CI.os.environ, CI.SAFE_CHILD_ENV, clear=True),
            mock.patch.object(CI.Path, "iterdir", return_value=iter((Path("/lo"), Path("/eth0")))),
        ):
            with self.assertRaises(CI.SandboxError):
                CI.inside_container_main(expected, "candidate-behavior")

    def test_valid_preflight_execs_validator_with_fresh_minimal_environment(self) -> None:
        expected = f"{sys.version_info.major}.{sys.version_info.minor}"
        with (
            mock.patch.object(CI.os, "geteuid", return_value=65532),
            mock.patch.object(CI.os, "getegid", return_value=65532),
            mock.patch.dict(CI.os.environ, CI.SAFE_CHILD_ENV, clear=True),
            mock.patch.object(CI.Path, "iterdir", return_value=iter((Path("/lo"),))),
            mock.patch.object(CI.os, "scandir", side_effect=PermissionError),
            mock.patch.object(CI.os, "execve", side_effect=RuntimeError("exec sentinel")) as execute,
        ):
            with self.assertRaisesRegex(RuntimeError, "exec sentinel"):
                CI.inside_container_main(expected, "candidate-behavior")
        self.assertEqual(execute.call_args.args[0], "/usr/local/bin/python")
        self.assertEqual(execute.call_args.args[2], CI.SAFE_CHILD_ENV)

    def test_trusted_preflight_execs_only_the_mounted_gate(self) -> None:
        with (
            mock.patch.object(CI.os, "geteuid", return_value=65532),
            mock.patch.object(CI.os, "getegid", return_value=65532),
            mock.patch.object(CI.sys, "version_info", mock.Mock(major=3, minor=12)),
            mock.patch.dict(CI.os.environ, CI.SAFE_CHILD_ENV, clear=True),
            mock.patch.object(CI.Path, "iterdir", return_value=iter((Path("/lo"),))),
            mock.patch.object(CI.os, "scandir", side_effect=PermissionError),
            mock.patch.object(CI.os, "execve", side_effect=RuntimeError("exec sentinel")) as execute,
        ):
            with self.assertRaisesRegex(RuntimeError, "exec sentinel"):
                CI.inside_container_main("3.12", "trusted-invariants")
        argv = execute.call_args.args[1]
        self.assertEqual(argv[:3], ["/usr/local/bin/python", "-I", "/opt/awb/trusted_invariant_gate.py"])
        self.assertNotIn("/workspace/scripts/verify_repository.py", argv)


class TrustedInvariantGateTests(unittest.TestCase):
    def _candidate_copy(self, parent: Path) -> Path:
        candidate = parent / "candidate"
        shutil.copytree(
            ROOT,
            candidate,
            ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"),
        )
        for directory, directory_names, file_names in os.walk(candidate, topdown=False, followlinks=False):
            for name in file_names:
                path = Path(directory) / name
                if not path.is_symlink():
                    path.chmod(0o600 | (path.stat().st_mode & 0o111))
            for name in directory_names:
                path = Path(directory) / name
                if not path.is_symlink():
                    path.chmod(0o700 | (path.stat().st_mode & 0o111))
        # A read-only export may have cleared mode bits before this fixture is
        # copied; restore only the executable bits asserted by its trusted policy.
        policy = json.loads((ROOT / ".github/ci/trusted_validation_policy.json").read_text(encoding="utf-8"))
        for entry in policy["protected_surface_inventory"]:
            if entry["executable"]:
                path = candidate / entry["path"]
                if not path.is_symlink():
                    path.chmod(path.stat().st_mode | 0o111)
        candidate.chmod(0o700)
        return candidate

    def _validate(self, candidate: Path) -> None:
        with mock.patch.object(GATE, "CANDIDATE_ROOT", os.fspath(candidate)):
            GATE.validate(
                candidate_root=os.fspath(candidate),
                policy_path=os.fspath(POLICY),
                trusted_gate_path=os.fspath(GATE_PATH),
                trusted_launcher_path=os.fspath(HELPER),
                trusted_workflow_path=os.fspath(WORKFLOW),
            )

    def test_policy_is_exact_and_complete_and_current_candidate_passes(self) -> None:
        policy = GATE.load_policy(POLICY.read_bytes())
        self.assertEqual(len(policy["authorization_by_role"]), 12)
        self.assertEqual(len(policy["codex_profiles"]), 12)
        self.assertEqual(len(policy["claude_profiles"]), 12)
        self.assertEqual(set(policy["codex_profiles"]), set(policy["claude_profiles"]))
        self.assertEqual(
            policy["authorization_by_role"][GATE.OWNERSHIP_PROBE_ROLE],
            GATE.OWNERSHIP_PROBE_AUTHORIZATION,
        )
        for family, expected in GATE.OWNERSHIP_PROBE_PROFILES.items():
            profile = policy[family][GATE.OWNERSHIP_PROBE_ROLE]
            self.assertEqual({key: profile[key] for key in expected}, expected)
        self.assertEqual(policy["protected_surface_roots"], list(GATE.PROTECTED_ROOTS))
        for path in (
            "tests/test_verify_repository.py",
            "tests/test_ci_sandbox.py",
            "tests/test_code_review_scope.py",
        ):
            self.assertIn(path, policy["pinned_candidate_files"])
        with tempfile.TemporaryDirectory() as directory:
            self._validate(self._candidate_copy(Path(directory)))

    def test_policy_rejects_ownership_probe_count_authorization_and_profile_drift(self) -> None:
        original = json.loads(POLICY.read_text(encoding="utf-8"))

        missing = json.loads(json.dumps(original))
        missing["authorization_by_role"].pop(GATE.OWNERSHIP_PROBE_ROLE)
        missing["codex_profiles"].pop(GATE.OWNERSHIP_PROBE_ROLE)
        missing["claude_profiles"].pop(GATE.OWNERSHIP_PROBE_ROLE)
        missing["policy_input_sha256"] = GATE.policy_input_sha256(missing)
        with self.assertRaisesRegex(GATE.GateError, "exactly 12 roles"):
            GATE.load_policy((json.dumps(missing) + "\n").encode())

        broadened_authority = json.loads(json.dumps(original))
        broadened_authority["authorization_by_role"][GATE.OWNERSHIP_PROBE_ROLE] = "allow network and credentials"
        broadened_authority["policy_input_sha256"] = GATE.policy_input_sha256(broadened_authority)
        with self.assertRaisesRegex(GATE.GateError, "exact non-operator authorization denial"):
            GATE.load_policy((json.dumps(broadened_authority) + "\n").encode())

        broadened_profile = json.loads(json.dumps(original))
        broadened_profile["claude_profiles"][GATE.OWNERSHIP_PROBE_ROLE]["tools"] = ["Glob", "Read"]
        with self.assertRaisesRegex(GATE.GateError, "exact least-privilege profile"):
            GATE.load_policy((json.dumps(broadened_profile) + "\n").encode())

    def test_protected_surface_inventory_rejects_explicit_bytecode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = self._candidate_copy(Path(directory))
            bytecode = candidate / "scripts/__pycache__/candidate.cpython-312.pyc"
            bytecode.parent.mkdir()
            bytecode.write_bytes(b"\xff\x00candidate-bytecode")
            policy = GATE.load_policy(POLICY.read_bytes())
            with mock.patch.object(GATE, "CANDIDATE_ROOT", os.fspath(candidate)):
                reader = GATE.CandidateReader.open(
                    os.fspath(candidate), policy["max_file_bytes"]
                )
            try:
                with self.assertRaisesRegex(
                    GATE.GateError, "protected surface inventory differs"
                ):
                    GATE.validate_protected_surfaces(reader, policy)
            finally:
                reader.close()

    def test_root_protected_file_deletion_mode_and_tamper_are_rejected(self) -> None:
        cases = (
            ("deletion", lambda path: path.unlink(), "protected surface entry cannot be opened safely"),
            ("mode", lambda path: path.chmod(path.stat().st_mode | 0o111), "protected surface executable mode differs"),
            (
                "tamper",
                lambda path: path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8"),
                "protected surface hash differs",
            ),
        )
        for name, mutate, diagnostic in cases:
            with self.subTest(case=name), tempfile.TemporaryDirectory() as directory:
                candidate = self._candidate_copy(Path(directory))
                mutate(candidate / ".mcp.json")
                with self.assertRaisesRegex(GATE.GateError, diagnostic):
                    self._validate(candidate)

    def test_candidate_noop_validator_fails_the_authoritative_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = self._candidate_copy(Path(directory))
            (candidate / "scripts/verify_repository.py").write_text(
                "#!/usr/bin/env python3\nprint('no-op validator passed')\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(GATE.GateError, "pinned candidate file differs"):
                self._validate(candidate)

    def test_candidate_canonical_test_deletion_fails_the_authoritative_gate(self) -> None:
        for path in (
            "tests/test_verify_repository.py",
            "tests/test_ci_sandbox.py",
            "tests/test_code_review_scope.py",
        ):
            with self.subTest(path=path), tempfile.TemporaryDirectory() as directory:
                candidate = self._candidate_copy(Path(directory))
                (candidate / path).unlink()
                with self.assertRaisesRegex(GATE.GateError, "candidate file is missing|protected surface inventory differs"):
                    self._validate(candidate)

    def test_candidate_control_change_and_duplicate_profile_key_fail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = self._candidate_copy(Path(directory))
            workflow = candidate / ".github/workflows/validate.yml"
            workflow.write_text(workflow.read_text(encoding="utf-8") + "\n# candidate change\n", encoding="utf-8")
            with self.assertRaisesRegex(GATE.GateError, "candidate trusted control differs"):
                self._validate(candidate)
        with tempfile.TemporaryDirectory() as directory:
            candidate = self._candidate_copy(Path(directory))
            profile = candidate / "agents/awb-builder.md"
            profile.write_text(
                profile.read_text(encoding="utf-8").replace("description:", "name: duplicate\ndescription:", 1),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(GATE.GateError, "duplicate frontmatter"):
                self._validate(candidate)

    def test_protected_executable_mode_removal_is_rejected(self) -> None:
        for relative in (
            "skills/pr-evidence/scripts/upload-github-attachment.sh",
            "skills/pr-evidence/scripts/tests/test-upload-github-attachment.sh",
        ):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as directory:
                candidate = self._candidate_copy(Path(directory))
                target = candidate / relative
                target.chmod(target.stat().st_mode & ~0o111)
                with self.assertRaisesRegex(GATE.GateError, "protected surface executable mode differs"):
                    self._validate(candidate)

    def test_fixed_reader_rejects_traversal_symlink_special_and_oversize(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "regular").write_text("safe", encoding="utf-8")
            (root / "large").write_bytes(b"x" * 17)
            (root / "link").symlink_to(root / "regular")
            (root / "real").mkdir()
            (root / "real/nested").write_text("safe", encoding="utf-8")
            (root / "linked-parent").symlink_to(root / "real", target_is_directory=True)
            os.mkfifo(root / "fifo")
            with mock.patch.object(GATE, "CANDIDATE_ROOT", os.fspath(root)):
                reader = GATE.CandidateReader.open(os.fspath(root), 16)
            try:
                for path in ("../regular", "link", "linked-parent/nested", "fifo", "large"):
                    with self.subTest(path=path), self.assertRaises(GATE.GateError):
                        reader.read(path)
            finally:
                reader.close()

    def test_recognized_surfaces_are_rejected_at_arbitrary_depth(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = self._candidate_copy(Path(directory))
            nested = candidate / "docs" / "nested"
            nested.mkdir(parents=True)
            (nested / "SKILL.md").write_text("untrusted authority", encoding="utf-8")
            with self.assertRaisesRegex(GATE.GateError, "unallowlisted instruction surface"):
                self._validate(candidate)
        with tempfile.TemporaryDirectory() as directory:
            candidate = self._candidate_copy(Path(directory))
            nested = candidate / "misc" / "workflows"
            nested.mkdir(parents=True)
            with self.assertRaisesRegex(GATE.GateError, "unallowlisted instruction directory"):
                self._validate(candidate)
        for name in (".agents", ".github", "agents", "skills"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                candidate = self._candidate_copy(Path(directory))
                nested = candidate / "misc" / name
                nested.mkdir(parents=True)
                with self.assertRaisesRegex(GATE.GateError, "unallowlisted instruction directory"):
                    self._validate(candidate)

    def test_strict_json_rejects_duplicate_keys_invalid_utf8_and_unknown_policy_keys(self) -> None:
        with self.assertRaisesRegex(GATE.GateError, "duplicate JSON key"):
            GATE.load_json_bytes("candidate", b'{"key": 1, "key": 2}')
        with self.assertRaisesRegex(GATE.GateError, "strict UTF-8 JSON"):
            GATE.load_json_bytes("candidate", b'{"key": "\xff"}')
        policy = POLICY.read_text(encoding="utf-8").replace(
            '"schema_version": 2,', '"schema_version": 2,\n  "unknown": true,', 1
        )
        with self.assertRaisesRegex(GATE.GateError, "unknown"):
            GATE.load_policy(policy.encode("utf-8"))


class TrustedPolicyGeneratorTests(unittest.TestCase):
    def _candidate_copy(
        self,
        parent: Path,
        source: Path = ROOT,
        *,
        include_ignored_bytecode: bool = False,
    ) -> Path:
        candidate = parent / "candidate"
        ignored = (".git",) if include_ignored_bytecode else (".git", "__pycache__", "*.pyc")
        shutil.copytree(source, candidate, ignore=shutil.ignore_patterns(*ignored))
        return candidate

    def test_candidate_copy_excludes_ignored_bytecode_from_ordinary_fixtures(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "ordinary.txt").write_text("ordinary", encoding="utf-8")
            bytecode = source / "scripts/__pycache__/ambient.cpython-312.pyc"
            bytecode.parent.mkdir(parents=True)
            bytecode.write_bytes(b"\xff\x00ambient-bytecode")
            candidate_parent = root / "copy"
            candidate_parent.mkdir()

            candidate = self._candidate_copy(candidate_parent, source)

            self.assertEqual((candidate / "ordinary.txt").read_text(encoding="utf-8"), "ordinary")
            self.assertEqual(list(candidate.rglob("*.pyc")), [])

    def test_candidate_copy_retains_non_utf8_bytecode_rejection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = root / "candidate.cpython-312.pyc"
            payload.write_bytes(b"\xff\x00candidate-bytecode")
            source_parent = root / "source"
            source_parent.mkdir()
            source = self._candidate_copy(source_parent)
            source_scripts = source / "scripts"
            source_scripts.chmod(0o700)
            bytecode = source_scripts / "__pycache__/candidate.cpython-312.pyc"
            bytecode.parent.mkdir(exist_ok=True)
            shutil.copyfile(payload, bytecode)
            candidate_parent = root / "copy"
            candidate_parent.mkdir()
            candidate = self._candidate_copy(
                candidate_parent,
                source,
                include_ignored_bytecode=True,
            )
            copied_bytecode = candidate / bytecode.relative_to(source)
            self.assertEqual(
                {path.relative_to(candidate) for path in candidate.rglob("*.pyc")},
                {bytecode.relative_to(source)},
            )
            self.assertEqual(copied_bytecode.read_bytes(), payload.read_bytes())
            baseline_sha256 = GENERATOR.sha256(POLICY.read_bytes())
            with self.assertRaisesRegex(
                GENERATOR.ProposalError, "unreadable or not UTF-8"
            ):
                GENERATOR.generate(candidate, None, POLICY, baseline_sha256)

    def test_changed_protected_state_requires_a_strictly_greater_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = self._candidate_copy(Path(directory))
            baseline = Path(directory).parent / (Path(directory).name + "-baseline.json")
            baseline.write_bytes(POLICY.read_bytes())
            baseline_sha256 = GENERATOR.sha256(baseline.read_bytes())
            skill = candidate / "skills/orchestrate-task/SKILL.md"
            skill.chmod(0o600)
            skill.write_text(skill.read_text(encoding="utf-8") + "\nchanged\n", encoding="utf-8")
            current = GATE.load_policy((candidate / ".github/ci/trusted_validation_policy.json").read_bytes())["policy_version"]
            with self.assertRaisesRegex(GENERATOR.ProposalError, "policy version must increase"):
                GENERATOR.generate(candidate, current, baseline, baseline_sha256)
            proposal = GENERATOR.generate(candidate, current + 1, baseline, baseline_sha256)
            self.assertEqual(GATE.load_policy(proposal)["policy_version"], current + 1)

    def test_trusted_controls_and_carried_policy_inputs_require_version_bump(self) -> None:
        current = GATE.load_policy(POLICY.read_bytes())["policy_version"]
        baseline_sha256 = GENERATOR.sha256(POLICY.read_bytes())
        mutations = (
            (".github/ci/trusted_invariant_gate.py", lambda path: path.write_text(path.read_text(encoding="utf-8") + "\nchanged\n", encoding="utf-8")),
            (".github/ci/run_sandboxed_validation.py", lambda path: path.write_text(path.read_text(encoding="utf-8") + "\nchanged\n", encoding="utf-8")),
        )
        for relative_path, mutate in mutations:
            with self.subTest(relative_path=relative_path), tempfile.TemporaryDirectory() as directory:
                candidate = self._candidate_copy(Path(directory))
                target = candidate / relative_path
                target.chmod(0o600)
                mutate(target)
                with self.assertRaisesRegex(GENERATOR.ProposalError, "protected validation state changed"):
                    GENERATOR.generate(candidate, None, POLICY, baseline_sha256)
        with tempfile.TemporaryDirectory() as directory:
            candidate = self._candidate_copy(Path(directory))
            target = candidate / ".github/ci/trusted_invariant_gate.py"
            target.chmod(0o600)
            target.write_text(target.read_text(encoding="utf-8") + "\nchanged\n", encoding="utf-8")
            policy_path = candidate / ".github/ci/trusted_validation_policy.json"
            policy_path.chmod(0o600)
            policy = json.loads(policy_path.read_text(encoding="utf-8"))
            policy["trusted_copy_sha256"][".github/ci/trusted_invariant_gate.py"] = GENERATOR.sha256(target.read_bytes())
            policy_path.write_text(json.dumps(policy, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(GENERATOR.ProposalError, "protected validation state changed"):
                GENERATOR.generate(candidate, None, POLICY, baseline_sha256)
        with tempfile.TemporaryDirectory() as directory:
            candidate = self._candidate_copy(Path(directory))
            policy_path = candidate / ".github/ci/trusted_validation_policy.json"
            policy_path.chmod(0o600)
            policy = json.loads(policy_path.read_text(encoding="utf-8"))
            policy["checkout_action"] = "actions/checkout@" + "0" * 40
            policy["policy_input_sha256"] = GENERATOR.policy_input_sha256(policy)
            policy_path.write_text(json.dumps(policy, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(GENERATOR.ProposalError, "protected validation state changed"):
                GENERATOR.generate(candidate, None, POLICY, baseline_sha256)

    @unittest.skipIf(os.environ.get("AWB_READ_ONLY_EXPORT_TEST") == "1", "policy regeneration requires preserved executable modes")
    def test_export_baseline_must_be_independent_and_identity_bound(self) -> None:
        current = GATE.load_policy(POLICY.read_bytes())["policy_version"]
        baseline_sha256 = GENERATOR.sha256(POLICY.read_bytes())
        with tempfile.TemporaryDirectory() as directory:
            candidate = self._candidate_copy(Path(directory))
            candidate_policy = candidate / ".github/ci/trusted_validation_policy.json"
            with self.assertRaisesRegex(GENERATOR.ProposalError, "outside the candidate checkout"):
                GENERATOR.generate(candidate, current, candidate_policy, baseline_sha256)
            with self.assertRaisesRegex(GENERATOR.ProposalError, "reviewed 64-character"):
                GENERATOR.generate(candidate, current, POLICY)
            with self.assertRaisesRegex(GENERATOR.ProposalError, "does not match"):
                GENERATOR.generate(candidate, current, POLICY, "0" * 64)
            proposal = GENERATOR.generate(candidate, current, POLICY, baseline_sha256)
            self.assertEqual(GATE.load_policy(proposal)["policy_version"], current)

    @unittest.skipIf(os.environ.get("AWB_READ_ONLY_EXPORT_TEST") == "1", "policy regeneration requires preserved executable modes")
    def test_current_generated_policy_is_bounded_and_gate_loadable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = self._candidate_copy(root)
            baseline = root / "baseline.json"
            baseline.write_bytes(POLICY.read_bytes())
            policy = GENERATOR.generate(
                candidate,
                GATE.load_policy(POLICY.read_bytes())["policy_version"],
                baseline,
                GENERATOR.sha256(baseline.read_bytes()),
            )
        self.assertLessEqual(len(policy), GENERATOR.MAX_POLICY_BYTES)
        self.assertEqual(GATE.load_policy(policy)["schema_version"], 2)

    def test_generated_policy_protects_canonical_test_modules(self) -> None:
        current = GATE.load_policy(POLICY.read_bytes())["policy_version"]
        baseline_sha256 = GENERATOR.sha256(POLICY.read_bytes())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = self._candidate_copy(root)
            baseline = root / "baseline.json"
            baseline.write_bytes(POLICY.read_bytes())
            proposal = GATE.load_policy(
                GENERATOR.generate(candidate, current + 1, baseline, baseline_sha256)
            )
        inventory = {entry["path"] for entry in proposal["protected_surface_inventory"]}
        self.assertEqual(proposal["protected_surface_roots"], list(GENERATOR.PROTECTED_ROOTS))
        for path in (
            "tests/test_verify_repository.py",
            "tests/test_ci_sandbox.py",
            "tests/test_code_review_scope.py",
        ):
            self.assertIn(path, inventory)
            self.assertIn(path, proposal["pinned_candidate_files"])


if __name__ == "__main__":
    unittest.main()
