from __future__ import annotations

import importlib
import os
import tempfile
import unittest
from pathlib import Path


ZERO_WIDTH = "\u200b"
FULLWIDTH_NEXT_WORK = "ｎｅｘｔ　ｗｏｒｋ"


class RuntimeBoundaryHiddenContinuationEdgesTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "state.db"
        os.environ["ILH_DB_PATH"] = str(self.db_path)
        os.environ["ILH_SECRET_PATH"] = str(Path(self.temp_dir.name) / "secret.key")

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

    def make_receipt(self, task_id: str, *, tool_name: str = "Bash"):
        return self.store.record_receipt(
            session_id="s1",
            task_id=task_id,
            source="runtime-boundary-test",
            tool_name=tool_name,
            command_text="pytest -q" if tool_name == "Bash" else "notes.md",
            exit_code=0,
            metadata={"stdout_sha256": "abc"},
        )

    def approve_verified_slice(self, task_id: str, receipt_id: str) -> None:
        result = self.server.turn_end_gate(
            session_id="s1",
            task_id=task_id,
            stop_condition="slice_verified",
            work_summary="Mapped visible evidence with direct runtime boundary checks.",
            receipt_ids=[receipt_id],
        )
        self.assertIn("APPROVED", result)

    def test_turn_end_gate_rejects_hidden_pending_work_in_known_risks(self) -> None:
        self.server.mission_lock("s1", "turn-known-risks", "goal", ["criterion"])
        receipt = self.make_receipt("turn-known-risks")

        rejected = self.server.turn_end_gate(
            session_id="s1",
            task_id="turn-known-risks",
            stop_condition="slice_verified",
            work_summary="Mapped visible evidence with direct runtime boundary checks.",
            receipt_ids=[receipt.receipt_id],
            known_risks=[f"remaining risk: next{ZERO_WIDTH}slice still needs review"],
        )

        self.assertIn("REJECTED", rejected)
        self.assertIn("pending local work", rejected)

    def test_turn_end_gate_rejects_hidden_pending_work_in_assumptions_remaining(self) -> None:
        self.server.mission_lock("s1", "turn-assumptions", "goal", ["criterion"])
        receipt = self.make_receipt("turn-assumptions")

        rejected = self.server.turn_end_gate(
            session_id="s1",
            task_id="turn-assumptions",
            stop_condition="slice_verified",
            work_summary="Mapped visible evidence with direct runtime boundary checks.",
            receipt_ids=[receipt.receipt_id],
            assumptions_remaining=[f"the next{ZERO_WIDTH} local step remains"],
        )

        self.assertIn("REJECTED", rejected)
        self.assertIn("pending local work", rejected)

    def test_turn_end_gate_rejects_hidden_pending_work_in_unverified_items(self) -> None:
        self.server.mission_lock("s1", "turn-unverified", "goal", ["criterion"])
        receipt = self.make_receipt("turn-unverified")

        rejected = self.server.turn_end_gate(
            session_id="s1",
            task_id="turn-unverified",
            stop_condition="slice_verified",
            work_summary="Mapped visible evidence with direct runtime boundary checks.",
            receipt_ids=[receipt.receipt_id],
            unverified_items=[f"remaining check: next{ZERO_WIDTH} step still open"],
        )

        self.assertIn("REJECTED", rejected)
        self.assertIn("pending local work", rejected)

    def test_turn_end_gate_rejects_hidden_chinese_pending_marker(self) -> None:
        self.server.mission_lock("s1", "turn-chinese", "goal", ["criterion"])
        receipt = self.make_receipt("turn-chinese")

        rejected = self.server.turn_end_gate(
            session_id="s1",
            task_id="turn-chinese",
            stop_condition="slice_verified",
            work_summary="Mapped visible evidence with direct runtime boundary checks.",
            receipt_ids=[receipt.receipt_id],
            known_risks=[f"下{ZERO_WIDTH}一步仍需复核"],
        )

        self.assertIn("REJECTED", rejected)
        self.assertIn("pending local work", rejected)

    def test_turn_end_gate_rejects_hidden_controls_in_non_pending_disclosure(self) -> None:
        self.server.mission_lock("s1", "turn-hidden-disclosure", "goal", ["criterion"])
        receipt = self.make_receipt("turn-hidden-disclosure")

        rejected = self.server.turn_end_gate(
            session_id="s1",
            task_id="turn-hidden-disclosure",
            stop_condition="user_information_required",
            work_summary="Mapped visible evidence before requesting the missing input.",
            receipt_ids=[receipt.receipt_id],
            known_risks=[f"reviewed{ZERO_WIDTH} disclosure"],
            reason_for_stopping="Need the user supplied external account identifier.",
        )

        self.assertIn("REJECTED", rejected)
        self.assertIn("known_risks[0] contains invisible/control", rejected)

    def test_turn_end_gate_rejects_hidden_controls_in_pending_actions(self) -> None:
        self.server.mission_lock("s1", "turn-hidden-pending-actions", "goal", ["criterion"])
        receipt = self.make_receipt("turn-hidden-pending-actions")

        rejected = self.server.turn_end_gate(
            session_id="s1",
            task_id="turn-hidden-pending-actions",
            stop_condition="approval_required",
            work_summary="Mapped visible evidence before requesting approval.",
            receipt_ids=[receipt.receipt_id],
            pending_actions_identified=[f"prepare{ZERO_WIDTH} deploy command"],
            reason_for_stopping="Need scoped approval before external deployment.",
        )

        self.assertIn("REJECTED", rejected)
        self.assertIn("pending_actions_identified[0] contains invisible/control", rejected)

    def test_completion_gate_rejects_fullwidth_pending_work_marker(self) -> None:
        self.server.mission_lock("s1", "completion-fullwidth", "goal", ["criterion"])
        receipt = self.make_receipt("completion-fullwidth")
        self.approve_verified_slice("completion-fullwidth", receipt.receipt_id)

        rejected = self.server.completion_gate(
            session_id="s1",
            task_id="completion-fullwidth",
            criterion_receipt_map=[
                {"criterion": "criterion", "receipt_ids": [receipt.receipt_id]}
            ],
            completion_summary="Mapped visible evidence and disclosed the mission boundary.",
            known_risks=[f"{FULLWIDTH_NEXT_WORK} remains open"],
        )

        self.assertIn("REJECTED", rejected)
        self.assertIn("pending local work", rejected)

    def test_completion_gate_rejects_hidden_pending_work_in_known_risks(self) -> None:
        self.server.mission_lock("s1", "completion-known-risks", "goal", ["criterion"])
        receipt = self.make_receipt("completion-known-risks")
        self.approve_verified_slice("completion-known-risks", receipt.receipt_id)

        rejected = self.server.completion_gate(
            session_id="s1",
            task_id="completion-known-risks",
            criterion_receipt_map=[
                {"criterion": "criterion", "receipt_ids": [receipt.receipt_id]}
            ],
            completion_summary="Mapped visible evidence and disclosed the mission boundary.",
            known_risks=[f"need to review next{ZERO_WIDTH} work after release"],
        )

        self.assertIn("REJECTED", rejected)
        self.assertIn("pending local work", rejected)

    def test_completion_gate_rejects_hidden_pending_work_in_unverified_items(self) -> None:
        self.server.mission_lock("s1", "completion-unverified", "goal", ["criterion"])
        receipt = self.make_receipt("completion-unverified")
        self.approve_verified_slice("completion-unverified", receipt.receipt_id)

        rejected = self.server.completion_gate(
            session_id="s1",
            task_id="completion-unverified",
            criterion_receipt_map=[
                {"criterion": "criterion", "receipt_ids": [receipt.receipt_id]}
            ],
            completion_summary="Mapped visible evidence and disclosed the mission boundary.",
            unverified_items=[f"remaining check: next{ZERO_WIDTH} step still open"],
        )

        self.assertIn("REJECTED", rejected)
        self.assertIn("pending local work", rejected)

    def test_completion_gate_rejects_hidden_controls_in_non_pending_disclosure(self) -> None:
        self.server.mission_lock("s1", "completion-hidden-disclosure", "goal", ["criterion"])
        receipt = self.make_receipt("completion-hidden-disclosure")
        self.approve_verified_slice("completion-hidden-disclosure", receipt.receipt_id)

        rejected = self.server.completion_gate(
            session_id="s1",
            task_id="completion-hidden-disclosure",
            criterion_receipt_map=[
                {"criterion": "criterion", "receipt_ids": [receipt.receipt_id]}
            ],
            completion_summary="Mapped visible evidence and disclosed the mission boundary.",
            known_risks=[f"reviewed{ZERO_WIDTH} disclosure"],
        )

        self.assertIn("REJECTED", rejected)
        self.assertIn("known_risks[0] contains invisible/control", rejected)

    def test_mission_lock_rejects_hidden_controls_in_scope_boundary(self) -> None:
        with self.assertRaisesRegex(ValueError, "scope_boundary contains invisible/control characters"):
            self.server.mission_lock(
                "s1",
                "mission-scope-boundary",
                "goal",
                ["criterion"],
                scope_boundary=f"only local work{ZERO_WIDTH}",
            )

    def test_mission_lock_rejects_hidden_controls_in_red_lines(self) -> None:
        with self.assertRaisesRegex(ValueError, "red_lines\\[0\\] contains invisible/control characters"):
            self.server.mission_lock(
                "s1",
                "mission-red-lines",
                "goal",
                ["criterion"],
                red_lines=[f"no push{ZERO_WIDTH}"],
            )


if __name__ == "__main__":
    unittest.main()
