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
SERVER_VERSION = "1.3.0"
TOOL_NAME = "scan_required_artifacts"
ADAPTER_RESULT_VERSION = 1
DESCRIPTOR_VERSION = 6
# Updated only with the protected descriptor in route_subagent.py and portable-contract.md.
DESCRIPTOR_SHA256 = "78bbdadf0e8e15509f9262a251666529b8265a09cd656fd32888827c8f8e11c4"
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
ROOT_SOURCE = "one-strict-canonical-local-file-uri-from-full-duplex-mcp-roots-list"
SERVER_CWD = "installed-plugin-root-never-used-as-scan-target"
ROOT_PINNING = "roots-list-path-opened-before-workspace-identity-and-reused-across-both-passes"
WORKSPACE_IDENTITY_BINDING = (
    "canonical-path-and-pinned-root-st-dev-st-ino-revalidated-before-between-and-after-passes"
)
ROOT_REQUEST_ID = "awb_ownership_roots_1"
MAX_INTERLEAVED_ROOT_NOTIFICATIONS = 16
_UNRESERVED_URI_BYTES = frozenset(
    b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
)

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


def _device_inode(metadata: os.stat_result) -> Tuple[int, int]:
    return int(metadata.st_dev), int(metadata.st_ino)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _scan_pass(pinned_root_fd: int, deadline: float, entries_seen: int) -> Tuple[List[Dict[str, Any]], bytes, int]:
    results = _query_results()
    directory_receipts: List[Dict[str, Any]] = []
    root_fd: Optional[int] = None
    stack: List[Tuple[int, str, int, Optional[List[int]]]] = []
    try:
        root_fd = os.dup(pinned_root_fd)
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


def _canonical_file_uri_path(path: str) -> str:
    encoded: List[str] = []
    for byte in path.encode("utf-8"):
        if byte == 0x2F or byte in _UNRESERVED_URI_BYTES:
            encoded.append(chr(byte))
        else:
            encoded.append("%%%02X" % byte)
    return "".join(encoded)


def _strict_local_file_uri(uri: Any) -> str:
    if not isinstance(uri, str) or not uri.startswith("file:///"):
        raise ValueError("workspace root must be a local file URI with no authority")
    if len(uri) > 16_384 or "?" in uri or "#" in uri or "\\" in uri or "\x00" in uri:
        raise ValueError("workspace root URI is not canonical")
    raw_path = uri[len("file://"):]
    decoded = bytearray()
    index = 0
    while index < len(raw_path):
        character = raw_path[index]
        if character == "%":
            if index + 2 >= len(raw_path):
                raise ValueError("workspace root URI has invalid percent encoding")
            pair = raw_path[index + 1:index + 3]
            if not re.fullmatch(r"[0-9A-F]{2}", pair):
                raise ValueError("workspace root URI percent encoding is not canonical")
            byte = int(pair, 16)
            if byte in {0, 0x2F, 0x5C}:
                raise ValueError("workspace root URI contains an encoded separator or NUL")
            decoded.append(byte)
            index += 3
            continue
        ordinal = ord(character)
        if ordinal > 0x7F:
            raise ValueError("workspace root URI must percent-encode non-ASCII bytes")
        decoded.append(ordinal)
        index += 1
    try:
        path = bytes(decoded).decode("utf-8", "strict")
    except UnicodeDecodeError as error:
        raise ValueError("workspace root URI is not valid UTF-8") from error
    if not os.path.isabs(path) or _canonical_file_uri_path(path) != raw_path:
        raise ValueError("workspace root URI is not canonical")
    if os.path.normpath(path) != path or os.path.realpath(path) != path:
        raise ValueError("workspace root path is not canonical")
    return path


