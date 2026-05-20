from __future__ import annotations

import importlib
import io
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing, redirect_stderr
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
for path in (REPO_ROOT / "mcp", REPO_ROOT / "scripts"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


class OpenCodeBridgePayloadEdgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "state.db"
        self.secret_path = Path(self.temp_dir.name) / "secret.key"
        os.environ["ILH_DB_PATH"] = str(self.db_path)
        os.environ["ILH_SECRET_PATH"] = str(self.secret_path)
        self.server = importlib.reload(importlib.import_module("server"))
        self.bridge = importlib.reload(importlib.import_module("opencode_plugin_bridge"))
        self.store = self.server.store

    def tearDown(self) -> None:
        self.temp_dir.cleanup()
        os.environ.pop("ILH_DB_PATH", None)
        os.environ.pop("ILH_SECRET_PATH", None)

    def test_load_event_rejects_non_object_json_payload(self) -> None:
        original_stdin = sys.stdin
        stderr = io.StringIO()
        sys.stdin = io.StringIO("[]")
        try:
            with redirect_stderr(stderr):
                event = self.bridge.load_event()
        finally:
            sys.stdin = original_stdin

        self.assertEqual(event["error"], "json_payload_not_object")
        self.assertEqual(event["payload_type"], "list")
        self.assertNotIn("[]", stderr.getvalue())

    def test_pre_tool_use_denies_non_object_tool_input(self) -> None:
        decision = self.bridge.pre_tool_use(
            {
                "session_id": "s1",
                "cwd": self.temp_dir.name,
                "tool_name": "bash",
                "tool_input": ["git push origin main"],
            }
        )

        self.assertEqual(decision["decision"], "deny")
        self.assertIn("tool_input", decision["reason"])

    def test_post_tool_use_rejects_non_object_tool_input_without_receipt(self) -> None:
        self.server.mission_lock("s1", "t1", "goal", ["criterion"])
        result = self.bridge.post_tool_use(
            {
                "session_id": "s1",
                "cwd": self.temp_dir.name,
                "tool_name": "bash",
                "tool_input": ["pytest -q"],
                "tool_response": {"output": "ok"},
            }
        )

        self.assertFalse(result["recorded"])
        self.assertIn("tool_input", result["reason"])
        self.assertEqual([], self.store.list_recent_receipts("s1", "t1", limit=10))

    def test_post_tool_use_rejects_non_object_tool_response_without_receipt(self) -> None:
        self.server.mission_lock("s1", "t1", "goal", ["criterion"])
        result = self.bridge.post_tool_use(
            {
                "session_id": "s1",
                "cwd": self.temp_dir.name,
                "tool_name": "bash",
                "tool_input": {"command": "pytest -q"},
                "tool_response": "ok",
            }
        )

        self.assertFalse(result["recorded"])
        self.assertIn("tool_response", result["reason"])
        self.assertEqual([], self.store.list_recent_receipts("s1", "t1", limit=10))

    def test_rejected_payload_edges_do_not_create_sessions(self) -> None:
        self.bridge.post_tool_use(
            {
                "session_id": "missing-session",
                "cwd": self.temp_dir.name,
                "tool_name": "bash",
                "tool_input": {"command": "pytest -q"},
                "tool_response": [],
            }
        )

        with closing(sqlite3.connect(self.db_path)) as conn:
            row = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()
        self.assertEqual(0, row[0])


if __name__ == "__main__":
    unittest.main()
