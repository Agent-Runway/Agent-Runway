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


class ReceiptScopeValidationEdgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        os.environ["ILH_DB_PATH"] = str(Path(self.temp_dir.name) / "state.db")
        os.environ["ILH_SECRET_PATH"] = str(Path(self.temp_dir.name) / "secret.key")
        self.server = importlib.reload(importlib.import_module("server"))
        self.store = self.server.store

    def tearDown(self) -> None:
        self.temp_dir.cleanup()
        os.environ.pop("ILH_DB_PATH", None)
        os.environ.pop("ILH_SECRET_PATH", None)

    def taskless_receipt(
        self,
        tool_name: str = "Bash",
        command_text: str = "pytest -q",
        metadata: dict[str, object] | None = None,
    ):
        return self.store.record_receipt(
            session_id="s1",
            task_id=None,
            source="test",
            tool_name=tool_name,
            command_text=command_text,
            exit_code=0,
            metadata=metadata or {"stdout_sha256": "abc"},
        )

    def test_turn_end_gate_rejects_string_receipt_ids_before_lookup(self) -> None:
        self.server.mission_lock("s1", "t1", "goal", ["tests pass"])
        receipt = self.taskless_receipt()

        with self.assertRaisesRegex(ValueError, "receipt_ids must be a list"):
            self.server.turn_end_gate(
                session_id="s1",
                task_id="t1",
                stop_condition="slice_verified",
                work_summary="Tried to pass a bare receipt id string instead of a list.",
                receipt_ids=receipt.receipt_id,  # type: ignore[arg-type]
            )

    def test_turn_end_gate_rejects_non_string_receipt_id_before_lookup(self) -> None:
        self.server.mission_lock("s1", "t1", "goal", ["tests pass"])
        receipt = self.taskless_receipt()

        with self.assertRaisesRegex(ValueError, "receipt_ids must be a list"):
            self.server.turn_end_gate(
                session_id="s1",
                task_id="t1",
                stop_condition="slice_verified",
                work_summary="Tried to pass a non-string receipt id beside a valid id.",
                receipt_ids=[receipt.receipt_id, 123],  # type: ignore[list-item]
            )

    def test_turn_end_gate_rejects_blank_receipt_id_before_lookup(self) -> None:
        self.server.mission_lock("s1", "t1", "goal", ["tests pass"])

        with self.assertRaisesRegex(ValueError, "receipt_ids must be a list"):
            self.server.turn_end_gate(
                session_id="s1",
                task_id="t1",
                stop_condition="slice_verified",
                work_summary="Tried to pass a blank receipt id instead of a real receipt id.",
                receipt_ids=["   "],
            )

    def test_completion_gate_rejects_string_receipt_ids_before_lookup(self) -> None:
        self.server.mission_lock("s1", "t1", "goal", ["tests pass"])
        receipt = self.taskless_receipt()

        with self.assertRaisesRegex(ValueError, "receipt_ids must be a list"):
            self.server.completion_gate(
                session_id="s1",
                task_id="t1",
                criterion_receipt_map=[{"criterion": "tests pass", "receipt_ids": receipt.receipt_id}],
                completion_summary="Tried to pass a bare receipt id string in the completion map.",
            )

    def test_completion_gate_rejects_non_string_receipt_id_before_lookup(self) -> None:
        self.server.mission_lock("s1", "t1", "goal", ["tests pass"])
        receipt = self.taskless_receipt()

        with self.assertRaisesRegex(ValueError, "receipt_ids must be a list"):
            self.server.completion_gate(
                session_id="s1",
                task_id="t1",
                criterion_receipt_map=[{"criterion": "tests pass", "receipt_ids": [receipt.receipt_id, 123]}],
                completion_summary="Tried to pass a non-string receipt id in the completion map.",
            )

    def test_completion_gate_rejects_blank_receipt_id_before_lookup(self) -> None:
        self.server.mission_lock("s1", "t1", "goal", ["tests pass"])

        with self.assertRaisesRegex(ValueError, "receipt_ids must be a list"):
            self.server.completion_gate(
                session_id="s1",
                task_id="t1",
                criterion_receipt_map=[{"criterion": "tests pass", "receipt_ids": ["   "]}],
                completion_summary="Tried to pass a blank receipt id in the completion map.",
            )

    def test_verify_receipt_integrity_rejects_partial_missing_receipt_ids(self) -> None:
        self.server.mission_lock("s1", "t1", "goal", ["tests pass"])
        receipt = self.taskless_receipt()

        with self.assertRaisesRegex(ValueError, "was not found"):
            self.server.verify_receipt_integrity("s1", [receipt.receipt_id, "missing-receipt"], "")

    def test_verify_receipt_integrity_explains_task_scope_mismatch(self) -> None:
        self.server.mission_lock("s1", "t1", "goal", ["tests pass"])
        receipt = self.store.record_receipt(
            session_id="s1",
            task_id="other-task",
            source="test",
            tool_name="Bash",
            command_text="pytest -q",
            exit_code=0,
            metadata={"stdout_sha256": "abc"},
        )

        with self.assertRaisesRegex(ValueError, "belongs to task_id='other-task'"):
            self.server.verify_receipt_integrity("s1", [receipt.receipt_id], "t1")

    def test_completion_gate_rejects_taskless_verification_before_taskless_mutation(self) -> None:
        self.server.mission_lock("s1", "t1", "goal", ["tests pass"])
        verification = self.taskless_receipt(command_text="pytest -q")
        self.taskless_receipt(tool_name="Edit", command_text="src/core.py", metadata={"file_path": "src/core.py"})

        rejected = self.server.completion_gate(
            session_id="s1",
            task_id="t1",
            criterion_receipt_map=[{"criterion": "tests pass", "receipt_ids": [verification.receipt_id]}],
            completion_summary="Tried to complete using verification from before a taskless edit.",
        )

        self.assertIn("REJECTED", rejected)
        self.assertIn("stale evidence", rejected)

    def test_turn_end_gate_counts_taskless_receipt_duration_against_time_budget(self) -> None:
        self.server.mission_lock("s1", "t1", "goal", ["tests pass"], time_budget_minutes=1)
        receipt = self.taskless_receipt(metadata={"stdout_sha256": "abc", "duration_seconds": 120})

        rejected = self.server.turn_end_gate(
            session_id="s1",
            task_id="t1",
            stop_condition="slice_verified",
            work_summary="Tried to claim another verified slice after time budget exhaustion.",
            receipt_ids=[receipt.receipt_id],
        )

        self.assertIn("REJECTED", rejected)
        self.assertIn("time budget is exhausted", rejected)

    def test_governance_records_accept_taskless_receipts_after_mission_lock(self) -> None:
        self.server.mission_lock("s1", "t1", "goal", ["tests pass"])
        receipt = self.taskless_receipt()

        decision = self.server.record_decision_record(
            "s1",
            "t1",
            "use taskless host receipt",
            "accept taskless receipt when it is fresh in the same mission session",
            ["reject all taskless receipts"],
            [receipt.receipt_id],
            "reversible",
            ["host emits task-scoped receipts again"],
        )
        counterexample = self.server.record_counterexample_check(
            "s1",
            "t1",
            "taskless receipt could be outside mission scope",
            ["checked mission epoch and session id"],
            "receipt was recorded after mission lock in the same session",
            [receipt.receipt_id],
            "taskless receipts still carry weaker provenance than task-scoped receipts",
        )

        self.assertIn("DECISION RECORDED", decision)
        self.assertIn("COUNTEREXAMPLE CHECK RECORDED", counterexample)

    def test_user_authorization_recorded_after_taskless_receipt_is_fresh(self) -> None:
        self.server.mission_lock("s1", "t1", "goal", ["tests pass"])
        self.taskless_receipt()

        self.server.record_user_authorization(
            "s1",
            "t1",
            "push commit",
            "single git push after tests",
            "Yes, push it.",
            True,
            900,
        )
        status = json.loads(self.server.authorization_status("s1", "t1"))

        self.assertTrue(status["authorization"]["fresh"])


if __name__ == "__main__":
    unittest.main()
