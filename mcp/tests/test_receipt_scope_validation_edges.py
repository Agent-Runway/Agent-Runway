from __future__ import annotations

import importlib
import asyncio
import inspect
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
        tool_name: str = "Bash",
        command_text: str = "pytest -q",
        metadata: dict[str, object] | None = None,
        *,
        source: str = "test",
    ):
        return self.store.record_receipt(
            session_id="s1",
            task_id=None,
            source=source,
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

    def test_turn_end_gate_rejects_empty_receipt_ids_before_scope_lookup(self) -> None:
        self.server.mission_lock("s1", "t1", "goal", ["tests pass"])

        with self.assertRaisesRegex(ValueError, "at least one receipt_id"):
            self.server.turn_end_gate(
                session_id="s1",
                task_id="t1",
                stop_condition="slice_verified",
                work_summary="Tried to stop without citing any concrete receipt id.",
                receipt_ids=[],
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

    def test_completion_gate_signature_keeps_summary_required_before_optional_map(self) -> None:
        params = inspect.signature(self.server.completion_gate).parameters

        self.assertEqual(
            ["session_id", "task_id", "completion_summary", "criterion_receipt_map"],
            list(params)[:4],
        )
        self.assertIs(inspect.Signature.empty, params["completion_summary"].default)
        self.assertIsNone(params["criterion_receipt_map"].default)

    def test_completion_gate_mcp_schema_exposes_optional_criterion_map(self) -> None:
        async def get_schema() -> dict[str, object]:
            tools = await self.server.mcp.list_tools()
            match = [tool for tool in tools if tool.name == "completion_gate"][0]
            return match.inputSchema

        schema = asyncio.run(get_schema())
        properties = schema["properties"]

        self.assertIn("criterion_receipt_map", properties)
        criterion_schema = properties["criterion_receipt_map"]
        self.assertEqual(None, criterion_schema["default"])
        self.assertIn({"type": "null"}, criterion_schema["anyOf"])
        self.assertIn("array", {item.get("type") for item in criterion_schema["anyOf"]})
        self.assertEqual(["session_id", "task_id", "completion_summary"], schema["required"])

    def test_completion_gate_rejects_missing_criterion_map_as_gate_denial(self) -> None:
        self.server.mission_lock("s1", "t1", "goal", ["tests pass"])

        rejected = self.server.completion_gate(
            session_id="s1",
            task_id="t1",
            completion_summary="Tried to complete without any criterion to receipt mapping.",
        )

        self.assertIn("REJECTED", rejected)
        self.assertIn("criterion_receipt_map is required", rejected)
        self.assertIn("Missing criterion mappings", rejected)
        status = self.server.mission_status("s1", "t1")
        self.assertIn("status: active", status)
        approval = self.store.latest_approval("s1", "t1", "completion_gate")
        self.assertIsNotNone(approval)
        self.assertFalse(approval.approved)
        self.assertEqual([], approval.meta["criterion_receipt_map"])
        budget = json.loads(self.server.budget_status("s1", "t1"))
        self.assertFalse(budget["latest_completion_gate_fresh"])
        self.assertEqual([], self.store.list_recent_receipts("s1"))

    def test_completion_gate_rejects_empty_criterion_map_as_gate_denial(self) -> None:
        self.server.mission_lock("s1", "t1", "goal", ["tests pass"])

        rejected = self.server.completion_gate(
            session_id="s1",
            task_id="t1",
            criterion_receipt_map=[],
            completion_summary="Tried to complete with an empty criterion to receipt mapping.",
        )

        self.assertIn("REJECTED", rejected)
        self.assertIn("Missing criterion mappings", rejected)
        status = self.server.mission_status("s1", "t1")
        self.assertIn("status: active", status)
        approval = self.store.latest_approval("s1", "t1", "completion_gate")
        self.assertIsNotNone(approval)
        self.assertFalse(approval.approved)
        self.assertEqual([], approval.meta["criterion_receipt_map"])

    def test_completion_gate_accepts_existing_positional_call_order(self) -> None:
        self.server.mission_lock("s1", "t1", "goal", ["tests pass"])
        receipt = self.store.record_receipt(
            session_id="s1",
            task_id="t1",
            source="test",
            tool_name="Bash",
            command_text="pytest -q",
            exit_code=0,
            metadata={"stdout_sha256": "abc"},
        )
        turn = self.server.turn_end_gate(
            "s1",
            "t1",
            "slice_verified",
            "Verified the current slice before using historical positional completion arguments.",
            [receipt.receipt_id],
        )
        self.assertIn("APPROVED", turn)

        approved = self.server.completion_gate(
            "s1",
            "t1",
            [{"criterion": "tests pass", "receipt_ids": [receipt.receipt_id]}],
            "Mapped evidence using the historical positional argument order.",
        )

        self.assertIn("APPROVED", approved)

    def test_completion_gate_rejects_non_list_criterion_map_before_lookup(self) -> None:
        self.server.mission_lock("s1", "t1", "goal", ["tests pass"])

        with self.assertRaisesRegex(ValueError, "criterion_receipt_map must be a list"):
            self.server.completion_gate(
                session_id="s1",
                task_id="t1",
                criterion_receipt_map={"criterion": "tests pass", "receipt_ids": []},
                completion_summary="Tried to pass an object instead of a criterion map list.",
            )

    def test_verify_receipt_integrity_rejects_empty_receipt_ids_before_scope_lookup(self) -> None:
        self.server.mission_lock("s1", "t1", "goal", ["tests pass"])

        with self.assertRaisesRegex(ValueError, "at least one receipt_id"):
            self.server.verify_receipt_integrity("s1", [], "t1")

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
        self.taskless_receipt(
            tool_name="Edit",
            command_text="src/core.py",
            metadata={"file_path": "src/core.py"},
            source="claude-hook",
        )

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

        stuck = self.server.record_stuck_attempt(
            "s1",
            "t1",
            "strategy-a",
            "Recorded a bounded failed strategy with same-session taskless evidence.",
            [receipt.receipt_id],
        )
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

        self.assertIn("STUCK ATTEMPT RECORDED", stuck)
        self.assertIn("DECISION RECORDED", decision)
        self.assertIn("COUNTEREXAMPLE CHECK RECORDED", counterexample)

    def test_governance_records_reject_taskless_receipts_with_multiple_active_missions(self) -> None:
        self.server.mission_lock("s1", "task-a", "goal a", ["tests pass"])
        self.server.mission_lock("s1", "task-b", "goal b", ["tests pass"])
        receipt = self.taskless_receipt(command_text="pytest shared")

        with self.assertRaisesRegex(ValueError, "taskless receipt.*multiple active missions"):
            self.server.record_stuck_attempt(
                "s1",
                "task-a",
                "strategy-a",
                "Tried a strategy using taskless evidence while another mission was active.",
                [receipt.receipt_id],
            )
        with self.assertRaisesRegex(ValueError, "taskless receipt.*multiple active missions"):
            self.server.record_decision_record(
                "s1",
                "task-a",
                "choose scoped evidence",
                "reject ambiguous taskless evidence",
                ["accept ambiguous taskless evidence"],
                [receipt.receipt_id],
                "reversible",
                ["host emits task-scoped receipts"],
            )
        with self.assertRaisesRegex(ValueError, "taskless receipt.*multiple active missions"):
            self.server.record_counterexample_check(
                "s1",
                "task-a",
                "taskless evidence could belong to a sibling mission",
                ["created a second active mission in the same session"],
                "the taskless receipt stayed ambiguous",
                [receipt.receipt_id],
                "task-scoped receipt remains required",
            )

    def test_governance_records_reject_empty_receipt_ids_before_scope_lookup(self) -> None:
        self.server.mission_lock("s1", "t1", "goal", ["tests pass"])

        expected_diagnostics = [
            "runtime-backed records require captured receipt evidence",
            "Hosts without automatic receipt capture cannot satisfy this field with an empty list",
            "instead of fabricating receipt ids",
        ]

        with self.assertRaises(ValueError) as stuck_ctx:
            self.server.record_stuck_attempt(
                "s1",
                "t1",
                "strategy-a",
                "Tried a strategy but supplied no receipt evidence.",
                [],
            )
        stuck_message = str(stuck_ctx.exception)
        self.assertIn("receipt_ids must include at least one receipt_id", stuck_message)
        for diagnostic in expected_diagnostics:
            self.assertIn(diagnostic, stuck_message)

        with self.assertRaises(ValueError) as decision_ctx:
            self.server.record_decision_record(
                "s1",
                "t1",
                "choose path",
                "choose the minimal path",
                ["choose the broad path"],
                [],
                "reversible",
                [],
            )
        decision_message = str(decision_ctx.exception)
        self.assertIn("evidence_receipt_ids must include at least one receipt_id", decision_message)
        for diagnostic in expected_diagnostics:
            self.assertIn(diagnostic, decision_message)

        with self.assertRaises(ValueError) as counterexample_ctx:
            self.server.record_counterexample_check(
                "s1",
                "t1",
                "the claim could be false",
                ["looked for a contrary case"],
                "no receipt evidence was supplied",
                [],
                "unverified without receipts",
            )
        counterexample_message = str(counterexample_ctx.exception)
        self.assertIn("receipt_ids must include at least one receipt_id", counterexample_message)
        for diagnostic in expected_diagnostics:
            self.assertIn(diagnostic, counterexample_message)

    def test_governance_records_explain_missing_receipt_ids(self) -> None:
        self.server.mission_lock("s1", "t1", "goal", ["tests pass"])

        with self.assertRaisesRegex(ValueError, "receipt_id 'missing-receipt' was not found"):
            self.server.record_stuck_attempt(
                "s1",
                "t1",
                "strategy-a",
                "Tried a strategy with a missing receipt id.",
                ["missing-receipt"],
            )
        with self.assertRaisesRegex(ValueError, "receipt_id 'missing-receipt' was not found"):
            self.server.record_decision_record(
                "s1",
                "t1",
                "choose scoped evidence",
                "reject missing receipt evidence",
                ["accept missing receipt evidence"],
                ["missing-receipt"],
                "reversible",
                ["new scoped evidence appears"],
            )
        with self.assertRaisesRegex(ValueError, "receipt_id 'missing-receipt' was not found"):
            self.server.record_counterexample_check(
                "s1",
                "t1",
                "missing receipts should not satisfy a counterexample check",
                ["submitted a missing receipt id"],
                "the runtime rejected the missing receipt id",
                ["missing-receipt"],
                "receipt evidence remains required",
            )

    def test_governance_records_explain_session_scope_mismatches(self) -> None:
        self.server.mission_lock("s1", "t1", "goal", ["tests pass"])
        other_session_receipt = self.store.record_receipt(
            session_id="s2",
            task_id="t1",
            source="test",
            tool_name="Bash",
            command_text="pytest other session",
            exit_code=0,
            metadata={"stdout_sha256": "other-session"},
        )

        with self.assertRaisesRegex(ValueError, "belongs to session_id='s2'"):
            self.server.record_stuck_attempt(
                "s1",
                "t1",
                "strategy-a",
                "Tried a strategy with a receipt from the wrong session.",
                [other_session_receipt.receipt_id],
            )
        with self.assertRaisesRegex(ValueError, "belongs to session_id='s2'"):
            self.server.record_decision_record(
                "s1",
                "t1",
                "choose scoped evidence",
                "reject receipts from sibling sessions",
                ["accept sibling session receipts"],
                [other_session_receipt.receipt_id],
                "reversible",
                ["new scoped evidence appears"],
            )
        with self.assertRaisesRegex(ValueError, "belongs to session_id='s2'"):
            self.server.record_counterexample_check(
                "s1",
                "t1",
                "sibling session receipts could prove the wrong mission",
                ["submitted a sibling-session receipt"],
                "the runtime rejected the sibling-session receipt",
                [other_session_receipt.receipt_id],
                "session-scoped evidence remains required",
            )

    def test_governance_records_report_each_mixed_scope_issue(self) -> None:
        self.server.mission_lock("s1", "t1", "goal", ["tests pass"])
        other_session_receipt = self.store.record_receipt(
            session_id="s2",
            task_id="t1",
            source="test",
            tool_name="Bash",
            command_text="pytest other session",
            exit_code=0,
            metadata={"stdout_sha256": "other-session"},
        )
        other_task_receipt = self.store.record_receipt(
            session_id="s1",
            task_id="other-task",
            source="test",
            tool_name="Bash",
            command_text="pytest other task",
            exit_code=0,
            metadata={"stdout_sha256": "other-task"},
        )

        with self.assertRaises(ValueError) as ctx:
            self.server.record_counterexample_check(
                "s1",
                "t1",
                "mixed invalid receipts should not satisfy a counterexample check",
                ["submitted missing, sibling-session, and sibling-task receipts"],
                "the runtime reported every invalid receipt scope separately",
                [
                    other_session_receipt.receipt_id,
                    "missing-receipt",
                    other_task_receipt.receipt_id,
                ],
                "all receipt ids must be individually diagnosable",
            )

        message = str(ctx.exception)
        self.assertIn(
            f"receipt_id {other_session_receipt.receipt_id!r} belongs to session_id='s2'",
            message,
        )
        self.assertIn("receipt_id 'missing-receipt' was not found", message)
        self.assertIn(
            f"receipt_id {other_task_receipt.receipt_id!r} belongs to task_id='other-task'",
            message,
        )
        self.assertNotEqual(
            "All referenced receipt_ids must exist and belong to this mission scope.",
            message,
        )

    def test_governance_records_explain_task_scope_mismatches(self) -> None:
        self.server.mission_lock("s1", "t1", "goal", ["tests pass"])
        other_task_receipt = self.store.record_receipt(
            session_id="s1",
            task_id="other-task",
            source="test",
            tool_name="Bash",
            command_text="pytest other",
            exit_code=0,
            metadata={"stdout_sha256": "other"},
        )

        with self.assertRaisesRegex(ValueError, "belongs to task_id='other-task'"):
            self.server.record_stuck_attempt(
                "s1",
                "t1",
                "strategy-a",
                "Tried a strategy with a receipt from the wrong task.",
                [other_task_receipt.receipt_id],
            )
        with self.assertRaisesRegex(ValueError, "belongs to task_id='other-task'"):
            self.server.record_decision_record(
                "s1",
                "t1",
                "choose scoped evidence",
                "reject receipts from sibling tasks",
                ["accept sibling task receipts"],
                [other_task_receipt.receipt_id],
                "reversible",
                ["new scoped evidence appears"],
            )

        with self.assertRaisesRegex(ValueError, "belongs to task_id='other-task'"):
            self.server.record_counterexample_check(
                "s1",
                "t1",
                "sibling task receipts could prove the wrong mission",
                ["submitted a sibling-task receipt"],
                "the runtime rejected the sibling-task receipt",
                [other_task_receipt.receipt_id],
                "task-scoped evidence remains required",
            )

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
