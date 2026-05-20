from __future__ import annotations

import importlib
import os
import tempfile
import unittest
from pathlib import Path


class TurnEndSoftStopEdgesTestCase(unittest.TestCase):
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

    def make_receipt(self, task_id: str, command: str):
        return self.store.record_receipt(
            session_id="s1",
            task_id=task_id,
            source="test",
            tool_name="Bash",
            command_text=command,
            exit_code=0,
            metadata={"stdout_sha256": "abc"},
        )

    def make_read_receipt(self, task_id: str, path: str):
        return self.store.record_receipt(
            session_id="s1",
            task_id=task_id,
            source="test",
            tool_name="Read",
            command_text=path,
            exit_code=0,
            metadata={},
        )

    def test_alternating_soft_stops_share_one_loop_counter(self) -> None:
        self.server.mission_lock("s1", "soft-stop-loop", "goal", ["criterion"])
        for stop_condition, command in [
            ("user_information_required", "prepare.py"),
            ("approval_required", "inspect.py"),
        ]:
            receipt = self.make_receipt("soft-stop-loop", command)
            approved = self.server.turn_end_gate(
                session_id="s1",
                task_id="soft-stop-loop",
                stop_condition=stop_condition,
                work_summary="Collected direct evidence before a temporary soft stop boundary.",
                receipt_ids=[receipt.receipt_id],
                reason_for_stopping="Need external input before the next bounded action.",
            )
            self.assertIn("APPROVED", approved)

        third_receipt = self.make_receipt("soft-stop-loop", "ask-again.py")
        rejected = self.server.turn_end_gate(
            session_id="s1",
            task_id="soft-stop-loop",
            stop_condition="user_information_required",
            work_summary="Tried to pause again after two soft stops without verified progress.",
            receipt_ids=[third_receipt.receipt_id],
            reason_for_stopping="Need external input before the next bounded action.",
        )
        self.assertIn("REJECTED", rejected)
        self.assertIn("too many times without real progress", rejected)

    def test_soft_stop_counter_resets_after_verified_progress(self) -> None:
        self.server.mission_lock("s1", "soft-stop-reset", "goal", ["criterion"])
        for stop_condition, command in [
            ("user_information_required", "prepare.py"),
            ("approval_required", "inspect.py"),
        ]:
            receipt = self.make_receipt("soft-stop-reset", command)
            approved = self.server.turn_end_gate(
                session_id="s1",
                task_id="soft-stop-reset",
                stop_condition=stop_condition,
                work_summary="Collected direct evidence before a temporary soft stop boundary.",
                receipt_ids=[receipt.receipt_id],
                reason_for_stopping="Need external input before the next bounded action.",
            )
            self.assertIn("APPROVED", approved)

        progress_receipt = self.make_receipt("soft-stop-reset", "pytest -q")
        progress = self.server.turn_end_gate(
            session_id="s1",
            task_id="soft-stop-reset",
            stop_condition="slice_verified",
            work_summary="Ran a real verification command and completed a bounded slice after soft stops.",
            receipt_ids=[progress_receipt.receipt_id],
        )
        self.assertIn("APPROVED", progress)

        later_receipt = self.make_receipt("soft-stop-reset", "prepare-release.py")
        approved_after_progress = self.server.turn_end_gate(
            session_id="s1",
            task_id="soft-stop-reset",
            stop_condition="approval_required",
            work_summary="Prepared the next external action after verified progress and need user approval.",
            receipt_ids=[later_receipt.receipt_id],
            reason_for_stopping="Need approval before the next externally visible action.",
        )
        self.assertIn("APPROVED", approved_after_progress)

    def test_read_only_verified_slice_does_not_reset_soft_stop_counter(self) -> None:
        self.server.mission_lock("s1", "soft-stop-read", "goal", ["criterion"])
        for stop_condition, command in [
            ("user_information_required", "prepare.py"),
            ("approval_required", "inspect.py"),
        ]:
            receipt = self.make_receipt("soft-stop-read", command)
            approved = self.server.turn_end_gate(
                session_id="s1",
                task_id="soft-stop-read",
                stop_condition=stop_condition,
                work_summary="Collected direct evidence before a temporary soft stop boundary.",
                receipt_ids=[receipt.receipt_id],
                reason_for_stopping="Need external input before the next bounded action.",
            )
            self.assertIn("APPROVED", approved)

        read_receipt = self.make_read_receipt("soft-stop-read", "notes.md")
        read_slice = self.server.turn_end_gate(
            session_id="s1",
            task_id="soft-stop-read",
            stop_condition="slice_verified",
            work_summary="Read notes and claimed a slice without execution or mutation progress.",
            receipt_ids=[read_receipt.receipt_id],
        )
        self.assertIn("APPROVED", read_slice)

        later_receipt = self.make_receipt("soft-stop-read", "prepare-release.py")
        rejected = self.server.turn_end_gate(
            session_id="s1",
            task_id="soft-stop-read",
            stop_condition="approval_required",
            work_summary="Tried to pause again after only a read-only slice occurred.",
            receipt_ids=[later_receipt.receipt_id],
            reason_for_stopping="Need approval before the next externally visible action.",
        )
        self.assertIn("REJECTED", rejected)
        self.assertIn("too many times without real progress", rejected)

    def test_repeated_interpretation_deadlock_requires_progress_or_escalation(self) -> None:
        self.server.mission_lock("s1", "deadlock-loop", "goal", ["criterion"])
        reasons = [
            "Parser can mean the CLI parser or the report parser, and the local evidence cannot distinguish which target the user intended.",
            "Requirement can mean preserving old behavior or enforcing the new contract, and available files support both interpretations.",
        ]
        for index, reason in enumerate(reasons):
            receipt = self.make_receipt("deadlock-loop", f"inspect-{index}.py")
            approved = self.server.turn_end_gate(
                session_id="s1",
                task_id="deadlock-loop",
                stop_condition="interpretation_deadlock",
                work_summary="Collected concrete evidence before reporting an unresolved interpretation conflict.",
                receipt_ids=[receipt.receipt_id],
                reason_for_stopping=reason,
            )
            self.assertIn("APPROVED", approved)

        third_receipt = self.make_receipt("deadlock-loop", "inspect-again.py")
        rejected = self.server.turn_end_gate(
            session_id="s1",
            task_id="deadlock-loop",
            stop_condition="interpretation_deadlock",
            work_summary="Tried to report another interpretation deadlock without verified progress.",
            receipt_ids=[third_receipt.receipt_id],
            reason_for_stopping="Module name can mean either the public API module or the internal runtime module, and both readings still fit the files.",
        )

        self.assertIn("REJECTED", rejected)
        self.assertIn("too many times without real progress", rejected)

    def test_interpretation_deadlock_counter_resets_after_verified_progress(self) -> None:
        self.server.mission_lock("s1", "deadlock-reset", "goal", ["criterion"])
        for index in range(2):
            receipt = self.make_receipt("deadlock-reset", f"inspect-{index}.py")
            approved = self.server.turn_end_gate(
                session_id="s1",
                task_id="deadlock-reset",
                stop_condition="interpretation_deadlock",
                work_summary="Collected concrete evidence before reporting an unresolved interpretation conflict.",
                receipt_ids=[receipt.receipt_id],
                reason_for_stopping="Parser can mean the CLI parser or report parser, and local evidence cannot distinguish which target the user intended.",
            )
            self.assertIn("APPROVED", approved)

        progress_receipt = self.make_receipt("deadlock-reset", "pytest -q")
        progress = self.server.turn_end_gate(
            session_id="s1",
            task_id="deadlock-reset",
            stop_condition="slice_verified",
            work_summary="Ran a real verification command and completed a bounded slice after deadlock reports.",
            receipt_ids=[progress_receipt.receipt_id],
        )
        self.assertIn("APPROVED", progress)

        later_receipt = self.make_receipt("deadlock-reset", "inspect-after-progress.py")
        approved_after_progress = self.server.turn_end_gate(
            session_id="s1",
            task_id="deadlock-reset",
            stop_condition="interpretation_deadlock",
            work_summary="Collected new evidence after verified progress and found a remaining interpretation conflict.",
            receipt_ids=[later_receipt.receipt_id],
            reason_for_stopping="Release line can mean Gitea dev line or GitHub public line, and both meanings appear in local notes.",
        )
        self.assertIn("APPROVED", approved_after_progress)

    def test_read_only_verified_slice_does_not_reset_interpretation_deadlock_counter(self) -> None:
        self.server.mission_lock("s1", "deadlock-read", "goal", ["criterion"])
        for index in range(2):
            receipt = self.make_receipt("deadlock-read", f"inspect-{index}.py")
            approved = self.server.turn_end_gate(
                session_id="s1",
                task_id="deadlock-read",
                stop_condition="interpretation_deadlock",
                work_summary="Collected concrete evidence before reporting an unresolved interpretation conflict.",
                receipt_ids=[receipt.receipt_id],
                reason_for_stopping="Parser can mean the CLI parser or report parser, and local evidence cannot distinguish which target the user intended.",
            )
            self.assertIn("APPROVED", approved)

        read_receipt = self.make_read_receipt("deadlock-read", "notes.md")
        read_slice = self.server.turn_end_gate(
            session_id="s1",
            task_id="deadlock-read",
            stop_condition="slice_verified",
            work_summary="Read notes and claimed a slice without execution or mutation progress.",
            receipt_ids=[read_receipt.receipt_id],
        )
        self.assertIn("APPROVED", read_slice)

        later_receipt = self.make_receipt("deadlock-read", "inspect-after-read.py")
        rejected = self.server.turn_end_gate(
            session_id="s1",
            task_id="deadlock-read",
            stop_condition="interpretation_deadlock",
            work_summary="Tried another interpretation deadlock after only read-only activity.",
            receipt_ids=[later_receipt.receipt_id],
            reason_for_stopping="Module name can mean public API module or internal runtime module, and both readings still fit the files.",
        )
        self.assertIn("REJECTED", rejected)
        self.assertIn("too many times without real progress", rejected)


if __name__ == "__main__":
    unittest.main()
