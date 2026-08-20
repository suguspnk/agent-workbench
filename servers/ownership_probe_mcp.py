#!/usr/bin/env python3
"""Minimal read-only MCP server for bounded ownership-artifact metadata scans."""

from __future__ import annotations

import json
import os
import re
import stat
import sys
import time
from typing import Any


SERVER_NAME = "agent-workbench-ownership-probe"
SERVER_VERSION = "1.0.0"
TOOL_NAME = "scan_required_artifacts"
ADAPTER_RESULT_VERSION = 1
DESCRIPTOR_VERSION = 3
# Updated only with the protected descriptor in route_subagent.py and portable-contract.md.
DESCRIPTOR_SHA256 = "8e4fbe2315ec2ac0427c74dbcd03c67eb4980e5d542cc33f5e6c851ed4fb6029"
MAX_CLASSES = 3
MAX_MATCHES_PER_CLASS = 64
MAX_DEPTH = 32
MAX_ENTRIES = 50_000
DEADLINE_SECONDS = 45

EXCLUDED_DIRECTORY_NAMES = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".tox",
        ".venv",
        "__pycache__",
        "node_modules",
        "vendor",
    }
)

ARTIFACT_PATTERNS = {
    "ecs-task-definition-manifests": re.compile(
        r"(?:[A-Za-z0-9._@+-]+/)*(?:[A-Za-z0-9][A-Za-z0-9._-]*[-_])?"
        r"task[-_]definitions?(?:[-_.][A-Za-z0-9][A-Za-z0-9._-]*)?\.(?:json|yaml|yml)\Z"
    ),
    "deployment-pipeline-manifests": re.compile(
        r"(?:[A-Za-z0-9._@+-]+/)*(?:\.github/workflows/[A-Za-z0-9._-]+\.(?:ya?ml)|"
        r"(?:[A-Za-z0-9][A-Za-z0-9._-]*[-_])?bitbucket-pipelines"
        r"(?:[-_.][A-Za-z0-9][A-Za-z0-9._-]*)?\.(?:yaml|yml)|"
        r"(?:[A-Za-z0-9][A-Za-z0-9._-]*[-_])?(?:cloudbuild|buildspec)"
        r"(?:[-_.][A-Za-z0-9][A-Za-z0-9._-]*)?\.(?:json|yaml|yml)|"
        r"(?:[A-Za-z0-9][A-Za-z0-9._-]*[-_])?pipeline"
        r"(?:[-_.][A-Za-z0-9][A-Za-z0-9._-]*)?\.(?:json|yaml|yml|groovy)|"
        r"(?:[A-Za-z0-9][A-Za-z0-9._-]*[-_])?Jenkinsfile"
        r"(?:[-_][A-Za-z0-9][A-Za-z0-9._-]*)?(?:\.groovy)?)\Z"
    ),
    "infrastructure-as-code": re.compile(
        r"(?:[A-Za-z0-9._@+-]+/)*(?:[A-Za-z0-9._-]+\.tf(?:\.json)?|cdk\.json|"
        r"Pulumi[A-Za-z0-9._-]*\.ya?ml|"
        r"(?:serverless|sam|cloudformation|template)[A-Za-z0-9._-]*\.ya?ml)\Z"
    ),
}

