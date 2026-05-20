from __future__ import annotations

import importlib
import json
import math
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path


class BudgetExhaustionTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "state.db"
        self.secret_path = Path(self.temp_dir.name) / "secret.key"
        os.environ["ILH_DB_PATH"] = str(self.db_path)
        os.environ["ILH_SECRET_PATH"] = str(self.secret_path)
        import sys

        mcp_root = str(Path(__file__).resolve().parents[1])
        if mcp_root not in sys.path:
            sys.path.insert(0, mcp_root)
        self.server = importlib.import_module("server")
        self.server = importlib.reload(self.server)
        self.store = self.server.store

    def tearDown(self) -> None:
        self.temp_dir.cleanup()
        os.environ.pop("ILH_DB_PATH", None)
        os.environ.pop("ILH_SECRET_PATH", None)

    def make_bash_receipt(
        self, session_id: str, task_id: str, command: str, exit_code: int = 0
    ):
        return self.store.record_receipt(
            session_id=session_id,
            task_id=task_id,
            source="test",
            tool_name="Bash",
            command_text=command,
            exit_code=exit_code,
            metadata={"stdout_sha256": "abc"},
        )

    def test_frontier_exhausted_is_legal_after_slice_budget_is_exhausted(self) -> None:
        self.server.mission_lock(
            "s1",
            "budget-wrap-task",
            "finish bounded work",
            ["one verified slice"],
            slice_budget=1,
        )
        first = self.make_bash_receipt("s1", "budget-wrap-task", "python one.py")
        first_result = self.server.turn_end_gate(
            session_id="s1",
            task_id="budget-wrap-task",
            stop_condition="slice_verified",
            work_summary="Verified the single permitted slice with direct command output evidence.",
            receipt_ids=[first.receipt_id],
        )
        self.assertIn("APPROVED", first_result)

        wrap = self.make_bash_receipt("s1", "budget-wrap-task", "python inspect.py")
        wrap_result = self.server.turn_end_gate(
            session_id="s1",
            task_id="budget-wrap-task",
            stop_condition="frontier_exhausted",
            work_summary="Inspected the remaining local frontier after budget exhaustion and found no further in-scope action.",
            receipt_ids=[wrap.receipt_id],
        )
        self.assertIn("APPROVED", wrap_result)
        self.assertIn("stop_condition: frontier_exhausted", wrap_result)

        mission = self.store.get_mission("s1", "budget-wrap-task")
        self.assertEqual(mission.slice_count, 1)

    def test_frontier_exhausted_is_legal_after_time_budget_is_exhausted(self) -> None:
        self.server.mission_lock(
            "s1",
            "time-wrap-task",
            "finish bounded work",
            ["inspect frontier"],
            time_budget_minutes=1,
        )
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute(
                "UPDATE missions SET created_at=? WHERE session_id=? AND task_id=?",
                ("2000-01-01T00:00:00Z", "s1", "time-wrap-task"),
            )

        wrap = self.make_bash_receipt("s1", "time-wrap-task", "python inspect.py")
        wrap_result = self.server.turn_end_gate(
            session_id="s1",
            task_id="time-wrap-task",
            stop_condition="frontier_exhausted",
            work_summary="Inspected the remaining local frontier after time budget exhaustion and found no further in-scope action.",
            receipt_ids=[wrap.receipt_id],
        )
        self.assertIn("APPROVED", wrap_result)
        self.assertIn("stop_condition: frontier_exhausted", wrap_result)

    def test_slice_verified_is_rejected_after_slice_budget_is_exhausted(self) -> None:
        self.server.mission_lock(
            "s1", "slice-block-task", "goal", ["criterion"], slice_budget=1
        )
        first = self.make_bash_receipt("s1", "slice-block-task", "python one.py")
        self.server.turn_end_gate(
            session_id="s1",
            task_id="slice-block-task",
            stop_condition="slice_verified",
            work_summary="Verified the single permitted slice with direct command output evidence.",
            receipt_ids=[first.receipt_id],
        )

        second = self.make_bash_receipt("s1", "slice-block-task", "python two.py")
        rejected = self.server.turn_end_gate(
            session_id="s1",
            task_id="slice-block-task",
            stop_condition="slice_verified",
            work_summary="Attempted to claim another verified slice after exhausting the slice budget.",
            receipt_ids=[second.receipt_id],
        )
        self.assertIn("REJECTED", rejected)
        self.assertIn("slice_budget is exhausted", rejected)

    def test_slice_verified_is_rejected_after_time_budget_is_exhausted(self) -> None:
        self.server.mission_lock(
            "s1",
            "time-block-task",
            "goal",
            ["criterion"],
            time_budget_minutes=1,
        )
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute(
                "UPDATE missions SET created_at=? WHERE session_id=? AND task_id=?",
                ("2000-01-01T00:00:00Z", "s1", "time-block-task"),
            )

        receipt = self.store.record_receipt(
            session_id="s1",
            task_id="time-block-task",
            source="test",
            tool_name="Bash",
            command_text="python one.py",
            exit_code=0,
            metadata={"stdout_sha256": "abc", "duration_seconds": 120},
        )
        rejected = self.server.turn_end_gate(
            session_id="s1",
            task_id="time-block-task",
            stop_condition="slice_verified",
            work_summary="Attempted to claim a verified slice after exhausting the time budget.",
            receipt_ids=[receipt.receipt_id],
        )
        self.assertIn("REJECTED", rejected)
        self.assertIn("time budget is exhausted", rejected)

    def test_api_timeout_wall_clock_does_not_exhaust_active_work_time_budget(self) -> None:
        self.server.mission_lock(
            "s1",
            "api-timeout-task",
            "goal",
            ["criterion"],
            time_budget_minutes=1,
        )
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute(
                "UPDATE missions SET created_at=? WHERE session_id=? AND task_id=?",
                ("2000-01-01T00:00:00Z", "s1", "api-timeout-task"),
            )

        receipt = self.make_bash_receipt("s1", "api-timeout-task", "python verify.py")
        approved = self.server.turn_end_gate(
            session_id="s1",
            task_id="api-timeout-task",
            stop_condition="slice_verified",
            work_summary="Verified the slice after an external API timeout delay that should not consume active work budget.",
            receipt_ids=[receipt.receipt_id],
        )
        self.assertIn("APPROVED", approved)

        status = json.loads(self.server.budget_status("s1", "api-timeout-task"))
        self.assertGreater(status["wall_clock_elapsed_minutes"], status["elapsed_minutes"])
        self.assertGreater(status["time_remaining_minutes"], 0)
        self.assertFalse(status["time_budget_exhausted"])

    def test_single_long_running_receipt_exhausts_active_work_time_budget(self) -> None:
        self.server.mission_lock(
            "s1",
            "long-running-task",
            "goal",
            ["criterion"],
            time_budget_minutes=1,
        )
        receipt = self.store.record_receipt(
            session_id="s1",
            task_id="long-running-task",
            source="test",
            tool_name="Bash",
            command_text="python long_running.py",
            exit_code=0,
            metadata={"stdout_sha256": "abc", "duration_seconds": 120},
        )

        rejected = self.server.turn_end_gate(
            session_id="s1",
            task_id="long-running-task",
            stop_condition="slice_verified",
            work_summary="Attempted to claim a verified slice after a single long-running command exceeded the active work budget.",
            receipt_ids=[receipt.receipt_id],
        )
        self.assertIn("REJECTED", rejected)
        self.assertIn("time budget is exhausted", rejected)

        status = json.loads(self.server.budget_status("s1", "long-running-task"))
        self.assertEqual(status["elapsed_minutes"], 2)
        self.assertEqual(status["receipt_duration_minutes"], 2)
        self.assertTrue(status["time_budget_exhausted"])

    def test_non_finite_receipt_duration_does_not_exhaust_time_budget(self) -> None:
        self.server.mission_lock(
            "s1",
            "non-finite-duration-task",
            "goal",
            ["criterion"],
            time_budget_minutes=1,
        )
        self.store.record_receipt(
            session_id="s1",
            task_id="non-finite-duration-task",
            source="test",
            tool_name="Bash",
            command_text="python weird_duration.py",
            exit_code=0,
            metadata={"stdout_sha256": "abc", "duration_seconds": math.inf},
        )

        status = json.loads(self.server.budget_status("s1", "non-finite-duration-task"))

        self.assertEqual(status["receipt_duration_minutes"], 0)
        self.assertFalse(status["time_budget_exhausted"])

    def test_boolean_receipt_duration_does_not_accumulate_into_time_budget(self) -> None:
        self.server.mission_lock(
            "s1",
            "bool-duration-budget-task",
            "goal",
            ["criterion"],
            time_budget_minutes=1,
        )
        for index in range(60):
            self.store.record_receipt(
                session_id="s1",
                task_id="bool-duration-budget-task",
                source="test",
                tool_name="Bash",
                command_text=f"python verify_{index}.py",
                exit_code=0,
                metadata={"stdout_sha256": "abc", "duration_seconds": True},
            )

        status = json.loads(self.server.budget_status("s1", "bool-duration-budget-task"))

        self.assertEqual(status["receipt_duration_minutes"], 0)
        self.assertFalse(status["time_budget_exhausted"])

    def test_forced_conversation_gap_between_receipts_does_not_exhaust_time_budget(self) -> None:
        self.server.mission_lock(
            "s1",
            "forced-gap-task",
            "goal",
            ["criterion"],
            time_budget_minutes=1,
        )
        self.store.record_receipt(
            session_id="s1",
            task_id="forced-gap-task",
            source="test",
            tool_name="Bash",
            command_text="python before_forced_stop.py",
            exit_code=0,
            metadata={"stdout_sha256": "before", "duration_seconds": 1},
            created_at="2000-01-01T00:00:00Z",
        )
        receipt = self.store.record_receipt(
            session_id="s1",
            task_id="forced-gap-task",
            source="test",
            tool_name="Bash",
            command_text="python after_continue.py",
            exit_code=0,
            metadata={"stdout_sha256": "after", "duration_seconds": 1},
            created_at="2000-01-01T01:00:00Z",
        )

        approved = self.server.turn_end_gate(
            session_id="s1",
            task_id="forced-gap-task",
            stop_condition="slice_verified",
            work_summary="Verified the slice after a forced conversation gap that should not count as agent work time.",
            receipt_ids=[receipt.receipt_id],
        )
        self.assertIn("APPROVED", approved)

        status = json.loads(self.server.budget_status("s1", "forced-gap-task"))
        self.assertEqual(status["receipt_window_minutes"], 60)
        self.assertEqual(status["receipt_duration_minutes"], 0)
        self.assertFalse(status["time_budget_exhausted"])

if __name__ == "__main__":
    unittest.main()
