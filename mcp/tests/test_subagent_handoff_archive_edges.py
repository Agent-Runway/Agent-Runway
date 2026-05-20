from __future__ import annotations

import importlib
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path


class SubagentHandoffArchiveEdgeTestCase(unittest.TestCase):
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

    def lock_parent(self) -> None:
        self.server.mission_lock("s1", "t1", "delegate work", ["tests pass"])

    def start_child(self) -> dict:
        return json.loads(
            self.server.register_subagent_start(
                session_id="s1",
                task_id="t1",
                subagent_type="code-reviewer",
                delegated_scope="review parser changes only",
                delegated_budget={"max_tool_calls": 5},
            )
        )

    def parent_receipt(self):
        return self.store.record_receipt(
            session_id="s1",
            task_id="t1",
            source="parent-test",
            tool_name="Bash",
            command_text="pytest -q",
            exit_code=0,
            metadata={"stdout_sha256": "parent"},
        )

    def approve_parent_slice(self, receipt_id: str) -> None:
        approved = self.server.turn_end_gate(
            session_id="s1",
            task_id="t1",
            stop_condition="slice_verified",
            work_summary="Verified the parent mission before testing completed-parent child boundaries.",
            receipt_ids=[receipt_id],
        )
        self.assertIn("APPROVED", approved)

    def child_receipt(self, child_span_id: str, **metadata: str):
        payload = {"child_span_id": child_span_id, **metadata}
        return self.store.record_receipt(
            session_id="s1",
            task_id="t1",
            source="child-test",
            tool_name="Bash",
            command_text="python -m unittest mcp.tests.test_subagent_supervision",
            exit_code=0,
            metadata=payload,
        )

    def test_store_foreign_key_blocks_handoff_for_unknown_child_span(self) -> None:
        self.lock_parent()

        with self.assertRaises(sqlite3.IntegrityError):
            self.store.record_subagent_handoff(
                child_span_id="child_missing",
                session_id="s1",
                task_id="t1",
                values={
                    "summary": "forged handoff on missing span",
                    "verified_claims": [{"claim": "fake"}],
                    "receipt_ids": ["r1"],
                    "risks": [],
                    "unverified_items": [],
                },
            )

    def test_completed_parent_mission_rejects_new_subagent_start(self) -> None:
        self.lock_parent()
        receipt = self.parent_receipt()
        self.approve_parent_slice(receipt.receipt_id)
        self.server.completion_gate(
            session_id="s1",
            task_id="t1",
            criterion_receipt_map=[{"criterion": "tests pass", "receipt_ids": [receipt.receipt_id]}],
            completion_summary="Completed the parent task before any new delegated work could begin.",
        )

        with self.assertRaisesRegex(ValueError, "No active mission"):
            self.server.register_subagent_start(
                session_id="s1",
                task_id="t1",
                subagent_type="code-reviewer",
                delegated_scope="review parser changes only",
                delegated_budget={"max_tool_calls": 5},
            )

    def test_record_subagent_handoff_rejects_nested_child_marker_receipt(self) -> None:
        self.lock_parent()
        child = self.start_child()
        receipt = self.child_receipt(
            child["child_span_id"], nested_child_span_id="nested-child-1"
        )

        with self.assertRaisesRegex(ValueError, "nested_child_span_id"):
            self.server.record_subagent_handoff(
                session_id="s1",
                task_id="t1",
                child_span_id=child["child_span_id"],
                summary="Receipt carries an extra nested child marker and should not be accepted as direct child evidence.",
                verified_claims=[{"claim": "targeted tests passed"}],
                receipt_ids=[receipt.receipt_id],
                risks=[],
                unverified_items=[],
            )


if __name__ == "__main__":
    unittest.main()