def _workspace_uri_from_roots_response(response: Any) -> str:
    if not isinstance(response, dict) or set(response) != {"jsonrpc", "id", "result"}:
        raise ValueError("roots/list response has an invalid schema")
    if response.get("jsonrpc") != "2.0" or response.get("id") != ROOT_REQUEST_ID:
        raise ValueError("roots/list response binding is invalid")
    result = response.get("result")
    if not isinstance(result, dict) or set(result) != {"roots"}:
        raise ValueError("roots/list result has an invalid schema")
    roots = result.get("roots")
    if not isinstance(roots, list) or len(roots) != 1:
        raise ValueError("roots/list must return exactly one root")
    root = roots[0]
    if not isinstance(root, dict) or set(root) not in ({"uri"}, {"uri", "name"}):
        raise ValueError("roots/list root has an invalid schema")
    if "name" in root and not isinstance(root["name"], str):
        raise ValueError("roots/list root name must be a string")
    return _strict_local_file_uri(root.get("uri"))


def _open_workspace_root(workspace_identity: str) -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    return os.open(workspace_identity, flags)


def _workspace_binding_matches(root_fd: int, workspace_identity: str, root_identity: Tuple[int, int]) -> bool:
    try:
        root_metadata = os.fstat(root_fd)
        path_metadata = os.lstat(workspace_identity)
    except (OSError, ValueError):
        return False
    return (
        stat.S_ISDIR(root_metadata.st_mode)
        and stat.S_ISDIR(path_metadata.st_mode)
        and os.path.isabs(workspace_identity)
        and os.path.realpath(workspace_identity) == workspace_identity
        and _device_inode(root_metadata) == root_identity
        and _device_inode(path_metadata) == root_identity
    )


def _bind_workspace_identity(root_fd: int, workspace_identity: str) -> Tuple[str, Tuple[int, int]]:
    root_metadata = os.fstat(root_fd)
    if not stat.S_ISDIR(root_metadata.st_mode):
        raise OSError("startup workspace is not a directory")
    root_identity = _device_inode(root_metadata)
    if not _workspace_binding_matches(root_fd, workspace_identity, root_identity):
        raise OSError("startup workspace identity is not bound to the pinned root")
    return workspace_identity, root_identity


def scan_required_artifacts(roots_response: Any) -> Dict[str, Any]:
    """Scan one MCP workspace root twice without following links or reading contents."""
    workspace_identity = ""
    root_fd: Optional[int] = None
    try:
        workspace_identity = _workspace_uri_from_roots_response(roots_response)
        root_fd = _open_workspace_root(workspace_identity)
        try:
            workspace_identity, root_identity = _bind_workspace_identity(root_fd, workspace_identity)
        except (OSError, ValueError):
            results = _query_results()
            _mark_incomplete(results)
            return _adapter_result(workspace_identity, results)
        if not _supports_secure_scan():
            results = _query_results()
            _mark_incomplete(results)
            return _adapter_result(workspace_identity, results)

        deadline = time.monotonic() + DEADLINE_SECONDS
        entries_seen = 0
        binding_stable = _workspace_binding_matches(root_fd, workspace_identity, root_identity)
        pass_results: List[List[Dict[str, Any]]] = []
        pass_receipts: List[bytes] = []
        for pass_number in range(STABILITY_PASSES):
            results, receipt, entries_seen = _scan_pass(root_fd, deadline, entries_seen)
            pass_results.append(results)
            pass_receipts.append(receipt)
            if pass_number + 1 < STABILITY_PASSES:
                binding_stable = (
                    _workspace_binding_matches(root_fd, workspace_identity, root_identity)
                    and binding_stable
                )
        binding_stable = _workspace_binding_matches(root_fd, workspace_identity, root_identity) and binding_stable
        final_results = pass_results[-1]
        if (
            not binding_stable
            or any(not all(result["complete"] for result in results) for results in pass_results)
            or len(set(pass_receipts)) != 1
            or len({_canonical_bytes(results) for results in pass_results}) != 1
        ):
            _mark_incomplete(final_results)
        return _adapter_result(workspace_identity, final_results)
    except (OSError, ValueError):
        results = _query_results()
        _mark_incomplete(results)
        return _adapter_result(workspace_identity, results)
    finally:
        if root_fd is not None:
            os.close(root_fd)


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


def _tool_call_response(request_id: Any, roots_response: Any) -> Dict[str, Any]:
    result = scan_required_artifacts(roots_response)
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {
            "content": [{"type": "text", "text": _canonical_bytes(result).decode("ascii")}],
            "structuredContent": result,
            "isError": False,
        },
    }


