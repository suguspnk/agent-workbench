from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = ROOT / "servers/ownership_probe_mcp.py"
SPEC = importlib.util.spec_from_file_location("ownership_probe_mcp", SERVER_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load ownership probe MCP server")
SERVER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SERVER)


class OwnershipProbeScannerTests(unittest.TestCase):
    def scan(self, root: Path) -> dict[str, object]:
        old_cwd = Path.cwd()
        try:
            os.chdir(root)
            return SERVER.scan_required_artifacts()
        finally:
            os.chdir(old_cwd)

    def result_map(self, result: dict[str, object]) -> dict[str, dict[str, object]]:
        return {item["artifact_class"]: item for item in result["query_results"]}

    def test_absent_tree_is_complete_and_canonical(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src").mkdir()
            (root / "src/app.py").write_text("not inspected", encoding="utf-8")
            result = self.scan(root)
        self.assertEqual(result["workspace_identity"], str(root.resolve()))
        self.assertEqual(result["tool_name"], "scan_required_artifacts")
        self.assertEqual(result["descriptor_version"], 3)
        for query in result["query_results"]:
            self.assertTrue(query["complete"])
            self.assertFalse(query["truncated"])
            self.assertFalse(query["symlink_encountered"])
            self.assertEqual(query["matches"], [])

    def test_all_three_classes_and_nested_paths_are_detected_without_contents(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = (
                "deploy/service-task-definition.json",
                ".github/workflows/release.yml",
                "infra/main.tf",
            )
            for relative in paths:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("SECRET_CONTENT_MUST_NOT_BE_READ", encoding="utf-8")
            with mock.patch("builtins.open", side_effect=AssertionError("content read forbidden")):
                result = self.scan(root)
        by_class = self.result_map(result)
        self.assertEqual(by_class["ecs-task-definition-manifests"]["matches"], [paths[0]])
        self.assertEqual(by_class["deployment-pipeline-manifests"]["matches"], [paths[1]])
        self.assertEqual(by_class["infrastructure-as-code"]["matches"], [paths[2]])

    def test_more_than_64_matches_is_truncated_and_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index in range(65):
                (root / f"service-{index:02d}-task-definition.json").touch()
            result = self.scan(root)
        query = self.result_map(result)["ecs-task-definition-manifests"]
        self.assertEqual(len(query["matches"]), 64)
        self.assertTrue(query["truncated"])
        self.assertFalse(query["complete"])
        self.assertEqual(query["matches"], sorted(query["matches"]))

    def test_excluded_directories_are_not_scanned(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for excluded in (".git", "node_modules", "vendor", "__pycache__"):
                path = root / excluded / "hidden-task-definition.json"
                path.parent.mkdir(parents=True)
                path.touch()
            result = self.scan(root)
        self.assertEqual(self.result_map(result)["ecs-task-definition-manifests"]["matches"], [])
        self.assertTrue(all(item["complete"] for item in result["query_results"]))

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_symlink_is_never_followed_and_makes_absence_inconclusive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "outside"
            target.mkdir()
            (target / "service-task-definition.json").touch()
            os.symlink(target, root / "linked")
            result = self.scan(root)
        for query in result["query_results"]:
            self.assertFalse(query["complete"])
            self.assertTrue(query["symlink_encountered"])
            self.assertFalse(query["symlinks_followed"])
            self.assertNotIn("linked/service-task-definition.json", query["matches"])

    @unittest.skipUnless(hasattr(os, "mkfifo"), "special files unavailable")
    def test_special_file_makes_scan_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            os.mkfifo(root / "pipeline.yml")
            result = self.scan(root)
        self.assertTrue(any(not item["complete"] for item in result["query_results"]))
        self.assertTrue(all(item["matches"] == [] for item in result["query_results"]))

    def test_platform_absence_and_resource_limits_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "service-task-definition.json").touch()
            with mock.patch.object(SERVER, "_supports_secure_scan", return_value=False):
                unsupported = self.scan(root)
            with mock.patch.object(SERVER, "MAX_ENTRIES", 0):
                capped = self.scan(root)
        self.assertTrue(all(not item["complete"] for item in unsupported["query_results"]))
        self.assertTrue(all(not item["complete"] and item["truncated"] for item in capped["query_results"]))

    def test_stat_race_and_permission_error_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "service-task-definition.json").touch()
            original_stat = SERVER.os.stat

            def racing_stat(path, *args, **kwargs):
                if path == "service-task-definition.json" and "dir_fd" in kwargs:
                    raise FileNotFoundError(path)
                return original_stat(path, *args, **kwargs)

            with mock.patch.object(SERVER.os, "stat", side_effect=racing_stat):
                result = self.scan(root)
        self.assertTrue(all(not item["complete"] for item in result["query_results"]))
        self.assertTrue(all(item["matches"] == [] for item in result["query_results"]))

    def test_source_has_no_process_network_environment_or_write_capability(self) -> None:
        source = SERVER_PATH.read_text(encoding="utf-8")
        for forbidden in (
            "subprocess",
            "socket",
            "urllib",
            "requests",
            "builtins.open",
            ".write_text",
            ".write_bytes",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)
        self.assertIn("os.environ.clear()", source)


class OwnershipProbeMcpProtocolTests(unittest.TestCase):
    def run_protocol(self, requests: list[dict[str, object]], cwd: Path) -> tuple[list[dict[str, object]], str]:
        payload = "".join(json.dumps(request) + "\n" for request in requests)
        environment = {"PATH": os.environ.get("PATH", ""), "AWB_TEST_SECRET": "must-not-appear"}
        result = subprocess.run(
            [sys.executable, str(SERVER_PATH)],
            cwd=cwd,
            input=payload,
            text=True,
            capture_output=True,
            env=environment,
            check=False,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return [json.loads(line) for line in result.stdout.splitlines()], result.stderr

    def test_initialize_notification_list_and_call(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "infra.tf").touch()
            responses, stderr = self.run_protocol(
                [
                    {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                    {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
                    {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
                    {
                        "jsonrpc": "2.0",
                        "id": 3,
                        "method": "tools/call",
                        "params": {"name": "scan_required_artifacts", "arguments": {}},
                    },
                ],
                root,
            )
        self.assertEqual(stderr, "")
        self.assertEqual([item["id"] for item in responses], [1, 2, 3])
        tools = responses[1]["result"]["tools"]
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0]["name"], "scan_required_artifacts")
        self.assertEqual(tools[0]["inputSchema"]["additionalProperties"], False)
        self.assertTrue(tools[0]["annotations"]["readOnlyHint"])
        structured = responses[2]["result"]["structuredContent"]
        self.assertEqual(structured["workspace_identity"], str(root.resolve()))
        self.assertNotIn("must-not-appear", json.dumps(responses))

    def test_unknown_method_tool_and_nonempty_input_fail_without_scanning(self) -> None:
        requests = [
            {"jsonrpc": "2.0", "id": 1, "method": "unknown", "params": {}},
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "other", "arguments": {}},
            },
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "scan_required_artifacts", "arguments": {"path": "/"}},
            },
        ]
        with tempfile.TemporaryDirectory() as directory:
            responses, _stderr = self.run_protocol(requests, Path(directory))
        self.assertEqual([item["error"]["code"] for item in responses], [-32601, -32601, -32602])


if __name__ == "__main__":
    unittest.main()
