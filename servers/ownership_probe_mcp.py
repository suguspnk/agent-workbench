#!/usr/bin/python3 -I
"""Minimal read-only MCP server for bounded ownership-artifact metadata scans."""

from __future__ import annotations

import json
import os
import re
import stat
import sys
import time
from typing import Any, Dict, List, Optional, Tuple


SERVER_NAME = "agent-workbench-ownership-probe"
SERVER_VERSION = "1.1.0"
TOOL_NAME = "scan_required_artifacts"
ADAPTER_RESULT_VERSION = 1
DESCRIPTOR_VERSION = 4
# Updated only with the protected descriptor in route_subagent.py and portable-contract.md.
DESCRIPTOR_SHA256 = "4a5993ebc44201cbc76ab0ea2e5411d2bf4e5d923b39383c94388e3f7de38e08"
MAX_CLASSES = 3
MAX_MATCHES_PER_CLASS = 64
MAX_DEPTH = 32
MAX_ENTRIES = 50_000
DEADLINE_SECONDS = 45
STABILITY_PASSES = 2
METADATA_TOKEN_FIELDS = (
    "st_dev", "st_ino", "st_mode", "st_nlink", "st_uid", "st_gid", "st_size", "st_mtime_ns", "st_ctime_ns",
)
STABILITY_COMPARISON = "byte-identical-canonical-metadata-receipts-and-query-results"
STABILITY_FAILURE_ACTION = "all-query-results-incomplete"

EXCLUDED_DIRECTORY_NAMES = frozenset(
    {".git", ".hg", ".svn", ".tox", ".venv", "__pycache__", "node_modules", "vendor"}
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
    "description": "Scan the startup workspace for three protected deployment-artifact classes using bounded path metadata only.",
    "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
}


def _query_results() -> List[Dict[str, Any]]:
    return [{
        "artifact_class": artifact_class,
        "complete": True,
        "truncated": False,
        "symlink_encountered": False,
        "symlinks_followed": False,
        "matches": [],
    } for artifact_class in ARTIFACT_PATTERNS]


def _mark_incomplete(results: List[Dict[str, Any]], truncated: bool = False) -> None:
    for result in results:
        result["complete"] = False
        if truncated:
            result["truncated"] = True


def _mark_symlink(results: List[Dict[str, Any]]) -> None:
    for result in results:
        result["symlink_encountered"] = True
        result["complete"] = False


def _supports_secure_scan() -> bool:
    if os.name != "posix" or any(not hasattr(os, name) for name in ("O_DIRECTORY", "O_NOFOLLOW")):
        return False
    return os.open in os.supports_dir_fd and os.stat in os.supports_dir_fd and os.stat in os.supports_follow_symlinks


