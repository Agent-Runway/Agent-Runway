from __future__ import annotations

import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "mcp") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "mcp"))
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))


class OpenCodeReceiptAttributionEdgesTestCase(unittest.TestCase):
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

    def record_opencode_receipt(self, session_id: str, cwd: str) -> dict[str, object]:
        return self.bridge.post_tool_use({
            "session_id": session_id,
            "cwd": cwd,
            "tool_name": "bash",
            "tool_input": {"command": "pytest -q"},
            "tool_response": {
                "output": "ok",
                "metadata": {"exitCode": 0},
            },
            "hook_event_name": "OpenCodeToolExecuteAfter",
        })

    def test_maps_receipt_to_latest_active_same_cwd_mission(self) -> None:
        self.server.mission_lock(
            "mission-session",
            "active-task",
            "goal",
            ["criterion"],
            host="opencode",
            cwd=self.temp_dir.name,
        )

        result = self.record_opencode_receipt("host-session", self.temp_dir.name)

        self.assertTrue(result["recorded"])
        self.assertEqual(result["task_id"], "active-task")
        mapped = self.store.list_recent_receipts("mission-session", "active-task", limit=10)
        orphan = self.store.list_recent_receipts("host-session", limit=10)
        self.assertEqual(len(mapped), 1)
        self.assertEqual(mapped[0].source, "opencode-plugin")
        self.assertEqual(mapped[0].task_id, "active-task")
        self.assertEqual(orphan, [])

    def test_exact_cwd_match_still_fails_closed_when_duplicate_active_missions_exist(self) -> None:
        self.server.mission_lock(
            "mission-session-a",
            "active-task-a",
            "goal",
            ["criterion"],
            host="opencode",
            cwd=self.temp_dir.name,
        )
        self.server.mission_lock(
            "mission-session-b",
            "active-task-b",
            "goal",
            ["criterion"],
            host="opencode",
            cwd=self.temp_dir.name,
        )

        result = self.record_opencode_receipt("host-session", self.temp_dir.name)

        self.assertTrue(result["recorded"])
        self.assertIsNone(result["task_id"])

    def test_exact_cwd_match_fails_closed_when_equivalent_cwd_mapping_is_ambiguous(self) -> None:
        project_dir = Path(self.temp_dir.name) / "project"
        project_dir.mkdir()
        self.server.mission_lock(
            "mission-session-a",
            "active-task-a",
            "goal",
            ["criterion"],
            host="opencode",
            cwd=str(project_dir),
        )
        self.server.mission_lock(
            "mission-session-b",
            "active-task-b",
            "goal",
            ["criterion"],
            host="opencode",
            cwd=str(project_dir) + os.sep,
        )

        result = self.record_opencode_receipt("host-session", str(project_dir))

        self.assertTrue(result["recorded"])
        self.assertIsNone(result["task_id"])

    def test_maps_same_directory_even_when_cwd_strings_are_not_identical(self) -> None:
        project_dir = Path(self.temp_dir.name) / "project"
        project_dir.mkdir()
        self.server.mission_lock(
            "mission-session",
            "active-task",
            "goal",
            ["criterion"],
            host="opencode",
            cwd=str(project_dir),
        )

        result = self.record_opencode_receipt("host-session", str(project_dir) + os.sep)

        self.assertTrue(result["recorded"])
        self.assertEqual(result["task_id"], "active-task")
        mapped = self.store.list_recent_receipts("mission-session", "active-task", limit=10)
        orphan = self.store.list_recent_receipts("host-session", limit=10)
        self.assertEqual(len(mapped), 1)
        self.assertEqual(orphan, [])

    def test_keeps_receipt_taskless_when_same_cwd_mapping_is_ambiguous(self) -> None:
        self.server.mission_lock(
            "mission-session-a",
            "active-task-a",
            "goal",
            ["criterion"],
            host="opencode",
            cwd=self.temp_dir.name,
        )
        self.server.mission_lock(
            "mission-session-b",
            "active-task-b",
            "goal",
            ["criterion"],
            host="opencode",
            cwd=self.temp_dir.name,
        )

        result = self.record_opencode_receipt("host-session", self.temp_dir.name)

        self.assertTrue(result["recorded"])
        self.assertIsNone(result["task_id"])
        self.assertEqual(self.store.list_recent_receipts("mission-session-a", "active-task-a", limit=10), [])
        self.assertEqual(self.store.list_recent_receipts("mission-session-b", "active-task-b", limit=10), [])
        orphan = self.store.list_recent_receipts("host-session", limit=10)
        self.assertEqual(len(orphan), 1)
        self.assertIsNone(orphan[0].task_id)


if __name__ == "__main__":
    unittest.main()
