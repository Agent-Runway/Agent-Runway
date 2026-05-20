from __future__ import annotations

import importlib
import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


class ReceiptBackedHookTestCase(unittest.TestCase):
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
        self.server = importlib.reload(importlib.import_module("server"))
        self.hooks = importlib.reload(importlib.import_module("claude_hooks"))
        self.bridge = importlib.reload(importlib.import_module("opencode_plugin_bridge"))
        self.store = self.server.store

    def tearDown(self) -> None:
        self.temp_dir.cleanup()
        os.environ.pop("ILH_DB_PATH", None)
        os.environ.pop("ILH_SECRET_PATH", None)

    def lock(self) -> None:
        self.server.mission_lock("s1", "t1", "goal", ["criterion"])

    def test_claude_pre_tool_ask_decision_is_receipt_backed(self) -> None:
        self.lock()
        event = {
            "session_id": "s1",
            "cwd": self.temp_dir.name,
            "tool_name": "Bash",
            "tool_input": {"command": "git push origin main"},
        }

        with redirect_stdout(io.StringIO()):
            self.assertEqual(self.hooks.pre_tool_use(event), 0)

        receipt = self.store.list_recent_receipts("s1", "t1", limit=1)[0]
        self.assertEqual(receipt.source, "claude-hook")
        self.assertEqual(receipt.tool_name, "PreToolUse")
        self.assertEqual(receipt.metadata["hook_decision"], "ask")
        self.assertIn("git push", receipt.command_text)

    def test_claude_pre_tool_deny_decision_is_receipt_backed(self) -> None:
        self.lock()
        event = {
            "session_id": "s1",
            "cwd": self.temp_dir.name,
            "tool_name": "Read",
            "tool_input": {"file_path": str(self.secret_path)},
        }

        with redirect_stdout(io.StringIO()):
            self.assertEqual(self.hooks.pre_tool_use(event), 0)

        receipt = self.store.list_recent_receipts("s1", "t1", limit=1)[0]
        self.assertEqual(receipt.source, "claude-hook")
        self.assertEqual(receipt.tool_name, "PreToolUse")
        self.assertEqual(receipt.exit_code, 1)
        self.assertEqual(receipt.metadata["hook_decision"], "deny")
        self.assertEqual(receipt.metadata["target_tool_name"], "Read")

    def test_claude_stop_block_decision_is_receipt_backed(self) -> None:
        self.lock()
        self.store.record_receipt(
            session_id="s1",
            task_id="t1",
            source="test",
            tool_name="Bash",
            command_text="pytest -q",
            exit_code=0,
            metadata={},
        )

        with redirect_stdout(io.StringIO()):
            self.assertEqual(self.hooks.stop({"session_id": "s1", "cwd": self.temp_dir.name}), 0)

        receipt = self.store.list_recent_receipts("s1", "t1", limit=1)[0]
        self.assertEqual(receipt.source, "claude-hook")
        self.assertEqual(receipt.tool_name, "Stop")
        self.assertEqual(receipt.exit_code, 1)
        self.assertEqual(receipt.metadata["hook_decision"], "block")
        self.assertEqual(receipt.metadata["gate_type"], "turn_end_gate")

    def test_opencode_before_hook_decision_is_receipt_backed(self) -> None:
        self.lock()
        decision = self.bridge.pre_tool_use(
            {
                "session_id": "s1",
                "cwd": self.temp_dir.name,
                "tool_name": "bash",
                "tool_input": {"command": "git push origin main"},
            }
        )

        self.assertEqual(decision["decision"], "ask")
        receipt = self.store.list_recent_receipts("s1", "t1", limit=1)[0]
        self.assertEqual(receipt.source, "opencode-plugin")
        self.assertEqual(receipt.tool_name, "OpenCodeToolExecuteBefore")
        self.assertEqual(receipt.metadata["hook_decision"], "ask")

    def test_claude_pre_tool_decision_marks_unscoped_without_active_mission(self) -> None:
        event = {
            "session_id": "orphan-session",
            "cwd": self.temp_dir.name,
            "tool_name": "Bash",
            "tool_input": {"command": "git push origin main"},
        }

        with redirect_stdout(io.StringIO()):
            self.assertEqual(self.hooks.pre_tool_use(event), 0)

        receipt = self.store.list_recent_receipts("orphan-session", limit=1)[0]
        self.assertIsNone(receipt.task_id)
        self.assertEqual(receipt.source, "claude-hook")
        self.assertEqual(receipt.tool_name, "PreToolUse")
        self.assertEqual(receipt.metadata["hook_decision"], "ask")
        self.assertEqual(receipt.metadata["scope_status"], "unscoped")
        self.assertEqual(
            receipt.metadata["scope_reason"],
            "no_active_mission_or_binding",
        )

    def test_opencode_before_hook_decision_keeps_unscoped_when_cwd_is_ambiguous(self) -> None:
        self.server.mission_lock(
            "mission-session-a",
            "active-task-a",
            "goal",
            ["criterion"],
            cwd=self.temp_dir.name,
        )
        self.server.mission_lock(
            "mission-session-b",
            "active-task-b",
            "goal",
            ["criterion"],
            cwd=self.temp_dir.name,
        )

        decision = self.bridge.pre_tool_use(
            {
                "session_id": "host-session",
                "cwd": self.temp_dir.name,
                "tool_name": "bash",
                "tool_input": {"command": "git push origin main"},
            }
        )

        self.assertEqual(decision["decision"], "ask")
        orphan = self.store.list_recent_receipts("host-session", limit=1)[0]
        self.assertIsNone(orphan.task_id)
        self.assertEqual(orphan.source, "opencode-plugin")
        self.assertEqual(orphan.tool_name, "OpenCodeToolExecuteBefore")
        self.assertEqual(orphan.metadata["hook_decision"], "ask")
        self.assertEqual(orphan.metadata["scope_status"], "unscoped")
        self.assertEqual(orphan.metadata["scope_reason"], "ambiguous_cwd_mission")
        self.assertEqual(orphan.metadata["scope_candidate_count"], 2)
        self.assertEqual(
            self.store.list_recent_receipts("mission-session-a", "active-task-a", limit=10),
            [],
        )
        self.assertEqual(
            self.store.list_recent_receipts("mission-session-b", "active-task-b", limit=10),
            [],
        )


if __name__ == "__main__":
    unittest.main()
