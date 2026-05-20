from __future__ import annotations

import importlib
import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
for path in (REPO_ROOT / "mcp", REPO_ROOT / "scripts"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


class HookPayloadEdgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "state.db"
        os.environ["ILH_DB_PATH"] = str(self.db_path)
        self.server = importlib.reload(importlib.import_module("server"))
        self.hooks = importlib.reload(importlib.import_module("claude_hooks"))
        self.store = self.server.store

    def tearDown(self) -> None:
        self.temp_dir.cleanup()
        os.environ.pop("ILH_DB_PATH", None)

    def test_pre_tool_use_denies_non_object_tool_input(self) -> None:
        event = {"tool_name": "Bash", "tool_input": ["git push origin main"]}
        output = io.StringIO()

        with redirect_stdout(output):
            result = self.hooks.pre_tool_use(event)

        self.assertEqual(0, result)
        payload = json.loads(output.getvalue())
        decision = payload["hookSpecificOutput"]
        self.assertEqual("deny", decision["permissionDecision"])
        self.assertIn("tool_input", decision["permissionDecisionReason"])

    def test_record_tool_use_event_rejects_non_object_tool_input_without_receipt(self) -> None:
        self.server.mission_lock("s1", "t1", "goal", ["criterion"])
        result = self.hooks.record_tool_use_event(
            {
                "session_id": "s1",
                "cwd": self.temp_dir.name,
                "tool_name": "Bash",
                "tool_input": ["pytest -q"],
                "tool_response": {"output": "ok"},
            },
            source="claude-hook",
        )

        self.assertFalse(result["recorded"])
        self.assertIn("tool_input", result["reason"])
        self.assertEqual([], self.store.list_recent_receipts("s1", "t1", limit=10))

    def test_record_tool_use_event_rejects_non_object_tool_response_without_receipt(self) -> None:
        self.server.mission_lock("s1", "t1", "goal", ["criterion"])
        result = self.hooks.record_tool_use_event(
            {
                "session_id": "s1",
                "cwd": self.temp_dir.name,
                "tool_name": "Bash",
                "tool_input": {"command": "pytest -q"},
                "tool_response": "ok",
            },
            source="claude-hook",
        )

        self.assertFalse(result["recorded"])
        self.assertIn("tool_response", result["reason"])
        self.assertEqual([], self.store.list_recent_receipts("s1", "t1", limit=10))

    def test_post_tool_use_rejects_non_object_nested_payload_without_session(self) -> None:
        result = self.hooks.post_tool_use(
            {
                "session_id": "missing-session",
                "cwd": self.temp_dir.name,
                "tool_name": "Bash",
                "tool_input": {"command": "pytest -q"},
                "tool_response": [],
            }
        )

        self.assertEqual(0, result)
        with closing(sqlite3.connect(self.db_path)) as conn:
            row = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()
        self.assertEqual(0, row[0])


if __name__ == "__main__":
    unittest.main()
