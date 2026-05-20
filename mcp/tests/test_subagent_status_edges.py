from __future__ import annotations

import importlib
import json
import os
import tempfile
import unittest
from pathlib import Path


class SubagentStatusEdgeTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self._old_env = {
            key: os.environ.get(key)
            for key in ("ILH_DB_PATH", "ILH_SECRET_PATH", "ILH_HARNESS_SECRET")
        }
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
        for key, value in self._old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def lock_parent(self) -> None:
        self.server.mission_lock(
            "subagent-session",
            "parent-task",
            "delegate review work",
            ["tests pass"],
        )

    def start_child(self) -> dict:
        return json.loads(
            self.server.register_subagent_start(
                session_id="subagent-session",
                task_id="parent-task",
                subagent_type="code-reviewer",
                delegated_scope="review parser changes only",
                delegated_budget={"max_tool_calls": 5},
            )
        )

    def child_receipt(self, child_span_id: str):
        return self.store.record_receipt(
            session_id="subagent-session",
            task_id="parent-task",
            source="child-test",
            tool_name="Bash",
            command_text="python -m unittest mcp.tests.test_subagent_status_edges",
            exit_code=0,
            metadata={"child_span_id": child_span_id},
        )

    def record_handoff(self, child_span_id: str, receipt_id: str) -> None:
        self.server.record_subagent_handoff(
            session_id="subagent-session",
            task_id="parent-task",
            child_span_id=child_span_id,
            summary="Child returned evidence for bulk status handoff lookup coverage.",
            verified_claims=[{"claim": "targeted tests passed"}],
            receipt_ids=[receipt_id],
            risks=[],
            unverified_items=[],
        )

    def test_subagent_status_fetches_handoffs_in_bulk(self) -> None:
        self.lock_parent()
        children = [self.start_child() for _ in range(3)]
        for child in children:
            receipt = self.child_receipt(child["child_span_id"])
            self.record_handoff(child["child_span_id"], receipt.receipt_id)

        original = self.store.list_subagent_handoffs
        calls: list[str | None] = []

        def tracking_handoffs(session_id: str, task_id: str, child_span_id: str | None = None):
            calls.append(child_span_id)
            return original(session_id, task_id, child_span_id)

        self.store.list_subagent_handoffs = tracking_handoffs
        try:
            payload = json.loads(self.server.subagent_status("subagent-session", "parent-task"))
        finally:
            self.store.list_subagent_handoffs = original

        self.assertEqual(payload["summary"]["total"], 3)
        self.assertEqual(calls, [None])

    def test_subagent_status_exposes_receipt_sequence_boundaries(self) -> None:
        self.lock_parent()
        child = self.start_child()
        receipt = self.child_receipt(child["child_span_id"])
        self.record_handoff(child["child_span_id"], receipt.receipt_id)
        self.server.register_subagent_stop(
            session_id="subagent-session",
            task_id="parent-task",
            child_span_id=child["child_span_id"],
            status="completed",
            budget_consumed={"tool_calls": 1},
        )

        payload = json.loads(self.server.subagent_status("subagent-session", "parent-task"))
        span = payload["child_spans"][0]

        self.assertEqual(span["parent_receipt_seq"], 0)
        self.assertGreaterEqual(span["terminal_receipt_seq"], receipt.seq)
