from __future__ import annotations

import importlib
import json
import os
import tempfile
import unittest
from pathlib import Path


class SubagentHandoffEdgeTestCase(unittest.TestCase):
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

    def lock_parent(self) -> None:
        self.server.mission_lock(
            "handoff-edge-session",
            "parent-task",
            "delegate review work",
            ["tests pass"],
        )

    def start_child(self) -> str:
        payload = self.server.register_subagent_start(
            session_id="handoff-edge-session",
            task_id="parent-task",
            subagent_type="code-reviewer",
            delegated_scope="review parser changes only",
            delegated_budget={"max_tool_calls": 5},
        )
        return json.loads(payload)["child_span_id"]

    def child_receipt(self, child_span_id: str):
        return self.store.record_receipt(
            session_id="handoff-edge-session",
            task_id="parent-task",
            source="child-test",
            tool_name="Bash",
            command_text="python -m unittest mcp.tests.test_subagent_handoff_edges",
            exit_code=0,
            metadata={"child_span_id": child_span_id},
        )

    def taskless_child_receipt(self, child_span_id: str):
        return self.store.record_receipt(
            session_id="handoff-edge-session",
            task_id=None,
            source="child-test",
            tool_name="Bash",
            command_text="python -m unittest mcp.tests.test_subagent_handoff_edges --taskless-child",
            exit_code=0,
            metadata={"child_span_id": child_span_id},
        )

    def test_record_subagent_handoff_rejects_empty_verified_claims(self) -> None:
        self.lock_parent()
        child_span_id = self.start_child()
        receipt = self.child_receipt(child_span_id)

        with self.assertRaisesRegex(ValueError, "verified_claims"):
            self.server.record_subagent_handoff(
                session_id="handoff-edge-session",
                task_id="parent-task",
                child_span_id=child_span_id,
                summary="Child supplied a receipt but did not map it to any verified claim.",
                verified_claims=[],
                receipt_ids=[receipt.receipt_id],
                risks=[],
                unverified_items=[],
            )

    def test_record_subagent_handoff_rejects_blank_verified_claim_text(self) -> None:
        self.lock_parent()
        child_span_id = self.start_child()
        receipt = self.child_receipt(child_span_id)

        with self.assertRaisesRegex(ValueError, "verified_claims"):
            self.server.record_subagent_handoff(
                session_id="handoff-edge-session",
                task_id="parent-task",
                child_span_id=child_span_id,
                summary="Child supplied a receipt but only included an empty verified claim.",
                verified_claims=[{"claim": "   "}],
                receipt_ids=[receipt.receipt_id],
                risks=[],
                unverified_items=[],
            )

    def test_record_subagent_handoff_accepts_taskless_child_receipt_with_single_active_mission(self) -> None:
        self.lock_parent()
        child_span_id = self.start_child()
        receipt = self.taskless_child_receipt(child_span_id)

        handoff = json.loads(
            self.server.record_subagent_handoff(
                session_id="handoff-edge-session",
                task_id="parent-task",
                child_span_id=child_span_id,
                summary="Child supplied taskless host evidence while only one mission was active.",
                verified_claims=[{"claim": "targeted tests passed"}],
                receipt_ids=[receipt.receipt_id],
                risks=[],
                unverified_items=[],
            )
        )

        self.assertEqual(handoff["receipt_ids"], [receipt.receipt_id])

    def test_record_subagent_handoff_accepts_task_scoped_child_receipt_with_multiple_active_missions(self) -> None:
        self.lock_parent()
        self.server.mission_lock(
            "handoff-edge-session",
            "sibling-task",
            "parallel sibling work",
            ["sibling criterion"],
        )
        child_span_id = self.start_child()
        receipt = self.child_receipt(child_span_id)

        handoff = json.loads(
            self.server.record_subagent_handoff(
                session_id="handoff-edge-session",
                task_id="parent-task",
                child_span_id=child_span_id,
                summary="Child supplied task-scoped evidence while a sibling mission was active.",
                verified_claims=[{"claim": "targeted tests passed"}],
                receipt_ids=[receipt.receipt_id],
                risks=[],
                unverified_items=[],
            )
        )

        self.assertEqual(handoff["receipt_ids"], [receipt.receipt_id])

    def test_record_subagent_handoff_rejects_taskless_child_receipt_with_multiple_active_missions(self) -> None:
        self.lock_parent()
        self.server.mission_lock(
            "handoff-edge-session",
            "sibling-task",
            "parallel sibling work",
            ["sibling criterion"],
        )
        child_span_id = self.start_child()
        receipt = self.taskless_child_receipt(child_span_id)

        with self.assertRaisesRegex(ValueError, "taskless receipt.*multiple active missions"):
            self.server.record_subagent_handoff(
                session_id="handoff-edge-session",
                task_id="parent-task",
                child_span_id=child_span_id,
                summary="Child tried to use taskless host evidence while a sibling mission was active.",
                verified_claims=[{"claim": "targeted tests passed"}],
                receipt_ids=[receipt.receipt_id],
                risks=[],
                unverified_items=[],
            )


if __name__ == "__main__":
    unittest.main()