TOOL_DEFINITION = {
    "name": TOOL_NAME,
    "description": (
        "Scan the startup workspace for three protected deployment-artifact classes using "
        "bounded path metadata only."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
    "annotations": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
}


def _query_results() -> list[dict[str, Any]]:
    return [
        {
            "artifact_class": artifact_class,
            "complete": True,
            "truncated": False,
            "symlink_encountered": False,
            "symlinks_followed": False,
            "matches": [],
        }
        for artifact_class in ARTIFACT_PATTERNS
    ]


def _mark_incomplete(results: list[dict[str, Any]], *, truncated: bool = False) -> None:
    for result in results:
        result["complete"] = False
        if truncated:
            result["truncated"] = True


def _mark_symlink(results: list[dict[str, Any]]) -> None:
    for result in results:
        result["symlink_encountered"] = True
        result["complete"] = False


def _supports_secure_scan() -> bool:
    required_flags = ("O_DIRECTORY", "O_NOFOLLOW")
    if os.name != "posix" or any(not hasattr(os, name) for name in required_flags):
        return False
    return (
        os.open in os.supports_dir_fd
        and os.stat in os.supports_dir_fd
        and os.stat in os.supports_follow_symlinks
    )


def scan_required_artifacts() -> dict[str, Any]:
    """Scan only startup-cwd path metadata without following links or reading contents."""
    workspace_identity = os.path.realpath(os.getcwd())
    results = _query_results()
    if not _supports_secure_scan():
        _mark_incomplete(results)
        return _adapter_result(workspace_identity, results)

    deadline = time.monotonic() + DEADLINE_SECONDS
    entries_seen = 0
    root_fd: int | None = None
    stack: list[tuple[int, str, int]] = []
    try:
        root_fd = os.open(
            ".",
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
        )
        stack.append((root_fd, "", 0))
        root_fd = None
        while stack:
            directory_fd, prefix, depth = stack.pop()
            try:
                if time.monotonic() >= deadline:
                    _mark_incomplete(results, truncated=True)
                    break
                try:
                    names = sorted(os.listdir(directory_fd), reverse=True)
                except OSError:
                    _mark_incomplete(results)
                    continue
                for name in names:
                    entries_seen += 1
                    if entries_seen > MAX_ENTRIES or time.monotonic() >= deadline:
                        _mark_incomplete(results, truncated=True)
                        stack.clear()
                        break
                    if not name or name in {".", ".."} or "/" in name or "\x00" in name:
                        _mark_incomplete(results)
                        continue
                    relative_path = f"{prefix}/{name}" if prefix else name
                    try:
                        metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                    except OSError:
                        _mark_incomplete(results)
                        continue
                    if stat.S_ISLNK(metadata.st_mode):
                        _mark_symlink(results)
                        continue
                    if stat.S_ISDIR(metadata.st_mode):
                        if name in EXCLUDED_DIRECTORY_NAMES:
                            continue
                        if depth >= MAX_DEPTH:
                            _mark_incomplete(results, truncated=True)
                            continue
                        try:
                            child_fd = os.open(
                                name,
                                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                dir_fd=directory_fd,
                            )
                        except OSError:
                            _mark_incomplete(results)
                            continue
                        stack.append((child_fd, relative_path, depth + 1))
                        continue
                    if not stat.S_ISREG(metadata.st_mode):
                        _mark_incomplete(results)
                        continue
                    for result in results:
                        pattern = ARTIFACT_PATTERNS[result["artifact_class"]]
                        if pattern.fullmatch(relative_path) is None:
                            continue
                        if len(result["matches"]) >= MAX_MATCHES_PER_CLASS:
                            result["complete"] = False
                            result["truncated"] = True
                        else:
                            result["matches"].append(relative_path)
            finally:
                os.close(directory_fd)
    except OSError:
        _mark_incomplete(results)
    finally:
        if root_fd is not None:
            os.close(root_fd)
        for directory_fd, _prefix, _depth in stack:
            try:
                os.close(directory_fd)
            except OSError:
                pass

    for result in results:
        result["matches"].sort()
    return _adapter_result(workspace_identity, results)


def _adapter_result(workspace_identity: str, results: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "adapter_result_version": ADAPTER_RESULT_VERSION,
        "tool_name": TOOL_NAME,
        "descriptor_version": DESCRIPTOR_VERSION,
        "descriptor_sha256": DESCRIPTOR_SHA256,
        "workspace_identity": workspace_identity,
        "query_results": results,
    }


def _error_response(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def handle_request(request: Any) -> dict[str, Any] | None:
    if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
        return _error_response(request.get("id") if isinstance(request, dict) else None, -32600, "Invalid Request")
    method = request.get("method")
    request_id = request.get("id")
    if method == "notifications/initialized" and "id" not in request:
        return None
    if "id" not in request:
        return None
    if method == "initialize":
        params = request.get("params")
        if not isinstance(params, dict):
            return _error_response(request_id, -32602, "Invalid params")
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": "2025-06-18",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        }
    if method == "tools/list":
        if request.get("params", {}) != {}:
            return _error_response(request_id, -32602, "Invalid params")
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": [TOOL_DEFINITION]}}
    if method == "tools/call":
        params = request.get("params")
        if not isinstance(params, dict) or set(params) != {"name", "arguments"}:
            return _error_response(request_id, -32602, "Invalid params")
        if params["name"] != TOOL_NAME:
            return _error_response(request_id, -32601, "Unknown tool")
        if params["arguments"] != {}:
            return _error_response(request_id, -32602, "Tool takes no arguments")
        result = scan_required_artifacts()
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "content": [{"type": "text", "text": json.dumps(result, sort_keys=True, separators=(",", ":"))}],
                "structuredContent": result,
                "isError": False,
            },
        }
    return _error_response(request_id, -32601, "Method not found")


def main() -> int:
    # The scanner needs no inherited environment after the interpreter has started.
    os.environ.clear()
    for raw_line in sys.stdin.buffer:
        try:
            request = json.loads(raw_line)
            response = handle_request(request)
        except (UnicodeDecodeError, json.JSONDecodeError):
            response = _error_response(None, -32700, "Parse error")
        except Exception:
            response = _error_response(None, -32603, "Internal error")
        if response is not None:
            encoded = json.dumps(response, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
            sys.stdout.write(encoded + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