def _client_supports_roots(params: Any) -> bool:
    if not isinstance(params, dict):
        return False
    capabilities = params.get("capabilities")
    if not isinstance(capabilities, dict):
        return False
    roots = capabilities.get("roots")
    return isinstance(roots, dict) and set(roots).issubset({"listChanged"}) and isinstance(
        roots.get("listChanged", False), bool
    )


def _valid_tool_call(request: Any) -> bool:
    if not isinstance(request, dict) or request.get("method") != "tools/call":
        return False
    params = request.get("params")
    return (
        isinstance(params, dict)
        and {"name", "arguments"}.issubset(params)
        and set(params).issubset({"name", "arguments", "_meta"})
        and params.get("name") == TOOL_NAME
        and params.get("arguments") == {}
        and ("_meta" not in params or isinstance(params["_meta"], dict))
    )


def handle_request(
    request: Any,
    client_supports_roots: bool = False,
    roots_response: Any = None,
) -> Optional[Dict[str, Any]]:
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
        # MCP list params are optional. Codex may serialize the empty first
        # page as omitted params, null, or a null cursor, with optional request
        # metadata. Keep the one-tool inventory unpaginated and reject every
        # non-null cursor or unknown field.
        list_params = request.get("params")
        if list_params is not None and (
            not isinstance(list_params, dict)
            or not set(list_params).issubset({"cursor", "_meta"})
            or list_params.get("cursor") is not None
            or ("_meta" in list_params and not isinstance(list_params["_meta"], dict))
        ):
            return _error_response(request_id, -32602, "Invalid params")
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": [TOOL_DEFINITION]}}
    if method == "tools/call":
        params = request.get("params")
        if (
            not isinstance(params, dict)
            or not {"name", "arguments"}.issubset(params)
            or not set(params).issubset({"name", "arguments", "_meta"})
            or ("_meta" in params and not isinstance(params["_meta"], dict))
        ):
            return _error_response(request_id, -32602, "Invalid params")
        if params["name"] != TOOL_NAME:
            return _error_response(request_id, -32601, "Unknown tool")
        if params["arguments"] != {}:
            return _error_response(request_id, -32602, "Tool takes no arguments")
        if not client_supports_roots:
            return _tool_call_response(request_id, None)
        return _tool_call_response(request_id, roots_response)
    return _error_response(request_id, -32601, "Method not found")


def _write_message(message: Dict[str, Any]) -> None:
    encoded = json.dumps(message, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    sys.stdout.write(encoded + "\n")
    sys.stdout.flush()


def _read_roots_response() -> Any:
    for _index in range(MAX_INTERLEAVED_ROOT_NOTIFICATIONS + 1):
        raw_line = sys.stdin.buffer.readline()
        if not raw_line:
            return None
        try:
            response = json.loads(raw_line)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        if isinstance(response, dict) and response.get("id") == ROOT_REQUEST_ID:
            return response
        if not isinstance(response, dict) or "id" in response or not str(response.get("method", "")).startswith(
            "notifications/"
        ):
            return None
    return None


def main() -> int:
    # Isolated mode suppresses PYTHONPATH/user-site; then drop all environment data.
    os.environ.clear()
    roots_supported = False
    for raw_line in sys.stdin.buffer:
        try:
            request = json.loads(raw_line)
            if isinstance(request, dict) and request.get("method") == "initialize":
                roots_supported = _client_supports_roots(request.get("params"))
            roots_response = None
            if roots_supported and _valid_tool_call(request):
                _write_message({
                    "jsonrpc": "2.0",
                    "id": ROOT_REQUEST_ID,
                    "method": "roots/list",
                    "params": {},
                })
                roots_response = _read_roots_response()
            response = handle_request(request, roots_supported, roots_response)
        except (UnicodeDecodeError, json.JSONDecodeError):
            response = _error_response(None, -32700, "Parse error")
        except Exception:
            response = _error_response(None, -32603, "Internal error")
        if response is not None:
            _write_message(response)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
