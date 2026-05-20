from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


MCP_ROOT = Path(__file__).resolve().parents[1]
if str(MCP_ROOT) not in sys.path:
    sys.path.insert(0, str(MCP_ROOT))


class SubagentReverificationEdgeTests(unittest.TestCase):
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

    def approve_verified_slice(self, receipt_ids: list[str]) -> None:
        approved = self.server.turn_end_gate(
            session_id="s1",
            task_id="parent",
            stop_condition="slice_verified",
            work_summary="Recorded parent-visible evidence before testing child receipt completion validation.",
            receipt_ids=receipt_ids,
        )
        self.assertIn("APPROVED", approved)

    def reject_verified_slice(self, receipt_ids: list[str]) -> str:
        rejected = self.server.turn_end_gate(
            session_id="s1",
            task_id="parent",
            stop_condition="slice_verified",
            work_summary="Attempted to verify parent-visible evidence with invalid child receipt metadata.",
            receipt_ids=receipt_ids,
        )
        self.assertIn("REJECTED", rejected)
        return rejected

    def test_child_reverification_reports_unknown_child_span(self) -> None:
        self.server.mission_lock("s1", "parent", "goal", ["tests pass"])
        receipt = self.store.record_receipt(
            session_id="s1",
            task_id="parent",
            source="test",
            tool_name="Bash",
            command_text="pytest child-suite",
            exit_code=0,
            metadata={"child_span_id": "child_missing"},
        )

        violations = self.server._child_reverification_violations(
            [receipt], "s1", "parent", "tests pass"
        )

        self.assertEqual(1, len(violations))
        self.assertIn("unknown child_span_id", violations[0])
        self.assertIn("tests pass", violations[0])
        self.assertIn("child_missing", violations[0])

    def test_completion_gate_reports_unknown_child_span_once(self) -> None:
        self.server.mission_lock("s1", "parent", "goal", ["tests pass"])
        receipt = self.store.record_receipt(
            session_id="s1",
            task_id="parent",
            source="test",
            tool_name="Bash",
            command_text="pytest child-suite",
            exit_code=0,
            metadata={"child_span_id": "child_missing"},
        )
        rejected = self.reject_verified_slice([receipt.receipt_id])

        rejection_items = [
            line for line in rejected.splitlines() if line.startswith("- ")
        ]
        self.assertEqual(1, len(rejection_items))
        self.assertIn("unknown child_span_id", rejection_items[0])
        self.assertIn("child_missing", rejection_items[0])
        self.assertNotIn("criterion 'tests pass' child receipt", rejected)
        self.assertNotIn("parent re-verification", rejected)

    def test_completion_gate_filters_unknown_child_before_known_child_reverify(self) -> None:
        self.server.mission_lock("s1", "parent", "goal", ["tests pass"])
        child = json.loads(
            self.server.register_subagent_start(
                session_id="s1",
                task_id="parent",
                subagent_type="reviewer",
                delegated_scope="review only",
                delegated_budget={},
                host="test",
                host_child_id="child-1",
                workspace_kind="local_sandbox",
            )
        )
        unknown_receipt = self.store.record_receipt(
            session_id="s1",
            task_id="parent",
            source="test",
            tool_name="Bash",
            command_text="pytest forged-child-suite",
            exit_code=0,
            metadata={"child_span_id": "child_missing"},
        )
        sandbox_receipt = self.store.record_receipt(
            session_id="s1",
            task_id="parent",
            source="test",
            tool_name="Bash",
            command_text="pytest sandbox-child-suite",
            exit_code=0,
            metadata={"child_span_id": child["child_span_id"]},
        )
        self.server.record_subagent_handoff(
            session_id="s1",
            task_id="parent",
            child_span_id=child["child_span_id"],
            summary="Child provided sandbox evidence that still needs parent verification.",
            verified_claims=[{"claim": "child tests passed"}],
            receipt_ids=[sandbox_receipt.receipt_id],
        )
        self.server.register_subagent_stop(
            session_id="s1",
            task_id="parent",
            child_span_id=child["child_span_id"],
            status="completed",
        )

        rejected = self.reject_verified_slice(
            [unknown_receipt.receipt_id, sandbox_receipt.receipt_id]
        )

        rejection_items = [
            line for line in rejected.splitlines() if line.startswith("- ")
        ]
        self.assertEqual(1, len(rejection_items))
        self.assertEqual(
            1, sum("unknown child_span_id" in item for item in rejection_items)
        )
        self.assertIn("child_missing", rejected)
        self.assertNotIn(
            f"criterion 'tests pass' child receipt {unknown_receipt.receipt_id!r}",
            rejected,
        )
        self.assertNotIn("parent re-verification", rejected)
        self.assertNotIn(child["child_span_id"], rejected)

    def test_completion_gate_keeps_known_sandbox_child_reverify_violation(self) -> None:
        self.server.mission_lock("s1", "parent", "goal", ["tests pass"])
        child = json.loads(
            self.server.register_subagent_start(
                session_id="s1",
                task_id="parent",
                subagent_type="reviewer",
                delegated_scope="review only",
                delegated_budget={},
                host="test",
                host_child_id="child-1",
                workspace_kind="local_sandbox",
            )
        )
        receipt = self.store.record_receipt(
            session_id="s1",
            task_id="parent",
            source="test",
            tool_name="Bash",
            command_text="pytest child-suite",
            exit_code=0,
            metadata={"child_span_id": child["child_span_id"]},
        )
        self.server.record_subagent_handoff(
            session_id="s1",
            task_id="parent",
            child_span_id=child["child_span_id"],
            summary="Child provided sandbox evidence that still needs parent verification.",
            verified_claims=[{"claim": "child tests passed"}],
            receipt_ids=[receipt.receipt_id],
        )
        self.server.register_subagent_stop(
            session_id="s1",
            task_id="parent",
            child_span_id=child["child_span_id"],
            status="completed",
        )
        self.approve_verified_slice([receipt.receipt_id])

        rejected = self.server.completion_gate(
            session_id="s1",
            task_id="parent",
            completion_summary="Parent tried to use sandbox evidence without local reverification.",
            criterion_receipt_map=[
                {"criterion": "tests pass", "receipt_ids": [receipt.receipt_id]}
            ],
        )

        self.assertIn("REJECTED", rejected)
        self.assertIn("parent re-verification", rejected)
        self.assertIn(child["child_span_id"], rejected)
        self.assertNotIn("unknown child_span_id", rejected)


if __name__ == "__main__":
    unittest.main()
