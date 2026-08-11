#!/usr/bin/env python3
"""Run candidate repository validation inside a constrained Docker container."""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import re
import signal
import stat
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


MAX_CAPTURE_BYTES = 65_536
CONTAINER_TIMEOUT_SECONDS = 240
CLEANUP_TIMEOUT_SECONDS = 10
KILL_GRACE_SECONDS = 2
ALLOWED_IMAGES = {
    "3.11": "python:3.11.15-slim-bookworm@sha256:77923445c077d8eb971b14b2b114a1d9cd4a87edb4c75654820ca4832ee8cb15",
    "3.12": "python:3.12.13-slim-bookworm@sha256:72d3d75f2639ab82b34b29390ad3d6e0827c775befee94edda8e9976818f488d",
}
VALIDATION_MODES = frozenset({"trusted-invariants", "candidate-behavior"})
TRUSTED_GATE = Path(__file__).with_name("trusted_invariant_gate.py").resolve()
TRUSTED_POLICY = Path(__file__).with_name("trusted_validation_policy.json").resolve()
TRUSTED_WORKFLOW = (Path(__file__).parents[1] / "workflows/validate.yml").resolve()
SAFE_CHILD_ENV = {
    "HOME": "/tmp",
    "TMPDIR": "/tmp",
    "PATH": "/usr/local/bin:/usr/bin:/bin",
    "LANG": "C.UTF-8",
    "PYTHONDONTWRITEBYTECODE": "1",
    "AWB_CI_SANDBOX": "1",
}
FORBIDDEN_ENV_NAMES = frozenset(
    {
        "GITHUB_TOKEN",
        "GH_TOKEN",
        "ACTIONS_RUNTIME_TOKEN",
        "ACTIONS_ID_TOKEN_REQUEST_TOKEN",
        "ACTIONS_ID_TOKEN_REQUEST_URL",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AZURE_CLIENT_ID",
        "AZURE_CLIENT_SECRET",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "SSH_AUTH_SOCK",
        "SSH_AGENT_PID",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
    }
)
FORBIDDEN_ENV_PREFIXES = ("GITHUB_", "ACTIONS_", "AWS_", "AZURE_", "GOOGLE_", "CLOUD_")
_SAFE_SHA = re.compile(r"[0-9a-f]{40}\Z")
_SAFE_CONTAINER = re.compile(r"awb-validation-[0-9a-f]{20}\Z")
_SAFE_IMAGE = re.compile(r"[A-Za-z0-9._:/@-]+\Z")
_SENSITIVE_PATTERNS = (
    re.compile(r"(?i)(authorization\s*:\s*)(?:bearer\s+)?[^\s,;\x00-\x1f\x7f]+"),
    re.compile(r"(?i)\b((?:github|gh|actions|aws|azure|google|cloud|ssh)[A-Z0-9_]*(?:token|secret|key|password|credential)[A-Z0-9_]*\s*[=:]\s*)[^\s,;\x00-\x1f\x7f]+"),
    re.compile(r"\b(?:gh[opsu]_[A-Za-z0-9_]{16,}|github_pat_[A-Za-z0-9_]{16,})\b"),
    re.compile(r"(?i)(https?://)([^/@\s]+)@"),
)


class SandboxError(RuntimeError):
    """A fail-closed containment error."""


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    output: bytes
    truncated: bool
    timed_out: bool


class _HeadTailCapture:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.head_limit = limit // 2
        self.tail_limit = limit - self.head_limit
        self.head = bytearray()
        self.tail: collections.deque[int] = collections.deque(maxlen=self.tail_limit)
        self.total = 0
        self.lock = threading.Lock()

    def add(self, chunk: bytes) -> None:
        with self.lock:
            self.total += len(chunk)
            remaining = self.head_limit - len(self.head)
            if remaining > 0:
                self.head.extend(chunk[:remaining])
                chunk = chunk[remaining:]
            self.tail.extend(chunk)

    def finish(self) -> tuple[bytes, bool]:
        with self.lock:
            truncated = self.total > self.limit
            if not truncated:
                return bytes(self.head) + bytes(self.tail), False
            marker = b"\n...[output truncated]...\n"
            return bytes(self.head) + marker + bytes(self.tail), True


def _drain(stream: object, capture: _HeadTailCapture) -> None:
    while True:
        chunk = stream.read(16_384)  # type: ignore[attr-defined]
        if not chunk:
            return
        capture.add(chunk)


def _terminate_group(process: subprocess.Popen[bytes], grace: float) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=grace)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    process.wait(timeout=grace)


