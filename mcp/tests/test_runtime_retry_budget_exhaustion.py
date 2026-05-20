from __future__ import annotations

import importlib
import json
import os
import tempfile
import unittest
from pathlib import Path


class RuntimeRetryBudgetExhaustionTestCase(unittest.TestCase):
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

    def test_budget_status_guides_escalation_after_retry_budget_is_exhausted(self) -> None:
        self.server.mission_lock(
            "s1", "retry-guide-task", "debug failure", ["tests pass"], retry_budget=2
        )
        first = self.make_bash_receipt(
            "s1", "retry-guide-task", "pytest failing_test.py", exit_code=1
        )
        second = self.make_bash_receipt(
            "s1", "retry-guide-task", "python repro.py", exit_code=1
        )
        self.server.record_stuck_attempt(
            "s1", "retry-guide-task", "pytest-repro", "pytest failure reproduced", [first.receipt_id]
        )
        self.server.record_stuck_attempt(
            "s1", "retry-guide-task", "direct-repro", "direct script reproduced failure", [second.receipt_id]
        )

        status = json.loads(self.server.budget_status("s1", "retry-guide-task"))

        self.assertEqual(status["retries_remaining"], 0)
        self.assertTrue(status["retry_budget_exhausted"])
        self.assertTrue(status["budget_exhausted"])
        self.assertFalse(status["slice_budget_exhausted"])
        self.assertFalse(status["time_budget_exhausted"])
        self.assertIn("stuck_escalation", status["wrap_up_guidance"])
        packet = json.loads(self.server.export_handoff_packet("s1", "retry-guide-task"))
        self.assertEqual(packet["recommended_next_action"], status["wrap_up_guidance"])

    def test_retry_budget_exhaustion_does_not_block_verified_slice(self) -> None:
        self.server.mission_lock(
            "s1", "retry-slice-task", "debug then verify", ["tests pass"], retry_budget=1
        )
        failure = self.make_bash_receipt(
            "s1", "retry-slice-task", "pytest failing_test.py", exit_code=1
        )
        self.server.record_stuck_attempt(
            "s1", "retry-slice-task", "pytest-repro", "pytest failure reproduced", [failure.receipt_id]
        )

        success = self.make_bash_receipt("s1", "retry-slice-task", "pytest fixed_test.py")
        result = self.server.turn_end_gate(
            session_id="s1",
            task_id="retry-slice-task",
            stop_condition="slice_verified",
            work_summary="Verified a new non-retry slice after the prior retry budget was exhausted.",
            receipt_ids=[success.receipt_id],
        )

        self.assertIn("APPROVED", result)
        self.assertIn("stop_condition: slice_verified", result)


if __name__ == "__main__":
    unittest.main()
