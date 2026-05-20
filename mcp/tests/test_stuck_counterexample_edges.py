from __future__ import annotations

import importlib
import os
import tempfile
import unittest
from pathlib import Path


class StuckCounterexampleEdgesTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        os.environ["ILH_DB_PATH"] = str(Path(self.temp_dir.name) / "state.db")
        os.environ["ILH_SECRET_PATH"] = str(Path(self.temp_dir.name) / "secret.key")
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

    def make_receipt(self, task_id: str, command: str = "pytest -q"):
        return self.store.record_receipt(
            session_id="s1",
            task_id=task_id,
            source="stuck-counterexample-test",
            tool_name="Bash",
            command_text=command,
            exit_code=1,
            metadata={"stdout_sha256": "abc"},
        )

    def prepare_stuck_mission(self, task_id: str, **mission_kwargs):
        self.server.mission_lock(
            "s1",
            task_id,
            "goal",
            ["criterion"],
            counterexample_required=True,
            retry_budget=1,
            **mission_kwargs,
        )
        receipt = self.make_receipt(task_id)
        self.server.record_stuck_attempt(
            "s1", task_id, "strategy-a", "first failed strategy", [receipt.receipt_id]
        )
        return receipt

    def escalate(self, task_id: str, receipt_id: str, reason: str) -> str:
        return self.server.turn_end_gate(
            session_id="s1",
            task_id=task_id,
            stop_condition="stuck_escalation",
            work_summary="Recorded stuck strategy evidence and evaluated escalation requirements.",
            receipt_ids=[receipt_id],
            reason_for_stopping=reason,
        )

    def record_counterexample(self, task_id: str, receipt_id: str) -> None:
        self.server.record_counterexample_check(
            "s1",
            task_id,
            "local retries may still find a solution",
            ["tried an independent command path"],
            "no new path survived the check",
            [receipt_id],
            "counterexample check is scoped to the current mission receipt.",
        )

    def test_stuck_escalation_rejects_missing_counterexample_check(self) -> None:
        receipt = self.prepare_stuck_mission("counterexample-stuck")

        rejected = self.escalate(
            "counterexample-stuck",
            receipt.receipt_id,
            "Retry budget is exhausted, but counterexample work has not been recorded.",
        )

        self.assertIn("REJECTED", rejected)
        self.assertIn("counterexample", rejected.lower())

    def test_stuck_escalation_accepts_fresh_counterexample_check(self) -> None:
        receipt = self.prepare_stuck_mission("counterexample-stuck-ok")
        self.record_counterexample("counterexample-stuck-ok", receipt.receipt_id)

        approved = self.escalate(
            "counterexample-stuck-ok",
            receipt.receipt_id,
            "Retry budget is exhausted after a recorded counterexample check and further retries repeat the same path.",
        )

        self.assertIn("APPROVED", approved)

    def test_stuck_escalation_rejects_missing_required_decision_record(self) -> None:
        receipt = self.prepare_stuck_mission(
            "decision-record-stuck", decision_records_required=True
        )
        self.record_counterexample("decision-record-stuck", receipt.receipt_id)

        rejected = self.escalate(
            "decision-record-stuck",
            receipt.receipt_id,
            "Retry budget is exhausted after counterexample work, but no decision record exists.",
        )

        self.assertIn("REJECTED", rejected)
        self.assertIn("decision record", rejected.lower())

    def test_stuck_escalation_accepts_required_decision_record(self) -> None:
        receipt = self.prepare_stuck_mission(
            "decision-record-stuck-ok", decision_records_required=True
        )
        self.record_counterexample("decision-record-stuck-ok", receipt.receipt_id)
        self.server.record_decision_record(
            "s1",
            "decision-record-stuck-ok",
            "escalate after bounded retries",
            "stop local retries after the recorded counterexample check",
            ["repeat the same failed retry path"],
            [receipt.receipt_id],
        )

        approved = self.escalate(
            "decision-record-stuck-ok",
            receipt.receipt_id,
            "Retry budget is exhausted after counterexample and decision-record evidence.",
        )

        self.assertIn("APPROVED", approved)

    def test_counterexample_check_rejects_wrong_task_receipt(self) -> None:
        self.prepare_stuck_mission("counterexample-wrong-task")
        other_receipt = self.store.record_receipt(
            session_id="s1",
            task_id="other-task",
            source="stuck-counterexample-test",
            tool_name="Bash",
            command_text="pytest other",
            exit_code=1,
            metadata={"stdout_sha256": "other"},
        )

        with self.assertRaisesRegex(ValueError, "belongs to task_id='other-task'"):
            self.record_counterexample("counterexample-wrong-task", other_receipt.receipt_id)

    def test_counterexample_check_rejects_wrong_session_receipt(self) -> None:
        self.prepare_stuck_mission("counterexample-wrong-session")
        other_receipt = self.store.record_receipt(
            session_id="other-session",
            task_id="counterexample-wrong-session",
            source="stuck-counterexample-test",
            tool_name="Bash",
            command_text="pytest other-session",
            exit_code=1,
            metadata={"stdout_sha256": "other-session"},
        )

        with self.assertRaisesRegex(ValueError, "belongs to session_id='other-session'"):
            self.record_counterexample(
                "counterexample-wrong-session", other_receipt.receipt_id
            )

    def test_counterexample_check_rejects_partial_missing_receipt(self) -> None:
        receipt = self.prepare_stuck_mission("counterexample-partial-missing")

        with self.assertRaisesRegex(ValueError, "was not found"):
            self.server.record_counterexample_check(
                "s1",
                "counterexample-partial-missing",
                "missing receipts could be ignored when one receipt is valid",
                ["included one valid and one missing receipt id"],
                "missing receipt id was rejected before recording the check",
                [receipt.receipt_id, "missing-counterexample-receipt"],
                "partial receipt lists must not record governance checks.",
            )

    def test_counterexample_check_rejects_prelock_stale_receipt(self) -> None:
        stale_receipt = self.make_receipt("counterexample-stale")
        self.server.mission_lock(
            "s1",
            "counterexample-stale",
            "goal",
            ["criterion"],
            counterexample_required=True,
            retry_budget=1,
        )

        with self.assertRaisesRegex(ValueError, "stale receipt"):
            self.record_counterexample("counterexample-stale", stale_receipt.receipt_id)

    def test_counterexample_check_rejects_prelock_taskless_stale_receipt(self) -> None:
        stale_receipt = self.store.record_receipt(
            session_id="s1",
            task_id=None,
            source="stuck-counterexample-test",
            tool_name="Bash",
            command_text="pytest before mission",
            exit_code=1,
            metadata={"stdout_sha256": "taskless-stale"},
        )
        self.server.mission_lock(
            "s1",
            "counterexample-taskless-stale",
            "goal",
            ["criterion"],
            counterexample_required=True,
            retry_budget=1,
        )

        with self.assertRaisesRegex(ValueError, "stale receipt"):
            self.record_counterexample(
                "counterexample-taskless-stale", stale_receipt.receipt_id
            )


if __name__ == "__main__":
    unittest.main()