def run_bounded(
    command: list[str],
    *,
    env: dict[str, str],
    timeout: float,
    max_output: int = MAX_CAPTURE_BYTES,
) -> ProcessResult:
    """Continuously drain a child while retaining bounded head and tail output."""
    capture = _HeadTailCapture(max_output)
    process = subprocess.Popen(
        command,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    assert process.stdout is not None
    reader = threading.Thread(target=_drain, args=(process.stdout, capture), daemon=True)
    reader.start()
    timed_out = False
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _terminate_group(process, KILL_GRACE_SECONDS)
    except BaseException:
        _terminate_group(process, KILL_GRACE_SECONDS)
        raise
    finally:
        reader.join(KILL_GRACE_SECONDS)
        if reader.is_alive():
            _terminate_group(process, KILL_GRACE_SECONDS)
            reader.join(KILL_GRACE_SECONDS)
        process.stdout.close()
    output, truncated = capture.finish()
    return ProcessResult(process.returncode, output, truncated, timed_out)


def sanitize_output(raw: bytes | str, redaction_values: tuple[str, ...] = ()) -> str:
    text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
    for value in sorted((item for item in redaction_values if item), key=len, reverse=True):
        text = text.replace(value, "[REDACTED]")
    for pattern in _SENSITIVE_PATTERNS:
        if pattern.groups:
            text = pattern.sub(r"\1[REDACTED]", text)
        else:
            text = pattern.sub("[REDACTED]", text)
    return json.dumps(text, ensure_ascii=True)[1:-1]


def _safe_existing_directory(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute() or not path.is_dir() or path.is_symlink():
        raise SandboxError("candidate must be an existing absolute non-symlink directory")
    return path.resolve()


def validate_inputs(
    image: str,
    expected_python: str,
    workspace: str,
    expected_sha: str,
    container_name: str,
    validation_mode: str,
) -> Path:
    candidate = _safe_existing_directory(workspace)
    if not _SAFE_SHA.fullmatch(expected_sha):
        raise SandboxError("expected SHA must be exactly 40 lowercase hexadecimal characters")
    if ALLOWED_IMAGES.get(expected_python) != image or not _SAFE_IMAGE.fullmatch(image):
        raise SandboxError("image and Python minor must match the reviewed allowlist")
    if not _SAFE_CONTAINER.fullmatch(container_name):
        raise SandboxError("container name is outside the trusted format")
    if validation_mode not in VALIDATION_MODES:
        raise SandboxError("validation mode is outside the trusted allowlist")
    if validation_mode == "trusted-invariants" and expected_python != "3.12":
        raise SandboxError("trusted invariants require the reviewed Python 3.12 image")
    return candidate


def _host_environment() -> dict[str, str]:
    return {"HOME": "/nonexistent", "PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8"}


def _git(candidate: Path, arguments: list[str]) -> ProcessResult:
    return run_bounded(
        ["/usr/bin/git", "--no-optional-locks", "-C", os.fspath(candidate), *arguments],
        timeout=CLEANUP_TIMEOUT_SECONDS,
        env={"HOME": "/nonexistent", "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "GIT_CONFIG_NOSYSTEM": "1"},
    )


def verify_checkout_credentials(candidate: Path, expected_sha: str) -> None:
    try:
        root_before = candidate.lstat()
    except OSError as error:
        raise SandboxError("candidate checkout cannot be inspected") from error
    if not stat.S_ISDIR(root_before.st_mode) or stat.S_ISLNK(root_before.st_mode):
        raise SandboxError("candidate checkout must remain an ordinary directory")
    head = _git(candidate, ["rev-parse", "--verify", "HEAD"])
    if head.timed_out or head.returncode or head.truncated:
        raise SandboxError("could not verify candidate HEAD")
    try:
        actual_sha = head.output.decode("ascii", "strict").strip()
    except UnicodeDecodeError as error:
        raise SandboxError("candidate HEAD is not ASCII") from error
    if actual_sha != expected_sha:
        raise SandboxError("candidate HEAD does not match the event SHA")

    metadata = candidate / ".git"
    if not metadata.is_dir() or metadata.is_symlink():
        raise SandboxError("candidate checkout must use an ordinary .git directory")
    metadata_before = metadata.lstat()
    for residue in (candidate / ".git-credentials", metadata / ".git-credentials"):
        if residue.exists() or residue.is_symlink():
            raise SandboxError("candidate checkout contains a .git-credentials file")

    config = _git(candidate, ["config", "--local", "--null", "--list"])
    if config.timed_out or config.returncode or config.truncated:
        raise SandboxError("could not safely inspect candidate Git configuration")
    try:
        entries = config.output.decode("utf-8", "strict").split("\0")
    except UnicodeDecodeError as error:
        raise SandboxError("candidate Git configuration is not UTF-8") from error
    for entry in entries:
        if not entry:
            continue
        key, separator, value = entry.partition("\n")
        lowered = key.lower()
        if not separator:
            raise SandboxError("candidate Git configuration has an unsupported entry")
        forbidden_key = (
            (lowered.startswith("http.") and lowered.endswith(".extraheader"))
            or lowered in {"credential.helper", "core.askpass", "core.sshcommand"}
            or (lowered.startswith("credential.") and ("helper" in lowered or "path" in lowered))
        )
        if forbidden_key:
            raise SandboxError("candidate checkout retains a credential-bearing Git setting")
        if lowered.endswith(".url") or lowered.startswith("url."):
            parsed = urlsplit(value)
            if (
                parsed.username is not None
                or parsed.password is not None
                or re.search(r"://[^/@\s]+@", value)
                or re.search(r"://[^/@\s]+@", lowered)
            ):
                raise SandboxError("candidate Git URL contains user information")

    tracked = _git(candidate, ["status", "--porcelain=v1", "--untracked-files=no"])
    if tracked.timed_out or tracked.returncode or tracked.truncated or tracked.output:
        raise SandboxError("candidate checkout has modified tracked files")
    try:
        root_after = candidate.lstat()
        metadata_after = metadata.lstat()
    except OSError as error:
        raise SandboxError("candidate checkout changed during verification") from error
    root_identity_before = (root_before.st_dev, root_before.st_ino, root_before.st_mode)
    root_identity_after = (root_after.st_dev, root_after.st_ino, root_after.st_mode)
    metadata_identity_before = (metadata_before.st_dev, metadata_before.st_ino, metadata_before.st_mode)
    metadata_identity_after = (metadata_after.st_dev, metadata_after.st_ino, metadata_after.st_mode)
    if root_identity_before != root_identity_after or metadata_identity_before != metadata_identity_after:
        raise SandboxError("candidate checkout inode changed during verification")


def _trusted_control_paths(validation_mode: str) -> list[tuple[Path, str]]:
    helper = Path(__file__).resolve()
    controls = [(helper, "/opt/awb/run_validation.py")]
    if validation_mode == "trusted-invariants":
        controls.extend(
            (
                (TRUSTED_GATE, "/opt/awb/trusted_invariant_gate.py"),
                (TRUSTED_POLICY, "/opt/awb/trusted_validation_policy.json"),
                (TRUSTED_WORKFLOW, "/opt/awb/validate.yml"),
            )
        )
    for path, _ in controls:
        try:
            metadata = path.lstat()
        except OSError as error:
            raise SandboxError("trusted validation control is missing") from error
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise SandboxError("trusted validation controls must be regular non-symlink files")
    return controls


def build_docker_command(
    candidate: Path,
    image: str,
    expected_python: str,
    container_name: str,
    validation_mode: str,
) -> list[str]:
    command = [
        "docker", "run", "--name", container_name,
        "--platform=linux/amd64", "--pull=never", "--network=none", "--read-only",
        "--user=65532:65532", "--cap-drop=ALL", "--security-opt=no-new-privileges:true",
        "--pids-limit=128", "--memory=768m", "--memory-swap=768m", "--cpus=2",
        "--ulimit=nofile=1024:1024", "--ipc=none", "--init", "--log-driver=none",
        "--tmpfs=/tmp:rw,nosuid,nodev,noexec,size=268435456,mode=1777",
        "--tmpfs=/workspace/.git:ro,nosuid,nodev,noexec,size=65536,mode=000",
        f"--mount=type=bind,src={candidate},dst=/workspace,readonly",
        "--workdir=/workspace",
    ]
    for source, destination in _trusted_control_paths(validation_mode):
        command.insert(-1, f"--mount=type=bind,src={source},dst={destination},readonly")
    for key, value in SAFE_CHILD_ENV.items():
        command.extend(("--env", f"{key}={value}"))
    command.extend(
        (
            image,
            "/usr/local/bin/python", "-I", "/opt/awb/run_validation.py",
            "--inside", "--validation-mode", validation_mode, "--expected-python", expected_python,
        )
    )
    return command


def _forbidden_environment() -> list[str]:
    forbidden: list[str] = []
    for name in os.environ:
        upper = name.upper()
        if upper in FORBIDDEN_ENV_NAMES or upper.startswith(FORBIDDEN_ENV_PREFIXES):
            forbidden.append(name)
        elif any(fragment in upper for fragment in ("CACHE_URL", "RESULTS_URL", "OIDC", "PROXY")):
            forbidden.append(name)
    return sorted(forbidden)


def inside_container_main(expected_python: str, validation_mode: str) -> None:
    if os.geteuid() == 0 or (os.geteuid(), os.getegid()) != (65532, 65532):
        raise SandboxError("sandbox must run as uid and gid 65532")
    if f"{sys.version_info.major}.{sys.version_info.minor}" != expected_python:
        raise SandboxError("sandbox Python minor differs from the matrix selection")
    if os.environ.get("AWB_CI_SANDBOX") != "1":
        raise SandboxError("sandbox sentinel is missing")
    if validation_mode not in VALIDATION_MODES:
        raise SandboxError("validation mode is outside the trusted allowlist")
    if validation_mode == "trusted-invariants" and expected_python != "3.12":
        raise SandboxError("trusted invariants require Python 3.12")
    forbidden = _forbidden_environment()
    if forbidden:
        raise SandboxError(f"forbidden environment variables are present: {','.join(forbidden)}")
    interfaces = sorted(path.name for path in Path("/sys/class/net").iterdir())
    if interfaces != ["lo"]:
        raise SandboxError("sandbox network namespace exposes a non-loopback interface")
    metadata = Path("/workspace/.git")
    try:
        with os.scandir(metadata) as entries:
            next(entries, None)
    except PermissionError:
        pass
    else:
        raise SandboxError("candidate Git metadata is readable inside the sandbox")
    if validation_mode == "trusted-invariants":
        argv = [
            "/usr/local/bin/python", "-I", "/opt/awb/trusted_invariant_gate.py",
            "--candidate-root", "/workspace",
            "--policy", "/opt/awb/trusted_validation_policy.json",
            "--trusted-gate", "/opt/awb/trusted_invariant_gate.py",
            "--trusted-launcher", "/opt/awb/run_validation.py",
            "--trusted-workflow", "/opt/awb/validate.yml",
        ]
    else:
        argv = ["/usr/local/bin/python", "-I", "/workspace/scripts/verify_repository.py"]
    os.execve(argv[0], argv, dict(SAFE_CHILD_ENV))


def cleanup_container(container_name: str) -> None:
    result = run_bounded(
        ["docker", "rm", "--force", container_name],
        timeout=CLEANUP_TIMEOUT_SECONDS,
        env=_host_environment(),
    )
    if result.timed_out or result.returncode:
        raise SandboxError("container cleanup failed")


def host_main(workspace: str, expected_sha: str, image: str, expected_python: str, validation_mode: str) -> None:
    suffix = hashlib.sha256(f"{os.getpid()}:{time.monotonic_ns()}:{workspace}".encode()).hexdigest()[:20]
    container_name = f"awb-validation-{suffix}"
    candidate = validate_inputs(image, expected_python, workspace, expected_sha, container_name, validation_mode)
    verify_checkout_credentials(candidate, expected_sha)
    command = build_docker_command(candidate, image, expected_python, container_name, validation_mode)
    validation: ProcessResult | None = None
    cleanup_error: BaseException | None = None
    try:
        validation = run_bounded(command, timeout=CONTAINER_TIMEOUT_SECONDS, env=_host_environment())
    finally:
        try:
            cleanup_container(container_name)
        except BaseException as error:
            cleanup_error = error
    if cleanup_error is not None:
        raise SandboxError(str(cleanup_error))
    assert validation is not None
    parent_secrets = tuple(
        value for name, value in os.environ.items()
        if value and (name.upper() in FORBIDDEN_ENV_NAMES or name.upper().startswith(FORBIDDEN_ENV_PREFIXES))
    )
    if validation.timed_out:
        raise SandboxError(f"sandboxed validation timed out; output={sanitize_output(validation.output, parent_secrets)}")
    if validation.returncode:
        raise SandboxError(
            f"sandboxed validation failed with exit {validation.returncode}; "
            f"truncated={validation.truncated}; output={sanitize_output(validation.output, parent_secrets)}"
        )
    if validation_mode == "trusted-invariants":
        print("Trusted repository invariants passed.")
    else:
        print(f"Candidate behavior checks passed for Python {expected_python} (non-authoritative).")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inside", action="store_true")
    parser.add_argument("--candidate")
    parser.add_argument("--expected-sha")
    parser.add_argument("--image")
    parser.add_argument("--validation-mode", choices=sorted(VALIDATION_MODES), required=True)
    parser.add_argument("--expected-python", required=True)
    arguments = parser.parse_args(argv)
    try:
        if arguments.inside:
            inside_container_main(arguments.expected_python, arguments.validation_mode)
        else:
            if not all((arguments.candidate, arguments.expected_sha, arguments.image)):
                raise SandboxError("host mode requires candidate, expected SHA, and image")
            host_main(
                arguments.candidate, arguments.expected_sha, arguments.image,
                arguments.expected_python, arguments.validation_mode,
            )
    except SandboxError as error:
        print(f"ERROR: {sanitize_output(str(error))}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
