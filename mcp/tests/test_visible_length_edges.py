from __future__ import annotations

import importlib
import json
import os
import tempfile
import unittest
from pathlib import Path


INVISIBLE_PADDING = "\x00\u200b\u034f\ufe0f" * 10
COMBINING_MARK_PADDING = "\u0301" * 30


class VisibleLengthEdgesTestCase(unittest.TestCase):
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

    def make_receipt(
        self,
        task_id: str,
        *,
        tool_name: str = "Read",
        metadata: dict[str, object] | None = None,
    ):
        command_text = "pytest -q" if tool_name == "Bash" else "notes.md"
        return self.store.record_receipt(
            session_id="s1",
            task_id=task_id,
            source="visible-length-test",
            tool_name=tool_name,
            command_text=command_text,
            exit_code=0,
            metadata=metadata or {},
        )

    def approve_verified_slice(self, task_id: str, receipt_id: str) -> None:
        approved = self.server.turn_end_gate(
            session_id="s1",
            task_id=task_id,
            stop_condition="slice_verified",
            work_summary="Mapped visible substantive evidence before completion.",
            receipt_ids=[receipt_id],
        )
        self.assertIn("APPROVED", approved)

    def assert_short_completion_rejected(self, task_id: str, padding: str) -> None:
        self.server.mission_lock("s1", task_id, "goal", ["criterion"])
        receipt = self.make_receipt(task_id)

        with self.assertRaisesRegex(ValueError, "completion_summary is too short"):
            self.server.completion_gate(
                session_id="s1",
                task_id=task_id,
                criterion_receipt_map=[
                    {"criterion": "criterion", "receipt_ids": [receipt.receipt_id]}
                ],
                completion_summary="x" + padding,
            )

    def test_completion_gate_rejects_invisible_padded_short_summary(self) -> None:
        self.assert_short_completion_rejected("invisible-completion", INVISIBLE_PADDING)

    def test_completion_gate_rejects_combining_mark_padded_short_summary(self) -> None:
        self.assert_short_completion_rejected("combining-completion", COMBINING_MARK_PADDING)

    def test_completion_gate_rejects_invisible_control_inside_long_summary(self) -> None:
        self.server.mission_lock("s1", "hidden-control-completion", "goal", ["criterion"])
        receipt = self.make_receipt("hidden-control-completion")
        self.approve_verified_slice("hidden-control-completion", receipt.receipt_id)

        rejected = self.server.completion_gate(
            session_id="s1",
            task_id="hidden-control-completion",
            criterion_receipt_map=[
                {"criterion": "criterion", "receipt_ids": [receipt.receipt_id]}
            ],
            completion_summary="Mapped visible evidence\x00 while hiding a control character in the summary.",
        )

        self.assertIn("REJECTED", rejected)
        self.assertIn("invisible/control", rejected)

    def assert_short_work_summary_rejected(self, task_id: str, padding: str) -> None:
        self.server.mission_lock("s1", task_id, "goal", ["criterion"])
        receipt = self.make_receipt(task_id, tool_name="Bash")

        with self.assertRaisesRegex(ValueError, "work_summary is too short"):
            self.server.turn_end_gate(
                session_id="s1",
                task_id=task_id,
                stop_condition="slice_verified",
                work_summary="x" + padding,
                receipt_ids=[receipt.receipt_id],
            )

    def test_turn_end_gate_rejects_invisible_padded_short_work_summary(self) -> None:
        self.assert_short_work_summary_rejected("invisible-work", INVISIBLE_PADDING)

    def test_turn_end_gate_rejects_combining_mark_padded_short_work_summary(self) -> None:
        self.assert_short_work_summary_rejected("combining-work", COMBINING_MARK_PADDING)

    def test_turn_end_gate_rejects_invisible_control_inside_long_summary(self) -> None:
        self.server.mission_lock("s1", "hidden-control-work", "goal", ["criterion"])
        receipt = self.make_receipt("hidden-control-work", tool_name="Bash")

        rejected = self.server.turn_end_gate(
            session_id="s1",
            task_id="hidden-control-work",
            stop_condition="slice_verified",
            work_summary="Mapped visible evidence\x00 while hiding a control character in the summary.",
            receipt_ids=[receipt.receipt_id],
        )

        self.assertIn("REJECTED", rejected)
        self.assertIn("invisible/control", rejected)

    def assert_short_stuck_reason_rejected(self, task_id: str, padding: str) -> None:
        self.server.mission_lock("s1", task_id, "goal", ["criterion"], retry_budget=1)
        receipt = self.make_receipt(task_id, tool_name="Bash")
        self.server.record_stuck_attempt(
            "s1", task_id, "strategy-a", "first failed strategy", [receipt.receipt_id]
        )

        rejected = self.server.turn_end_gate(
            session_id="s1",
            task_id=task_id,
            stop_condition="stuck_escalation",
            work_summary="Recorded one failed strategy with direct command output.",
            receipt_ids=[receipt.receipt_id],
            reason_for_stopping="x" + padding,
        )

        self.assertIn("REJECTED", rejected)
        self.assertIn("precise explanation", rejected)

    def test_stuck_escalation_rejects_invisible_padded_short_reason(self) -> None:
        self.assert_short_stuck_reason_rejected("invisible-reason", INVISIBLE_PADDING)

    def test_stuck_escalation_rejects_combining_mark_padded_short_reason(self) -> None:
        self.assert_short_stuck_reason_rejected("combining-reason", COMBINING_MARK_PADDING)

    def test_soft_stop_rejects_invisible_only_reason(self) -> None:
        self.server.mission_lock("s1", "invisible-soft-stop", "goal", ["criterion"])
        receipt = self.make_receipt("invisible-soft-stop", tool_name="Bash")

        rejected = self.server.turn_end_gate(
            session_id="s1",
            task_id="invisible-soft-stop",
            stop_condition="user_information_required",
            work_summary="Recorded current evidence before asking for missing information.",
            receipt_ids=[receipt.receipt_id],
            reason_for_stopping=INVISIBLE_PADDING,
        )

        self.assertIn("REJECTED", rejected)
        self.assertIn("precise reason_for_stopping", rejected)

    def assert_short_handoff_summary_rejected(self, task_id: str, padding: str) -> None:
        self.server.mission_lock("s1", task_id, "goal", ["criterion"])
        child = json.loads(
            self.server.register_subagent_start(
                "s1", task_id, "explore", "inspect parser behavior", {}
            )
        )
        receipt = self.make_receipt(
            task_id, tool_name="Bash", metadata={"child_span_id": child["child_span_id"]}
        )

        with self.assertRaisesRegex(ValueError, "summary is too short"):
            self.server.record_subagent_handoff(
                "s1",
                task_id,
                child["child_span_id"],
                "x" + padding,
                [{"claim": "ran pytest", "receipt_ids": [receipt.receipt_id]}],
                [receipt.receipt_id],
            )

    def test_subagent_handoff_rejects_invisible_padded_short_summary(self) -> None:
        self.assert_short_handoff_summary_rejected("invisible-child", INVISIBLE_PADDING)

    def test_subagent_handoff_rejects_combining_mark_padded_short_summary(self) -> None:
        self.assert_short_handoff_summary_rejected("combining-child", COMBINING_MARK_PADDING)

    def test_visible_accented_text_still_counts_as_substantive_text(self) -> None:
        self.server.mission_lock("s1", "accented-completion", "goal", ["criterion"])
        receipt = self.make_receipt("accented-completion")
        self.approve_verified_slice("accented-completion", receipt.receipt_id)

        approved = self.server.completion_gate(
            session_id="s1",
            task_id="accented-completion",
            criterion_receipt_map=[
                {"criterion": "criterion", "receipt_ids": [receipt.receipt_id]}
            ],
            completion_summary="Résumé verification notes describe concrete reviewed evidence.",
        )

        self.assertIn("APPROVED", approved)


if __name__ == "__main__":
    unittest.main()