def _metadata_token(metadata: os.stat_result) -> List[int]:
    return [int(getattr(metadata, field)) for field in METADATA_TOKEN_FIELDS]


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _scan_pass(deadline: float, entries_seen: int) -> Tuple[List[Dict[str, Any]], bytes, int]:
    results = _query_results()
    directory_receipts: List[Dict[str, Any]] = []
    root_fd: Optional[int] = None
    stack: List[Tuple[int, str, int, Optional[List[int]]]] = []
    try:
        root_fd = os.open(".", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        stack.append((root_fd, "", 0, None))
        root_fd = None
        while stack:
            directory_fd, prefix, depth, expected_token = stack.pop()
            children: List[Tuple[int, str, int, Optional[List[int]]]] = []
            try:
                if time.monotonic() >= deadline:
                    _mark_incomplete(results, truncated=True)
                    break
                before_token = _metadata_token(os.fstat(directory_fd))
                if expected_token is not None and before_token != expected_token:
                    _mark_incomplete(results)
                try:
                    names = sorted(os.listdir(directory_fd))
                except OSError:
                    _mark_incomplete(results)
                    names = []
                entry_receipts: List[List[Any]] = []
                for name in names:
                    entries_seen += 1
                    if entries_seen > MAX_ENTRIES or time.monotonic() >= deadline:
                        _mark_incomplete(results, truncated=True)
                        break
                    if not name or name in {".", ".."} or "/" in name or "\x00" in name:
                        _mark_incomplete(results)
                        continue
                    relative_path = "%s/%s" % (prefix, name) if prefix else name
                    try:
                        metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                    except OSError:
                        _mark_incomplete(results)
                        continue
                    token = _metadata_token(metadata)
                    entry_receipts.append([name, token])
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
                            child_fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory_fd)
                        except OSError:
                            _mark_incomplete(results)
                            continue
                        children.append((child_fd, relative_path, depth + 1, token))
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
                after_token = _metadata_token(os.fstat(directory_fd))
                if before_token != after_token:
                    _mark_incomplete(results)
                directory_receipts.append({"path": prefix, "before": before_token, "entries": entry_receipts, "after": after_token})
                for child in reversed(children):
                    stack.append(child)
            except OSError:
                _mark_incomplete(results)
            finally:
                os.close(directory_fd)
        if stack:
            _mark_incomplete(results, truncated=True)
    except OSError:
        _mark_incomplete(results)
    finally:
        if root_fd is not None:
            os.close(root_fd)
        for directory_fd, _prefix, _depth, _expected in stack:
            try:
                os.close(directory_fd)
            except OSError:
                pass
    for result in results:
        result["matches"].sort()
    directory_receipts.sort(key=lambda receipt: receipt["path"])
    return results, _canonical_bytes({"directories": directory_receipts, "query_results": results}), entries_seen


def scan_required_artifacts() -> Dict[str, Any]:
    """Scan startup-cwd metadata twice without following links or reading contents."""
    workspace_identity = os.path.realpath(os.getcwd())
    if not _supports_secure_scan():
        results = _query_results()
        _mark_incomplete(results)
        return _adapter_result(workspace_identity, results)
    deadline = time.monotonic() + DEADLINE_SECONDS
    entries_seen = 0
    pass_results: List[List[Dict[str, Any]]] = []
    pass_receipts: List[bytes] = []
    for _pass_number in range(STABILITY_PASSES):
        results, receipt, entries_seen = _scan_pass(deadline, entries_seen)
        pass_results.append(results)
        pass_receipts.append(receipt)
    final_results = pass_results[-1]
    if (
        any(not all(result["complete"] for result in results) for results in pass_results)
        or len(set(pass_receipts)) != 1
        or len({_canonical_bytes(results) for results in pass_results}) != 1
    ):
        _mark_incomplete(final_results)
    return _adapter_result(workspace_identity, final_results)


def _adapter_result(workspace_identity: str, results: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "adapter_result_version": ADAPTER_RESULT_VERSION,
        "tool_name": TOOL_NAME,
        "descriptor_version": DESCRIPTOR_VERSION,
        "descriptor_sha256": DESCRIPTOR_SHA256,
        "workspace_identity": workspace_identity,
        "query_results": results,
    }


def _error_response(request_id: Any, code: int, message: str) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def handle_request(request: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
        request_id = request.get("id") if isinstance(request, dict) else None
        return _error_response(request_id, -32600, "Invalid Request")
    method = request.get("method")
    request_id = request.get("id")
    if method == "notifications/initialized" and "id" not in request:
        return None
    if "id" not in request:
        return None
    if method == "initialize":
        if not isinstance(request.get("params"), dict):
            return _error_response(request_id, -32602, "Invalid params")
        return {"jsonrpc": "2.0", "id": request_id, "result": {"protocolVersion": "2025-06-18", "capabilities": {"tools": {"listChanged": False}}, "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION}}}
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
        return {"jsonrpc": "2.0", "id": request_id, "result": {"content": [{"type": "text", "text": _canonical_bytes(result).decode("ascii")}], "structuredContent": result, "isError": False}}
    return _error_response(request_id, -32601, "Method not found")


def main() -> int:
    # Isolated mode suppresses PYTHONPATH/user-site; then drop all environment data.
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
