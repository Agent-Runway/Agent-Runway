from __future__ import annotations

import importlib
import os
import tempfile
import unittest
from pathlib import Path


class RuntimeExtremeInputEdgeTestCase(unittest.TestCase):
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

    def make_bash_receipt(self, session_id: str, task_id: str, command: str = "pytest -q"):
        return self.store.record_receipt(
            session_id=session_id,
            task_id=task_id,
            source="test",
            tool_name="Bash",
            command_text=command,
            exit_code=0,
            metadata={"stdout_sha256": "abc"},
        )

    def approve_verified_slice(self, task_id: str, receipt_id: str) -> None:
        approved = self.server.turn_end_gate(
            session_id="s1",
            task_id=task_id,
            stop_condition="slice_verified",
            work_summary="Recorded the current command receipt before preserving residual disclosures.",
            receipt_ids=[receipt_id],
            known_risks=["risk-preflight"],
            unverified_items=["item-preflight"],
        )
        self.assertIn("APPROVED", approved)

    def test_mission_lock_accepts_zero_width_session_and_task_ids(self) -> None:
        sid = "s\u200b1"
        tid = "t\u200b1"

        result = self.server.mission_lock(sid, tid, "goal", ["criterion"])

        self.assertIn("MISSION LOCKED", result)
        status = self.server.mission_status(sid, tid)
        self.assertIn(f"task_id: {tid}", status)

    def test_mission_lock_accepts_control_characters_in_goal_text(self) -> None:
        result = self.server.mission_lock(
            "s1", "control-goal", "goal with tab\tand newline\ncontent", ["criterion"]
        )

        self.assertIn("MISSION LOCKED", result)

    def test_large_completion_criteria_list_is_supported(self) -> None:
        criteria = [f"criterion-{index}" for index in range(100)]

        result = self.server.mission_lock("s1", "wide-criteria", "goal", criteria)

        self.assertIn("MISSION LOCKED", result)
        status = self.server.mission_status("s1", "wide-criteria")
        self.assertIn("criterion-99", status)

    def test_large_known_risks_and_unverified_items_are_preserved(self) -> None:
        self.server.mission_lock("s1", "residuals", "goal", ["criterion"])
        receipt = self.make_bash_receipt("s1", "residuals")
        known_risks = [f"risk-{index}" for index in range(50)]
        unverified_items = [f"item-{index}" for index in range(50)]
        self.approve_verified_slice("residuals", receipt.receipt_id)

        result = self.server.completion_gate(
            "s1",
            "residuals",
            "Completed the task with verified evidence and detailed residual disclosures.",
            [{"criterion": "criterion", "receipt_ids": [receipt.receipt_id]}],
            unverified_items=unverified_items,
            known_risks=known_risks,
        )

        self.assertIn("APPROVED", result)
        handoff = self.server.export_handoff_packet("s1", "residuals")
        self.assertIn("risk-49", handoff)
        self.assertIn("item-49", handoff)

    def test_list_recent_receipts_negative_limit_clamps_to_one(self) -> None:
        self.server.mission_lock("s1", "negative-limit", "goal", ["criterion"])
        newest = None
        for index in range(3):
            newest = self.make_bash_receipt("s1", "negative-limit", f"cmd-{index}")

        payload = self.server.list_recent_receipts("s1", "negative-limit", -5)

        self.assertIsNotNone(newest)
        self.assertIn(newest.receipt_id, payload)
        self.assertNotIn("cmd-1", payload)

    def test_long_user_statement_excerpt_is_preserved(self) -> None:
        self.server.mission_lock("s1", "long-auth", "goal", ["criterion"])
        excerpt = "approved " * 200

        recorded = self.server.record_user_authorization(
            session_id="s1",
            task_id="long-auth",
            action_scope="write files",
            approval_scope="approve write",
            user_statement_excerpt=excerpt,
        )

        self.assertIn("USER AUTHORIZATION RECORDED", recorded)
        payload = self.server.authorization_status("s1", "long-auth")
        self.assertIn("approved approved", payload)

    def test_subagent_start_accepts_large_budget_dict(self) -> None:
        self.server.mission_lock("s1", "subagent-budget", "goal", ["criterion"])
        budget = {f"key_{index}": index for index in range(100)}

        payload = self.server.register_subagent_start(
            "s1", "subagent-budget", "reviewer", "check all files", budget
        )

        self.assertIn('"subagent_type": "reviewer"', payload)
        self.assertIn('"key_99": 99', payload)


if __name__ == "__main__":
    unittest.main()
