from __future__ import annotations

import importlib
import json
import math
import os
import tempfile
import unittest
from pathlib import Path


class HookDurationTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "state.db"
        self.secret_path = Path(self.temp_dir.name) / "secret.key"
        os.environ["ILH_DB_PATH"] = str(self.db_path)
        os.environ["ILH_SECRET_PATH"] = str(self.secret_path)

        import sys

        repo_root = Path(__file__).resolve().parents[2]
        for path in (repo_root / "mcp", repo_root / "scripts"):
            if str(path) not in sys.path:
                sys.path.insert(0, str(path))
        self.server = importlib.import_module("server")
        self.server = importlib.reload(self.server)
        self.hooks = importlib.import_module("claude_hooks")
        self.hooks = importlib.reload(self.hooks)
        self.bridge = importlib.import_module("opencode_plugin_bridge")
        self.bridge = importlib.reload(self.bridge)
        self.store = self.server.store

    def tearDown(self) -> None:
        self.temp_dir.cleanup()
        os.environ.pop("ILH_DB_PATH", None)
        os.environ.pop("ILH_SECRET_PATH", None)

    def test_claude_hook_records_duration_seconds_from_tool_response_metadata(self) -> None:
        self.server.mission_lock("s1", "duration-task", "goal", ["criterion"], time_budget_minutes=1)
        event = {
            "session_id": "s1",
            "tool_name": "Bash",
            "tool_input": {"command": "python long_running.py"},
            "tool_response": {
                "exit_code": 0,
                "stdout": "ok",
                "stderr": "",
                "metadata": {"duration_seconds": 90},
            },
            "hook_event_name": "PostToolUse",
        }

        result = self.hooks.post_tool_use(event)

        self.assertEqual(result, 0)
        receipt = self.store.list_recent_receipts("s1", "duration-task", limit=1)[0]
        self.assertEqual(receipt.metadata["duration_seconds"], 90)
        status = json.loads(self.server.budget_status("s1", "duration-task"))
        self.assertEqual(status["receipt_duration_minutes"], 1)

    def test_opencode_bridge_normalizes_duration_milliseconds_to_seconds(self) -> None:
        self.server.mission_lock("s1", "opencode-duration-task", "goal", ["criterion"])
        result = self.bridge.post_tool_use(
            {
                "session_id": "s1",
                "cwd": self.temp_dir.name,
                "tool_name": "bash",
                "tool_input": {"command": "pytest -q"},
                "tool_response": {
                    "output": "ok",
                    "metadata": {"exitCode": 0, "durationMs": 65000},
                },
            }
        )

        self.assertTrue(result["recorded"])
        receipt = self.store.list_recent_receipts("s1", "opencode-duration-task", limit=1)[0]
        self.assertEqual(receipt.metadata["duration_seconds"], 65)

    def test_opencode_bridge_preserves_top_level_duration_milliseconds(self) -> None:
        self.server.mission_lock("s1", "opencode-top-duration-task", "goal", ["criterion"])
        result = self.bridge.post_tool_use(
            {
                "session_id": "s1",
                "cwd": self.temp_dir.name,
                "tool_name": "bash",
                "tool_input": {"command": "pytest -q"},
                "tool_response": {"output": "ok", "durationMs": 120000},
            }
        )

        self.assertTrue(result["recorded"])
        receipt = self.store.list_recent_receipts("s1", "opencode-top-duration-task", limit=1)[0]
        self.assertEqual(receipt.metadata["duration_seconds"], 120)

    def test_opencode_plugin_passes_measured_duration_to_bridge(self) -> None:
        plugin_path = Path(__file__).resolve().parents[2] / ".opencode" / "plugins" / "agent-runway.js"
        plugin_text = plugin_path.read_text(encoding="utf-8")

        self.assertIn("Date.now()", plugin_text)
        self.assertIn("durationMs", plugin_text)
        self.assertIn("??", plugin_text)

    def test_non_numeric_duration_metadata_is_not_recorded(self) -> None:
        self.server.mission_lock("s1", "bad-duration-task", "goal", ["criterion"])
        event = {
            "session_id": "s1",
            "tool_name": "Bash",
            "tool_input": {"command": "python verify.py"},
            "tool_response": {
                "exit_code": 0,
                "stdout": "ok",
                "stderr": "",
                "metadata": {"duration_seconds": "90"},
            },
            "hook_event_name": "PostToolUse",
        }

        self.assertEqual(self.hooks.post_tool_use(event), 0)

        receipt = self.store.list_recent_receipts("s1", "bad-duration-task", limit=1)[0]
        self.assertNotIn("duration_seconds", receipt.metadata)

    def test_boolean_duration_metadata_is_not_recorded(self) -> None:
        self.server.mission_lock("s1", "bool-duration-task", "goal", ["criterion"])
        event = {
            "session_id": "s1",
            "tool_name": "Bash",
            "tool_input": {"command": "python verify.py"},
            "tool_response": {
                "exit_code": 0,
                "stdout": "ok",
                "stderr": "",
                "metadata": {"duration_seconds": True},
            },
            "hook_event_name": "PostToolUse",
        }

        self.assertEqual(self.hooks.post_tool_use(event), 0)

        receipt = self.store.list_recent_receipts("s1", "bool-duration-task", limit=1)[0]
        self.assertNotIn("duration_seconds", receipt.metadata)

    def test_negative_duration_metadata_is_not_recorded(self) -> None:
        self.server.mission_lock("s1", "negative-duration-task", "goal", ["criterion"])
        event = {
            "session_id": "s1",
            "tool_name": "Bash",
            "tool_input": {"command": "python verify.py"},
            "tool_response": {
                "exit_code": 0,
                "stdout": "ok",
                "stderr": "",
                "metadata": {"durationMs": -1},
            },
            "hook_event_name": "PostToolUse",
        }

        self.assertEqual(self.hooks.post_tool_use(event), 0)

        receipt = self.store.list_recent_receipts("s1", "negative-duration-task", limit=1)[0]
        self.assertNotIn("duration_seconds", receipt.metadata)

    def test_non_finite_duration_metadata_is_not_recorded(self) -> None:
        self.server.mission_lock("s1", "infinite-duration-task", "goal", ["criterion"])
        event = {
            "session_id": "s1",
            "tool_name": "Bash",
            "tool_input": {"command": "python verify.py"},
            "tool_response": {
                "exit_code": 0,
                "stdout": "ok",
                "stderr": "",
                "metadata": {"duration_seconds": math.inf},
            },
            "hook_event_name": "PostToolUse",
        }

        self.assertEqual(self.hooks.post_tool_use(event), 0)

        receipt = self.store.list_recent_receipts("s1", "infinite-duration-task", limit=1)[0]
        self.assertNotIn("duration_seconds", receipt.metadata)


if __name__ == "__main__":
    unittest.main()
