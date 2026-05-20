from __future__ import annotations

import importlib
import os
import tempfile
import unittest
from pathlib import Path


class CompletionGateReceiptMapEdgesTestCase(unittest.TestCase):
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

    def make_receipt(self, task_id: str, command: str):
        return self.store.record_receipt(
            session_id="s1",
            task_id=task_id,
            source="test",
            tool_name="Bash",
            command_text=command,
            exit_code=0,
            metadata={"stdout_sha256": "abc"},
        )

    def approve_turn(self, task_id: str, receipt_ids: list[str]) -> None:
        approved = self.server.turn_end_gate(
            "s1",
            task_id,
            "slice_verified",
            "Verified the current slice with all criterion receipts before completion.",
            receipt_ids,
        )
        self.assertIn("APPROVED", approved)

    def test_completion_gate_accepts_distinct_receipts_for_distinct_criteria(self) -> None:
        self.server.mission_lock(
            "s1", "distinct-task", "goal", ["tests pass", "lint passes"]
        )
        tests_receipt = self.make_receipt("distinct-task", "pytest -q")
        lint_receipt = self.make_receipt("distinct-task", "ruff check .")
        self.approve_turn("distinct-task", [tests_receipt.receipt_id, lint_receipt.receipt_id])

        approved = self.server.completion_gate(
            session_id="s1",
            task_id="distinct-task",
            criterion_receipt_map=[
                {"criterion": "tests pass", "receipt_ids": [tests_receipt.receipt_id]},
                {"criterion": "lint passes", "receipt_ids": [lint_receipt.receipt_id]},
            ],
            completion_summary="Mapped separate verification receipts to separate completion criteria without reusing evidence.",
        )

        self.assertIn("APPROVED", approved)
        self.assertIn("receipts_used: 2", approved)

    def test_completion_gate_accepts_multiple_receipts_for_one_criterion(self) -> None:
        self.server.mission_lock("s1", "multi-receipt-task", "goal", ["tests pass"])
        unit_receipt = self.make_receipt(
            "multi-receipt-task", "pytest mcp/tests/test_runtime.py -q"
        )
        regression_receipt = self.make_receipt(
            "multi-receipt-task", "pytest mcp/tests/test_runtime_regressions.py -q"
        )
        self.approve_turn(
            "multi-receipt-task",
            [unit_receipt.receipt_id, regression_receipt.receipt_id],
        )

        approved = self.server.completion_gate(
            session_id="s1",
            task_id="multi-receipt-task",
            criterion_receipt_map=[
                {
                    "criterion": "tests pass",
                    "receipt_ids": [unit_receipt.receipt_id, regression_receipt.receipt_id],
                }
            ],
            completion_summary="Mapped two distinct test receipts to one criterion to preserve legitimate evidence aggregation.",
        )

        self.assertIn("APPROVED", approved)
        self.assertIn("receipts_used: 2", approved)


if __name__ == "__main__":
    unittest.main()
