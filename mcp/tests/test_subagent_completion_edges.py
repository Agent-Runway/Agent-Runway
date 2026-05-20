from __future__ import annotations

import importlib
import json
import os
import tempfile
import unittest
from pathlib import Path


class SubagentCompletionEdgeTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        os.environ["ILH_DB_PATH"] = str(Path(self.temp_dir.name) / "state.db")
        os.environ["ILH_SECRET_PATH"] = str(Path(self.temp_dir.name) / "secret.key")
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

    def record_parent_receipt(self):
        return self.store.record_receipt(
            session_id="subagent-session",
            task_id="parent-task",
            source="parent-test",
            tool_name="Bash",
            command_text="python -m unittest mcp.tests.test_subagent_completion_edges",
            exit_code=0,
            metadata={"stdout_sha256": "parent"},
        )

    def record_child_receipt(self, child_span_id: str):
        return self.store.record_receipt(
            session_id="subagent-session",
            task_id="parent-task",
            source="child-test",
            tool_name="Bash",
            command_text="python -m unittest mcp.tests.test_subagent_completion_edges",
            exit_code=0,
            metadata={"child_span_id": child_span_id},
        )

    def record_taskless_child_receipt(self, child_span_id: str):
        return self.store.record_receipt(
            session_id="subagent-session",
            task_id=None,
            source="child-test",
            tool_name="Bash",
            command_text="python -m unittest mcp.tests.test_subagent_completion_edges --child",
            exit_code=0,
            metadata={"child_span_id": child_span_id},
        )

    def approve_parent_turn(self, receipt_ids: list[str]) -> None:
        approved = self.server.turn_end_gate(
            session_id="subagent-session",
            task_id="parent-task",
            stop_condition="slice_verified",
            work_summary="Verified the parent slice with child or parent evidence before completion.",
            receipt_ids=receipt_ids,
        )
        self.assertIn("APPROVED", approved)

    def start_child_with_risk(self) -> tuple[str, str]:
        child = self.server.register_subagent_start(
            session_id="subagent-session",
            task_id="parent-task",
            subagent_type="code-reviewer",
            delegated_scope="review tests only",
            delegated_budget={"max_tool_calls": 5},
        )
        child_span_id = json.loads(child)["child_span_id"]
        receipt = self.record_child_receipt(child_span_id)
        self.record_child_handoff_with_risk(child_span_id, receipt.receipt_id)
        return child_span_id, receipt.receipt_id

    def record_child_handoff_with_risk(self, child_span_id: str, receipt_id: str) -> None:
        self.server.record_subagent_handoff(
            session_id="subagent-session",
            task_id="parent-task",
            child_span_id=child_span_id,
            summary="Child returned evidence with a risk that parent must disclose.",
            verified_claims=[{"claim": "targeted tests passed"}],
            receipt_ids=[receipt_id],
            risks=["child risk must surface"],
            unverified_items=[],
        )

    def stop_child(self, child_span_id: str) -> None:
        self.server.register_subagent_stop(
            session_id="subagent-session",
            task_id="parent-task",
            child_span_id=child_span_id,
            status="completed",
            budget_consumed={"tool_calls": 1},
        )

    def test_completion_gate_batches_subagent_state_reads(self) -> None:
        self.server.mission_lock("subagent-session", "parent-task", "delegate work", ["tests pass"])
        receipt = self.record_parent_receipt()
        self.approve_parent_turn([receipt.receipt_id])

        span_calls = 0
        handoff_calls: list[str | None] = []
        original_spans = self.store.list_subagent_spans
        original_handoffs = self.store.list_subagent_handoffs

        def tracking_spans(session_id: str, task_id: str):
            nonlocal span_calls
            span_calls += 1
            return original_spans(session_id, task_id)

        def tracking_handoffs(session_id: str, task_id: str, child_span_id: str | None = None):
            handoff_calls.append(child_span_id)
            return original_handoffs(session_id, task_id, child_span_id)

        self.store.list_subagent_spans = tracking_spans
        self.store.list_subagent_handoffs = tracking_handoffs
        try:
            approved = self.server.completion_gate(
                session_id="subagent-session",
                task_id="parent-task",
                criterion_receipt_map=[
                    {"criterion": "tests pass", "receipt_ids": [receipt.receipt_id]}
                ],
                completion_summary="Parent completed with direct parent execution evidence.",
            )
        finally:
            self.store.list_subagent_spans = original_spans
            self.store.list_subagent_handoffs = original_handoffs

        self.assertIn("APPROVED", approved)
        self.assertLessEqual(span_calls, 1)
        self.assertEqual(handoff_calls, [])

    def test_completion_gate_batches_child_handoffs_without_losing_disclosures(self) -> None:
        self.server.mission_lock("subagent-session", "parent-task", "delegate work", ["tests pass"])
        child_span_id, child_receipt_id = self.start_child_with_risk()
        self.stop_child(child_span_id)
        parent_receipt = self.record_parent_receipt()

        original_handoffs = self.store.list_subagent_handoffs
        handoff_calls: list[str | None] = []

        def tracking_handoffs(session_id: str, task_id: str, child_span_id: str | None = None):
            handoff_calls.append(child_span_id)
            return original_handoffs(session_id, task_id, child_span_id)

        self.store.list_subagent_handoffs = tracking_handoffs
        try:
            rejected = self.server.completion_gate(
                session_id="subagent-session",
                task_id="parent-task",
                criterion_receipt_map=[
                    {
                        "criterion": "tests pass",
                        "receipt_ids": [child_receipt_id, parent_receipt.receipt_id],
                    }
                ],
                completion_summary="Parent tried to complete without carrying the child risk.",
            )
        finally:
            self.store.list_subagent_handoffs = original_handoffs

        self.assertIn("REJECTED", rejected)
        self.assertIn("child risk must surface", rejected)
        self.assertEqual(handoff_calls, [None])

    def test_export_handoff_packet_preserves_child_disclosures_after_completion(self) -> None:
        self.server.mission_lock("subagent-session", "parent-task", "delegate work", ["tests pass"])
        child = self.server.register_subagent_start(
            session_id="subagent-session",
            task_id="parent-task",
            subagent_type="code-reviewer",
            delegated_scope="review tests only",
            delegated_budget={"max_tool_calls": 5},
        )
        child_span_id = json.loads(child)["child_span_id"]
        child_receipt = self.record_child_receipt(child_span_id)
        self.server.record_subagent_handoff(
            session_id="subagent-session",
            task_id="parent-task",
            child_span_id=child_span_id,
            summary="Child returned evidence with residual disclosures for parent rollup.",
            verified_claims=[{"claim": "targeted tests passed"}],
            receipt_ids=[child_receipt.receipt_id],
            risks=["child risk must surface"],
            unverified_items=["child follow-up remains"],
        )
        self.stop_child(child_span_id)
        parent_receipt = self.record_parent_receipt()
        approved_turn = self.server.turn_end_gate(
            session_id="subagent-session",
            task_id="parent-task",
            stop_condition="slice_verified",
            work_summary="Verified the parent slice with child and parent receipts plus rolled-up disclosures.",
            receipt_ids=[child_receipt.receipt_id, parent_receipt.receipt_id],
            known_risks=["child risk must surface"],
            unverified_items=["child follow-up remains"],
        )
        self.assertIn("APPROVED", approved_turn)

        approved_completion = self.server.completion_gate(
            session_id="subagent-session",
            task_id="parent-task",
            criterion_receipt_map=[
                {
                    "criterion": "tests pass",
                    "receipt_ids": [child_receipt.receipt_id, parent_receipt.receipt_id],
                }
            ],
            completion_summary="Parent completed with child evidence and carried forward residual disclosures.",
            known_risks=["child risk must surface"],
            unverified_items=["child follow-up remains"],
        )
        self.assertIn("APPROVED", approved_completion)

        payload = json.loads(
            self.server.export_handoff_packet("subagent-session", "parent-task")
        )

        self.assertIn("child risk must surface", payload["known_risks"])
        self.assertIn("child follow-up remains", payload["unverified_items"])
        self.assertTrue(payload["latest_completion_gate"]["approved"])
        self.assertIn("tests pass", json.dumps(payload["criterion_coverage"], ensure_ascii=False))

    def test_completion_gate_allows_taskless_child_receipt_through_handoff_readiness(self) -> None:
        self.server.mission_lock("subagent-session", "parent-task", "delegate work", ["tests pass"])
        child = self.server.register_subagent_start(
            session_id="subagent-session",
            task_id="parent-task",
            subagent_type="code-reviewer",
            delegated_scope="review tests only",
            delegated_budget={"max_tool_calls": 5},
        )
        child_span_id = json.loads(child)["child_span_id"]
        receipt = self.record_taskless_child_receipt(child_span_id)
        self.server.record_subagent_handoff(
            session_id="subagent-session",
            task_id="parent-task",
            child_span_id=child_span_id,
            summary="Child returned taskless host evidence with explicit child span provenance.",
            verified_claims=[{"claim": "targeted tests passed"}],
            receipt_ids=[receipt.receipt_id],
            risks=[],
            unverified_items=[],
        )
        self.stop_child(child_span_id)
        self.approve_parent_turn([receipt.receipt_id])

        approved = self.server.completion_gate(
            session_id="subagent-session",
            task_id="parent-task",
            criterion_receipt_map=[
                {"criterion": "tests pass", "receipt_ids": [receipt.receipt_id]}
            ],
            completion_summary="Parent completed using child evidence that passed handoff readiness.",
        )

        self.assertIn("APPROVED", approved)
        self.assertNotIn("load-bearing gate evidence", approved)

    def test_turn_end_gate_rejects_unknown_taskless_child_receipt(self) -> None:
        self.server.mission_lock("subagent-session", "parent-task", "delegate work", ["tests pass"])
        receipt = self.store.record_receipt(
            session_id="subagent-session",
            task_id=None,
            source="child-test",
            tool_name="Bash",
            command_text="python -m unittest mcp.tests.test_subagent_completion_edges --child",
            exit_code=0,
            metadata={"child_span_id": "fake-child"},
        )

        rejected = self.server.turn_end_gate(
            session_id="subagent-session",
            task_id="parent-task",
            stop_condition="slice_verified",
            work_summary="Tried to verify a slice using a taskless receipt with fake child provenance.",
            receipt_ids=[receipt.receipt_id],
        )

        self.assertIn("REJECTED", rejected)
        self.assertIn("unknown child_span_id", rejected)

    def test_turn_end_gate_allows_taskless_child_receipt_after_handoff_readiness(self) -> None:
        self.server.mission_lock("subagent-session", "parent-task", "delegate work", ["tests pass"])
        child = self.server.register_subagent_start(
            session_id="subagent-session",
            task_id="parent-task",
            subagent_type="code-reviewer",
            delegated_scope="review tests only",
            delegated_budget={"max_tool_calls": 5},
        )
        child_span_id = json.loads(child)["child_span_id"]
        receipt = self.record_taskless_child_receipt(child_span_id)
        self.server.record_subagent_handoff(
            session_id="subagent-session",
            task_id="parent-task",
            child_span_id=child_span_id,
            summary="Child returned taskless host evidence with explicit child span provenance.",
            verified_claims=[{"claim": "targeted tests passed"}],
            receipt_ids=[receipt.receipt_id],
            risks=[],
            unverified_items=[],
        )
        self.stop_child(child_span_id)

        approved = self.server.turn_end_gate(
            session_id="subagent-session",
            task_id="parent-task",
            stop_condition="slice_verified",
            work_summary="Verified the slice using child evidence that passed handoff readiness.",
            receipt_ids=[receipt.receipt_id],
        )

        self.assertIn("APPROVED", approved)
        self.assertNotIn("load-bearing gate evidence", approved)
