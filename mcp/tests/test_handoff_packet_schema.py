from __future__ import annotations

import importlib
import json
import os
import tempfile
import unittest
from pathlib import Path


class HandoffPacketSchemaTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        os.environ["ILH_DB_PATH"] = str(Path(self.temp_dir.name) / "state.db")
        os.environ["ILH_SECRET_PATH"] = str(Path(self.temp_dir.name) / "secret.key")
        import sys

        mcp_root = str(Path(__file__).resolve().parents[1])
        if mcp_root not in sys.path:
            sys.path.insert(0, mcp_root)
        self.server = importlib.reload(importlib.import_module("server"))
        self.store = self.server.store

    def tearDown(self) -> None:
        self.temp_dir.cleanup()
        os.environ.pop("ILH_DB_PATH", None)
        os.environ.pop("ILH_SECRET_PATH", None)

    def make_bash_receipt(self, session_id: str, task_id: str, command: str):
        return self.store.record_receipt(
            session_id=session_id,
            task_id=task_id,
            source="test",
            tool_name="Bash",
            command_text=command,
            exit_code=0,
            metadata={"stdout_sha256": "abc"},
        )

    def test_budget_fields_live_only_in_budget_status(self) -> None:
        self.server.mission_lock(
            "s1",
            "handoff-schema-task",
            "goal",
            ["tests pass"],
            slice_budget=3,
            retry_budget=2,
            time_budget_minutes=15,
        )
        receipt = self.make_bash_receipt("s1", "handoff-schema-task", "pytest -q")
        self.server.turn_end_gate(
            session_id="s1",
            task_id="handoff-schema-task",
            stop_condition="slice_verified",
            work_summary="Verified one slice with concrete command output evidence.",
            receipt_ids=[receipt.receipt_id],
        )

        packet = json.loads(self.server.export_handoff_packet("s1", "handoff-schema-task"))

        self.assertEqual(packet["schema_version"], "1.0")
        self.assertEqual(
            list(packet),
            [
                "schema_version",
                "mission",
                "budget_status",
                "latest_receipts",
                "decision_records",
                "counterexample_checks",
                "latest_turn_gate",
                "latest_completion_gate",
                "latest_user_authorization",
                "adversarial_audit_status",
                "criterion_coverage",
                "known_risks",
                "unverified_items",
                "recommended_next_action",
            ],
        )
        self.assertEqual(
            list(packet["mission"]),
            [
                "session_id",
                "task_id",
                "goal",
                "status",
                "completion_criteria",
                "scope_boundary",
                "red_lines",
                "notes",
                "mission_start_receipt_seq",
            ],
        )
        for budget_key in ["slice_budget", "slice_count", "retry_budget"]:
            self.assertNotIn(budget_key, packet["mission"])
            self.assertIn(budget_key, packet["budget_status"])
        self.assertEqual(packet["budget_status"]["slice_budget"], 3)
        self.assertEqual(packet["budget_status"]["slice_count"], 1)
        self.assertEqual(packet["budget_status"]["retry_budget"], 2)


if __name__ == "__main__":
    unittest.main()
