from __future__ import annotations

import importlib
import json
import os
import tempfile
import unittest
from pathlib import Path


class LongSessionContinuationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "state.db"
        self.cwd = Path(self.temp_dir.name) / "repo"
        self.cwd.mkdir()
        os.environ["ILH_DB_PATH"] = str(self.db_path)
        os.environ["ILH_SECRET_PATH"] = str(Path(self.temp_dir.name) / "secret.key")
        os.environ["ILH_HARNESS_SECRET"] = "a" * 64

        import sys

        mcp_root = str(Path(__file__).resolve().parents[1])
        if mcp_root not in sys.path:
            sys.path.insert(0, mcp_root)
        self.server = importlib.reload(importlib.import_module("server"))
        self.store = self.server.store

    def tearDown(self) -> None:
        self.temp_dir.cleanup()
        os.environ.pop("ILH_DB_PATH", None)
        os.environ.pop("ILH_SECRET_PATH", None)
        os.environ.pop("ILH_HARNESS_SECRET", None)

    def lock(self, task_id: str, session_id: str = "s1") -> None:
        self.server.mission_lock(
            session_id,
            task_id,
            f"finish {task_id}",
            ["criterion"],
            cwd=str(self.cwd),
        )

    def receipt(self, task_id: str):
        return self.store.record_receipt(
            session_id="s1",
            task_id=task_id,
            source="test",
            tool_name="Bash",
            command_text="pytest -q",
            exit_code=0,
            metadata={"stdout_sha256": "abc"},
        )

    def test_mission_lock_keeps_previous_task_active_in_same_session(self) -> None:
        self.lock("task-a")
        self.lock("task-b")

        active = {mission.task_id for mission in self.store.list_active_missions("s1")}

        self.assertEqual({"task-a", "task-b"}, active)

    def test_completion_gate_reports_remaining_active_missions(self) -> None:
        self.lock("task-a")
        self.lock("task-b")
        receipt = self.receipt("task-b")
        turn = self.server.turn_end_gate(
            "s1",
            "task-b",
            "slice_verified",
            "Verified task-b with a fresh execution receipt before completion.",
            [receipt.receipt_id],
        )
        self.assertIn("APPROVED", turn)

        result = self.server.completion_gate(
            "s1",
            "task-b",
            "Completed task-b with a fresh execution receipt mapped to the criterion.",
            [{"criterion": "criterion", "receipt_ids": [receipt.receipt_id]}],
        )

        self.assertIn("APPROVED", result)
        self.assertIn("active_missions_remaining: 1", result)
        self.assertIn('remaining_active_task_ids: ["task-a"]', result)
        self.assertIn("next_action_required: continue remaining active mission(s)", result)
        self.assertIn("next_active_task_id: task-a", result)
        self.assertIn("task-a", result)

    def test_prompt_intake_uses_host_session_binding_after_compaction(self) -> None:
        self.lock("bound-task", session_id="mission-session")
        mission = self.store.get_active_mission("mission-session", "bound-task")
        self.store.bind_host_session_to_mission("host-session", mission, source="test")

        payload = json.loads(
            self.server.prompt_intake_gate(
                session_id="host-session",
                user_message="continue",
                cwd=str(Path(self.temp_dir.name) / "other-repo"),
            )
        )

        self.assertEqual("continue_current_mission", payload["classification"])
        self.assertEqual("mission-session", payload["mission"]["session_id"])
        self.assertEqual("bound-task", payload["mission"]["task_id"])
        self.assertIn("host_session_binding", payload["evidence_sources"])

    def test_mission_resume_rebinds_host_session_for_compacted_continue(self) -> None:
        self.lock("bound-task", session_id="mission-session")

        resumed = self.server.mission_resume(
            "mission-session",
            "bound-task",
            host_session_id="host-session",
        )
        payload = json.loads(
            self.server.prompt_intake_gate(
                session_id="host-session",
                user_message="continue",
                cwd=str(Path(self.temp_dir.name) / "other-repo"),
            )
        )

        self.assertIn("MISSION RESUMED", resumed)
        self.assertEqual("continue_current_mission", payload["classification"])
        self.assertEqual("mission-session", payload["mission"]["session_id"])
        self.assertEqual("bound-task", payload["mission"]["task_id"])

    def test_mission_lock_can_write_host_session_binding_without_hook_event(self) -> None:
        locked = self.server.mission_lock(
            "mission-session",
            "bound-task",
            "goal",
            ["criterion"],
            cwd=str(self.cwd),
            host_session_id="host-session",
        )
        payload = json.loads(
            self.server.prompt_intake_gate(
                session_id="host-session",
                user_message="continue",
                cwd=str(Path(self.temp_dir.name) / "other-repo"),
            )
        )

        self.assertIn("binding_written: yes", locked)
        self.assertEqual("continue_current_mission", payload["classification"])
        self.assertEqual("mission-session", payload["mission"]["session_id"])
        self.assertEqual("bound-task", payload["mission"]["task_id"])
        self.assertIn("host_session_binding", payload["evidence_sources"])


if __name__ == "__main__":
    unittest.main()
