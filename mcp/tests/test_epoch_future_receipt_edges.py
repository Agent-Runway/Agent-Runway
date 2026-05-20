from __future__ import annotations

import importlib
import os
import tempfile
import unittest
from pathlib import Path


class EpochFutureReceiptEdgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "state.db"
        self.secret_path = Path(self.temp_dir.name) / "secret.key"
        os.environ["ILH_DB_PATH"] = str(self.db_path)
        os.environ["ILH_SECRET_PATH"] = str(self.secret_path)
        os.environ["ILH_HARNESS_SECRET"] = "a" * 64

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
        os.environ.pop("ILH_HARNESS_SECRET", None)

    def make_receipt(self, session_id: str, task_id: str | None, created_at: str):
        return self.store.record_receipt(
            session_id=session_id,
            task_id=task_id,
            source="test",
            tool_name="Bash",
            command_text="pytest -q",
            exit_code=0,
            metadata={"stdout_sha256": created_at},
            created_at=created_at,
        )

    def test_turn_end_gate_accepts_future_timestamp_receipt_recorded_after_mission_lock(self) -> None:
        self.server.mission_lock("s1", "t1", "goal", ["tests pass"])
        receipt = self.make_receipt("s1", "t1", "2099-01-01T00:00:00Z")

        approved = self.server.turn_end_gate(
            session_id="s1",
            task_id="t1",
            stop_condition="slice_verified",
            work_summary="Used a post-lock receipt whose wall-clock timestamp is far in the future.",
            receipt_ids=[receipt.receipt_id],
        )

        self.assertIn("APPROVED", approved)

    def test_completion_gate_rejects_future_timestamp_taskless_receipt_after_mission_lock(self) -> None:
        self.server.mission_lock("s1", "t1", "goal", ["tests pass"])
        receipt = self.make_receipt("s1", None, "2099-01-01T00:00:00Z")

        rejected = self.server.completion_gate(
            session_id="s1",
            task_id="t1",
            criterion_receipt_map=[{"criterion": "tests pass", "receipt_ids": [receipt.receipt_id]}],
            completion_summary="Completed the mission with a fresh taskless receipt that carries a future timestamp.",
        )

        self.assertIn("REJECTED", rejected)
        self.assertIn("taskless receipt", rejected)
        self.assertIn("Receipts are not mission-scoped", rejected)

    def test_turn_end_and_completion_gate_warn_on_future_timestamp_taskless_receipt(self) -> None:
        self.server.mission_lock("s1", "t2", "goal", ["tests pass"])
        receipt = self.make_receipt("s1", None, "2099-01-01T00:00:00Z")

        turn_end = self.server.turn_end_gate(
            session_id="s1",
            task_id="t2",
            stop_condition="slice_verified",
            work_summary="Used a future-dated taskless receipt after mission lock for this verified slice.",
            receipt_ids=[receipt.receipt_id],
        )
        completion = self.server.completion_gate(
            session_id="s1",
            task_id="t2",
            criterion_receipt_map=[{"criterion": "tests pass", "receipt_ids": [receipt.receipt_id]}],
            completion_summary="Completed with the same future-dated taskless receipt after mission lock.",
        )

        self.assertIn("Receipts are not mission-scoped", turn_end)
        self.assertIn("Receipts are not mission-scoped", completion)

    def test_prelock_future_timestamp_receipt_is_still_rejected_by_sequence_epoch(self) -> None:
        receipt = self.make_receipt("s1", "t1", "2099-01-01T00:00:00Z")
        self.server.mission_lock("s1", "t1", "goal", ["tests pass"])

        rejected = self.server.turn_end_gate(
            session_id="s1",
            task_id="t1",
            stop_condition="slice_verified",
            work_summary="Tried to use a pre-lock receipt whose timestamp alone looks fresh.",
            receipt_ids=[receipt.receipt_id],
        )

        self.assertIn("REJECTED", rejected)
        self.assertIn("stale receipt", rejected.lower())


if __name__ == "__main__":
    unittest.main()
