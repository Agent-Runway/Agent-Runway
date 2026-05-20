from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MCP_ROOT = REPO_ROOT / "mcp"
if str(MCP_ROOT) not in sys.path:
    sys.path.insert(0, str(MCP_ROOT))


class ReceiptScopeEdgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        os.environ["ILH_DB_PATH"] = str(Path(self.temp_dir.name) / "state.db")
        os.environ["ILH_SECRET_PATH"] = str(Path(self.temp_dir.name) / "secret.key")
        os.environ["ILH_HARNESS_SECRET"] = "a" * 64
        self.server = importlib.reload(importlib.import_module("server"))
        self.store = self.server.store

    def tearDown(self) -> None:
        self.temp_dir.cleanup()
        os.environ.pop("ILH_DB_PATH", None)
        os.environ.pop("ILH_SECRET_PATH", None)
        os.environ.pop("ILH_HARNESS_SECRET", None)

    def taskless_receipt(
        self,
        session_id: str = "s1",
        command_text: str = "pytest -q",
    ):
        return self.store.record_receipt(
            session_id=session_id,
            task_id=None,
            source="test",
            tool_name="Bash",
            command_text=command_text,
            exit_code=0,
            metadata={"stdout_sha256": "abc"},
        )

    def approve_turn(self, task_id: str, receipt_ids: list[str]) -> None:
        approved = self.server.turn_end_gate(
            session_id="s1",
            task_id=task_id,
            stop_condition="slice_verified",
            work_summary="Verified the current slice with the same receipts before completion.",
            receipt_ids=receipt_ids,
        )
        self.assertIn("APPROVED", approved)

    def test_turn_end_gate_allows_taskless_receipt_for_single_active_mission_with_warning(self) -> None:
        self.server.mission_lock("s1", "t1", "goal", ["tests pass"])
        receipt = self.taskless_receipt()

        integrity = json.loads(self.server.verify_receipt_integrity("s1", [receipt.receipt_id], ""))
        approved = self.server.turn_end_gate(
            session_id="s1",
            task_id="t1",
            stop_condition="slice_verified",
            work_summary="Ran verification through a host path that emitted a taskless receipt.",
            receipt_ids=[receipt.receipt_id],
        )

        self.assertTrue(integrity["all_valid"])
        self.assertIn("APPROVED", approved)
        self.assertIn("Receipts are not mission-scoped", approved)

    def test_completion_gate_allows_taskless_receipt_for_single_active_mission_with_warning(self) -> None:
        self.server.mission_lock("s1", "t1", "goal", ["tests pass"])
        receipt = self.taskless_receipt()
        self.approve_turn("t1", [receipt.receipt_id])

        approved = self.server.completion_gate(
            session_id="s1",
            task_id="t1",
            criterion_receipt_map=[{"criterion": "tests pass", "receipt_ids": [receipt.receipt_id]}],
            completion_summary="Mapped the tests criterion to a fresh taskless execution receipt.",
        )

        self.assertIn("APPROVED", approved)
        self.assertIn("Receipts are not mission-scoped", approved)

    def test_turn_end_gate_allows_mixed_taskless_receipt_with_single_active_mission(self) -> None:
        self.server.mission_lock("s1", "t1", "goal", ["tests pass"])
        scoped = self.task_receipt("s1", "t1")
        taskless = self.taskless_receipt(command_text="pytest shared")

        approved = self.server.turn_end_gate(
            session_id="s1",
            task_id="t1",
            stop_condition="slice_verified",
            work_summary="Verified the slice with one scoped receipt and one taskless receipt.",
            receipt_ids=[scoped.receipt_id, taskless.receipt_id],
        )

        self.assertIn("APPROVED", approved)
        self.assertNotIn("load-bearing gate evidence", approved)
        self.assertIn("Receipts are not mission-scoped", approved)

    def test_turn_end_gate_rejects_taskless_receipt_when_session_has_multiple_active_missions(self) -> None:
        self.server.mission_lock("s1", "task-a", "goal a", ["tests pass"])
        self.server.mission_lock("s1", "task-b", "goal b", ["tests pass"])
        receipt = self.taskless_receipt(command_text="pytest shared")

        rejected = self.server.turn_end_gate(
            session_id="s1",
            task_id="task-a",
            stop_condition="slice_verified",
            work_summary="Tried to close task A using a taskless receipt while task B was also active.",
            receipt_ids=[receipt.receipt_id],
        )

        self.assertIn("REJECTED", rejected)
        self.assertIn("taskless receipt", rejected.lower())
        self.assertIn("multiple active missions", rejected.lower())

    def test_completion_gate_rejects_taskless_receipt_when_session_has_multiple_active_missions(self) -> None:
        self.server.mission_lock("s1", "task-a", "goal a", ["tests pass"])
        self.server.mission_lock("s1", "task-b", "goal b", ["tests pass"])
        receipt = self.taskless_receipt(command_text="pytest shared")

        rejected = self.server.completion_gate(
            session_id="s1",
            task_id="task-a",
            criterion_receipt_map=[{"criterion": "tests pass", "receipt_ids": [receipt.receipt_id]}],
            completion_summary="Tried to complete task A using taskless evidence while task B was also active.",
        )

        self.assertIn("REJECTED", rejected)
        self.assertIn("taskless receipt", rejected.lower())
        self.assertIn("multiple active missions", rejected.lower())

    def test_turn_end_gate_rejects_mixed_taskless_receipt_when_session_has_multiple_active_missions(self) -> None:
        self.server.mission_lock("s1", "task-a", "goal a", ["tests pass"])
        self.server.mission_lock("s1", "task-b", "goal b", ["tests pass"])
        scoped = self.task_receipt("s1", "task-a")
        taskless = self.taskless_receipt(command_text="pytest shared")

        rejected = self.server.turn_end_gate(
            session_id="s1",
            task_id="task-a",
            stop_condition="slice_verified",
            work_summary="Tried to mix scoped task A evidence with a taskless receipt while task B was active.",
            receipt_ids=[scoped.receipt_id, taskless.receipt_id],
        )

        self.assertIn("REJECTED", rejected)
        self.assertIn("taskless receipt", rejected.lower())
        self.assertIn("multiple active missions", rejected.lower())

    def test_completion_gate_rejects_mixed_taskless_receipt_when_session_has_multiple_active_missions(self) -> None:
        self.server.mission_lock("s1", "task-a", "goal a", ["tests pass", "lint pass"])
        self.server.mission_lock("s1", "task-b", "goal b", ["tests pass"])
        scoped = self.task_receipt("s1", "task-a")
        taskless = self.taskless_receipt(command_text="pytest shared")

        rejected = self.server.completion_gate(
            session_id="s1",
            task_id="task-a",
            criterion_receipt_map=[
                {"criterion": "tests pass", "receipt_ids": [scoped.receipt_id]},
                {"criterion": "lint pass", "receipt_ids": [taskless.receipt_id]},
            ],
            completion_summary="Tried to complete task A with mixed scoped and taskless evidence while task B was active.",
        )

        self.assertIn("REJECTED", rejected)
        self.assertIn("taskless receipt", rejected.lower())
        self.assertIn("multiple active missions", rejected.lower())

    def test_completion_gate_allows_mixed_taskless_receipt_with_single_active_mission(self) -> None:
        self.server.mission_lock("s1", "t1", "goal", ["tests pass", "lint pass"])
        scoped = self.task_receipt("s1", "t1")
        taskless = self.taskless_receipt(command_text="ruff check")
        self.approve_turn("t1", [scoped.receipt_id, taskless.receipt_id])

        approved = self.server.completion_gate(
            session_id="s1",
            task_id="t1",
            criterion_receipt_map=[
                {"criterion": "tests pass", "receipt_ids": [scoped.receipt_id]},
                {"criterion": "lint pass", "receipt_ids": [taskless.receipt_id]},
            ],
            completion_summary="Completed with one scoped test receipt and one taskless lint receipt.",
        )

        self.assertIn("APPROVED", approved)
        self.assertNotIn("load-bearing gate evidence", approved)
        self.assertIn("Receipts are not mission-scoped", approved)

    def test_completion_gate_approves_and_warns_when_all_receipts_are_taskless(self) -> None:
        self.server.mission_lock("s1", "t1", "goal", ["tests pass"])
        receipt = self.taskless_receipt()
        self.approve_turn("t1", [receipt.receipt_id])

        approved = self.server.completion_gate(
            session_id="s1",
            task_id="t1",
            criterion_receipt_map=[{"criterion": "tests pass", "receipt_ids": [receipt.receipt_id]}],
            completion_summary="Mapped the tests criterion to a fresh taskless execution receipt.",
        )

        self.assertIn("APPROVED", approved)
        self.assertIn("Receipts are not mission-scoped", approved)

    def test_completion_gate_rejection_warns_when_all_receipts_are_taskless(self) -> None:
        self.server.mission_lock("s1", "t1", "goal", ["tests pass"])
        receipt = self.taskless_receipt()

        rejected = self.server.completion_gate(
            session_id="s1",
            task_id="t1",
            criterion_receipt_map=[{"criterion": "unknown criterion", "receipt_ids": [receipt.receipt_id]}],
            completion_summary="Attempted completion with an unknown criterion and a taskless receipt.",
        )

        self.assertIn("REJECTED", rejected)
        self.assertIn("Receipts are not mission-scoped", rejected)

    def test_list_recent_receipts_in_task_scope_shows_fresh_taskless_receipts(self) -> None:
        self.server.mission_lock("s1", "t1", "goal", ["tests pass"])
        receipt = self.taskless_receipt(command_text="pytest -q --taskless")

        listing = self.server.list_recent_receipts("s1", "t1")

        self.assertIn(receipt.receipt_id, listing)
        self.assertIn("pytest -q --taskless", listing)

    def test_list_recent_receipts_filters_before_limiting_task_scope(self) -> None:
        self.server.mission_lock("s1", "t1", "goal", ["tests pass"])
        receipt = self.taskless_receipt(command_text="pytest -q --taskless")
        for index in range(12):
            self.store.record_receipt(
                session_id="s1",
                task_id=f"other-{index}",
                source="test",
                tool_name="Bash",
                command_text=f"pytest other-{index}",
                exit_code=0,
                metadata={"stdout_sha256": "abc"},
            )

        listing = self.server.list_recent_receipts("s1", "t1", limit=1)

        self.assertIn(receipt.receipt_id, listing)
        self.assertIn("pytest -q --taskless", listing)

    def test_mission_scope_receipts_scan_long_window_before_filtering(self) -> None:
        original_limit = self.server.MISSION_RECEIPT_SCAN_LIMIT
        self.server.MISSION_RECEIPT_SCAN_LIMIT = 120
        try:
            self.server.mission_lock("s1", "target-task", "goal", ["tests pass"])
            target = self.taskless_receipt(command_text="pytest target")
            for index in range(100):
                self.store.record_receipt(
                    session_id="s1",
                    task_id=f"other-{index}",
                    source="test",
                    tool_name="Bash",
                    command_text=f"pytest other-{index}",
                    exit_code=0,
                    metadata={"stdout_sha256": "abc"},
                )

            listing = self.server.list_recent_receipts("s1", "target-task", limit=1)
        finally:
            self.server.MISSION_RECEIPT_SCAN_LIMIT = original_limit

        self.assertIn(target.receipt_id, listing)
        self.assertIn("pytest target", listing)

    def test_list_recent_receipts_empty_task_scope_is_session_wide_with_multiple_active(self) -> None:
        self.server.mission_lock("s1", "old-task", "old goal", ["tests pass"])
        old_receipt = self.store.record_receipt(
            session_id="s1",
            task_id="old-task",
            source="test",
            tool_name="Bash",
            command_text="pytest old",
            exit_code=0,
            metadata={"stdout_sha256": "abc"},
        )
        self.server.mission_lock("s1", "new-task", "new goal", ["tests pass"])
        fresh_receipt = self.taskless_receipt(command_text="pytest new")

        listing = self.server.list_recent_receipts("s1", "")

        self.assertIn(fresh_receipt.receipt_id, listing)
        self.assertIn(old_receipt.receipt_id, listing)
        self.assertIn("pytest old", listing)

    def test_turn_end_gate_still_rejects_other_task_receipt_from_same_session(self) -> None:
        self.server.mission_lock("s1", "t1", "goal", ["tests pass"])
        receipt = self.task_receipt("s1", "other-task")

        with self.assertRaisesRegex(ValueError, "belongs to task_id='other-task'"):
            self.server.turn_end_gate(
                session_id="s1",
                task_id="t1",
                stop_condition="slice_verified",
                work_summary="Tried to close this task using another task receipt.",
                receipt_ids=[receipt.receipt_id],
            )

    def test_turn_end_gate_explains_receipt_from_other_session(self) -> None:
        self.server.mission_lock("s1", "t1", "goal", ["tests pass"])
        receipt = self.taskless_receipt(session_id="other-session")

        with self.assertRaisesRegex(ValueError, "belongs to session_id='other-session'"):
            self.server.turn_end_gate(
                session_id="s1",
                task_id="t1",
                stop_condition="slice_verified",
                work_summary="Tried to close this task using another session receipt.",
                receipt_ids=[receipt.receipt_id],
            )

    def test_completion_gate_still_rejects_other_task_receipt_from_same_session(self) -> None:
        self.server.mission_lock("s1", "t1", "goal", ["tests pass"])
        receipt = self.task_receipt("s1", "other-task")

        with self.assertRaisesRegex(ValueError, "belongs to task_id='other-task'"):
            self.server.completion_gate(
                session_id="s1",
                task_id="t1",
                criterion_receipt_map=[{"criterion": "tests pass", "receipt_ids": [receipt.receipt_id]}],
                completion_summary="Tried to complete this task using another task receipt.",
            )

    def test_completion_gate_explains_receipt_from_other_session(self) -> None:
        self.server.mission_lock("s1", "t1", "goal", ["tests pass"])
        receipt = self.taskless_receipt(session_id="other-session")

        with self.assertRaisesRegex(ValueError, "belongs to session_id='other-session'"):
            self.server.completion_gate(
                session_id="s1",
                task_id="t1",
                criterion_receipt_map=[{"criterion": "tests pass", "receipt_ids": [receipt.receipt_id]}],
                completion_summary="Tried to complete this task using another session receipt.",
            )

    def test_turn_end_gate_rejects_taskless_receipt_from_before_mission_lock_as_stale(self) -> None:
        receipt = self.taskless_receipt()
        self.server.mission_lock("s1", "t1", "goal", ["tests pass"])

        rejected = self.server.turn_end_gate(
            session_id="s1",
            task_id="t1",
            stop_condition="slice_verified",
            work_summary="Tried to close the mission using a pre-lock taskless receipt.",
            receipt_ids=[receipt.receipt_id],
        )

        self.assertIn("REJECTED", rejected)
        self.assertIn("stale receipt", rejected.lower())

    def test_completion_gate_rejects_taskless_receipt_from_before_mission_lock_as_stale(self) -> None:
        receipt = self.taskless_receipt()
        self.server.mission_lock("s1", "t1", "goal", ["tests pass"])

        rejected = self.server.completion_gate(
            session_id="s1",
            task_id="t1",
            criterion_receipt_map=[{"criterion": "tests pass", "receipt_ids": [receipt.receipt_id]}],
            completion_summary="Tried to complete the mission using a pre-lock taskless receipt.",
        )

        self.assertIn("REJECTED", rejected)
        self.assertIn("stale receipt", rejected.lower())

    def task_receipt(self, session_id: str, task_id: str):
        return self.store.record_receipt(
            session_id=session_id,
            task_id=task_id,
            source="test",
            tool_name="Bash",
            command_text="pytest -q",
            exit_code=0,
            metadata={"stdout_sha256": "abc"},
        )


if __name__ == "__main__":
    unittest.main()
