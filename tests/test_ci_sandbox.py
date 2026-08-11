from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / ".github/ci/run_sandboxed_validation.py"
SPEC = importlib.util.spec_from_file_location("run_sandboxed_validation", HELPER)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load sandbox helper")
CI = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CI
SPEC.loader.exec_module(CI)
EXPECTED_IMAGES = {
    "3.11": "python:3.11.15-slim-bookworm@sha256:77923445c077d8eb971b14b2b114a1d9cd4a87edb4c75654820ca4832ee8cb15",
    "3.12": "python:3.12.13-slim-bookworm@sha256:72d3d75f2639ab82b34b29390ad3d6e0827c775befee94edda8e9976818f488d",
}


class SandboxCommandTests(unittest.TestCase):
    def test_reviewed_image_allowlist_is_exact(self) -> None:
        self.assertEqual(CI.ALLOWED_IMAGES, EXPECTED_IMAGES)
        workflow = (ROOT / ".github/workflows/validate.yml").read_text(encoding="utf-8")
        for image in EXPECTED_IMAGES.values():
            self.assertEqual(workflow.count(image), 1)

    def test_workflow_keeps_trusted_and_candidate_boundaries_separate(self) -> None:
        workflow = (ROOT / ".github/workflows/validate.yml").read_text(encoding="utf-8")
        self.assertIn("permissions:\n  contents: read\n\nconcurrency:", workflow)
        self.assertEqual(workflow.count("persist-credentials: false"), 2)
        self.assertEqual(workflow.count("actions/checkout@11d5960a326750d5838078e36cf38b85af677262"), 2)
        self.assertIn("refs/pull/{0}/merge", workflow)
        self.assertIn("python3 -I trusted/.github/ci/run_sandboxed_validation.py", workflow)
        for forbidden in ("actions/setup-python@", "actions/cache@", "actions/upload-artifact@", "secrets.", "github.token"):
            self.assertNotIn(forbidden, workflow)

    def test_command_has_exact_isolation_contract_and_minimal_environment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory).resolve()
            image = CI.ALLOWED_IMAGES["3.11"]
            command = CI.build_docker_command(candidate, image, "3.11", "awb-validation-0123456789abcdefabcd")

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
        self.assertEqual(command[-6:], [image, "/usr/local/bin/python", "-I", "/opt/awb/run_validation.py", "--inside", "--expected-python", "3.11"][-6:])

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
            self.assertEqual(CI.validate_inputs(CI.ALLOWED_IMAGES["3.12"], "3.12", workspace, sha, name), Path(workspace))
            cases = (
                ("python:3.12-slim", "3.12", workspace, sha, name),
                (CI.ALLOWED_IMAGES["3.12"], "3.11", workspace, sha, name),
                (CI.ALLOWED_IMAGES["3.12"], "3.12", workspace, "A" * 40, name),
                (CI.ALLOWED_IMAGES["3.12"], "3.12", workspace, sha, "unsafe-name"),
            )
            for arguments in cases:
                with self.subTest(arguments=arguments), self.assertRaises(CI.SandboxError):
                    CI.validate_inputs(*arguments)

    def test_safe_child_environment_excludes_sensitive_parent_values(self) -> None:
        with mock.patch.dict(os.environ, {"GITHUB_TOKEN": "parent-secret", "HTTPS_PROXY": "http://proxy"}, clear=False):
            self.assertNotIn("GITHUB_TOKEN", CI.SAFE_CHILD_ENV)
            self.assertNotIn("HTTPS_PROXY", CI.SAFE_CHILD_ENV)
            self.assertNotIn("parent-secret", CI._host_environment().values())


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
                                CI.host_main(workspace, "a" * 40, CI.ALLOWED_IMAGES["3.11"], "3.11")
                        elif outcome.returncode or outcome.timed_out:
                            with self.assertRaises(CI.SandboxError):
                                CI.host_main(workspace, "a" * 40, CI.ALLOWED_IMAGES["3.11"], "3.11")
                        else:
                            CI.host_main(workspace, "a" * 40, CI.ALLOWED_IMAGES["3.11"], "3.11")
                    self.assertEqual(bounded.call_count, 2)


class InsidePreflightTests(unittest.TestCase):
    def test_preflight_rejects_root_wrong_python_forbidden_env_and_extra_interface(self) -> None:
        expected = f"{sys.version_info.major}.{sys.version_info.minor}"
        with mock.patch.object(CI.os, "geteuid", return_value=0):
            with self.assertRaises(CI.SandboxError):
                CI.inside_container_main(expected)
        with mock.patch.object(CI.os, "geteuid", return_value=65532), mock.patch.object(CI.os, "getegid", return_value=65532):
            with self.assertRaises(CI.SandboxError):
                CI.inside_container_main("0.0")
        with (
            mock.patch.object(CI.os, "geteuid", return_value=65532),
            mock.patch.object(CI.os, "getegid", return_value=65532),
            mock.patch.dict(CI.os.environ, {**CI.SAFE_CHILD_ENV, "GITHUB_TOKEN": "secret"}, clear=True),
        ):
            with self.assertRaises(CI.SandboxError):
                CI.inside_container_main(expected)
        with (
            mock.patch.object(CI.os, "geteuid", return_value=65532),
            mock.patch.object(CI.os, "getegid", return_value=65532),
            mock.patch.dict(CI.os.environ, CI.SAFE_CHILD_ENV, clear=True),
            mock.patch.object(CI.Path, "iterdir", return_value=iter((Path("/lo"), Path("/eth0")))),
        ):
            with self.assertRaises(CI.SandboxError):
                CI.inside_container_main(expected)

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
                CI.inside_container_main(expected)
        self.assertEqual(execute.call_args.args[0], "/usr/local/bin/python")
        self.assertEqual(execute.call_args.args[2], CI.SAFE_CHILD_ENV)


if __name__ == "__main__":
    unittest.main()
