from __future__ import annotations

import builtins
import importlib
import io
import json
import os
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from contextlib import redirect_stderr
from datetime import datetime
from pathlib import Path


class RuntimeTestCase(unittest.TestCase):
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

    def make_bash_receipt(
        self, session_id: str, task_id: str, command: str, exit_code: int = 0
    ):
        return self.store.record_receipt(
            session_id=session_id,
            task_id=task_id,
            source="test",
            tool_name="Bash",
            command_text=command,
            exit_code=exit_code,
            metadata={"stdout_sha256": "abc"},
        )

    def test_missions_are_isolated_by_session(self) -> None:
        self.server.mission_lock("s1", "t1", "goal one", ["criterion one"])
        self.server.mission_lock("s2", "t2", "goal two", ["criterion two"])
        status_one = self.server.mission_status("s1", "t1")
        status_two = self.server.mission_status("s2", "t2")
        self.assertIn("goal: goal one", status_one)
        self.assertIn("goal: goal two", status_two)
        self.assertNotEqual(status_one, status_two)

    def test_same_task_id_is_isolated_across_sessions(self) -> None:
        self.server.mission_lock("s1", "shared-task", "goal one", ["criterion one"])
        self.server.mission_lock("s2", "shared-task", "goal two", ["criterion two"])
        status_one = self.server.mission_status("s1", "shared-task")
        status_two = self.server.mission_status("s2", "shared-task")
        self.assertIn("session_id: s1", status_one)
        self.assertIn("goal: goal one", status_one)
        self.assertIn("session_id: s2", status_two)
        self.assertIn("goal: goal two", status_two)

    def test_mission_lock_rejects_duplicate_completion_criteria(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicate completion criterion"):
            self.server.mission_lock(
                "s1",
                "dup-criteria-task",
                "goal",
                ["tests pass", "tests pass"],
            )

    def test_turn_end_gate_requires_real_receipts(self) -> None:
        self.server.mission_lock("s1", "t1", "refactor", ["tests pass"])
        with self.assertRaises(ValueError):
            self.server.turn_end_gate(
                session_id="s1",
                task_id="t1",
                stop_condition="slice_verified",
                work_summary="Implemented refactor and ran checks.",
                receipt_ids=["missing"],
            )

    def test_stuck_escalation_is_bounded_by_retry_budget(self) -> None:
        self.server.mission_lock("s1", "t1", "refactor", ["tests pass"], retry_budget=2)
        receipt = self.make_bash_receipt("s1", "t1", "pytest -q", exit_code=1)
        self.server.record_stuck_attempt(
            "s1", "t1", "strategy-a", "first failed strategy", [receipt.receipt_id]
        )
        rejected = self.server.turn_end_gate(
            session_id="s1",
            task_id="t1",
            stop_condition="stuck_escalation",
            work_summary="Tried one approach and gathered failing evidence.",
            receipt_ids=[receipt.receipt_id],
            reason_for_stopping="Only one distinct strategy has been tried so far, so escalation is premature.",
        )
        self.assertIn("REJECTED", rejected)
        receipt_two = self.make_bash_receipt("s1", "t1", "python repro.py", exit_code=1)
        self.server.record_stuck_attempt(
            "s1", "t1", "strategy-b", "second failed strategy", [receipt_two.receipt_id]
        )
        approved = self.server.turn_end_gate(
            session_id="s1",
            task_id="t1",
            stop_condition="stuck_escalation",
            work_summary="Tried two materially different approaches and both failed with direct evidence.",
            receipt_ids=[receipt_two.receipt_id],
            reason_for_stopping="Two materially different strategies failed and further local retries would repeat the same search space.",
        )
        self.assertIn("APPROVED", approved)

    def test_completion_gate_rejects_forged_receipt_signature(self) -> None:
        self.server.mission_lock("s1", "forged-task", "goal", ["tests pass"])
        legit = self.make_bash_receipt("s1", "forged-task", "pytest -q")
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute(
                "UPDATE receipts SET tool_name=? WHERE receipt_id=?",
                ("TamperedTool", legit.receipt_id),
            )
            conn.commit()
        rejected = self.server.completion_gate(
            session_id="s1",
            task_id="forged-task",
            criterion_receipt_map=[
                {"criterion": "tests pass", "receipt_ids": [legit.receipt_id]}
            ],
            completion_summary="Mapped tampered receipt to criterion.",
        )
        self.assertIn("REJECTED", rejected)
        self.assertIn("invalid receipt signature", rejected.lower())

    def test_completion_gate_rejects_project_learning_memory_id_as_receipt(self) -> None:
        self.server.mission_lock("s1", "memory-id-task", "goal", ["tests pass"])
        with self.assertRaises(ValueError):
            self.server.completion_gate(
                session_id="s1",
                task_id="memory-id-task",
                criterion_receipt_map=[
                    {"criterion": "tests pass", "receipt_ids": ["pitfall_opencode_bridge_optional"]}
                ],
                completion_summary="Attempted to use a project learning id as receipt evidence.",
            )

    def test_receipts_are_isolated_across_tasks(self) -> None:
        self.server.mission_lock("s1", "task-a", "goal a", ["criterion"])
        self.server.mission_lock("s1", "task-b", "goal b", ["criterion"])
        r_a = self.store.record_receipt(
            session_id="s1", task_id="task-a", source="test",
            tool_name="Bash", command_text="pytest -q", exit_code=0, metadata={},
        )
        r_b = self.store.record_receipt(
            session_id="s1", task_id="task-b", source="test",
            tool_name="Bash", command_text="lint src/", exit_code=0, metadata={},
        )
        recs_a = self.store.get_receipts([r_a.receipt_id], session_id="s1", task_id="task-a")
        recs_b = self.store.get_receipts([r_a.receipt_id], session_id="s1", task_id="task-b")
        self.assertEqual(len(recs_a), 1)
        self.assertEqual(len(recs_b), 0)

    def test_completion_gate_requires_all_criteria(self) -> None:
        self.server.mission_lock("s1", "t1", "ship fix", ["tests pass", "file changed"])
        receipt = self.make_bash_receipt("s1", "t1", "pytest -q", exit_code=0)
        rejected = self.server.completion_gate(
            session_id="s1",
            task_id="t1",
            criterion_receipt_map=[
                {"criterion": "tests pass", "receipt_ids": [receipt.receipt_id]}
            ],
            completion_summary="Executed tests and observed success, but not every criterion is covered.",
        )
        self.assertIn("REJECTED", rejected)
        status_after_reject = self.server.mission_status("s1", "t1")
        self.assertIn("status: active", status_after_reject)
        self.assertNotIn("status: completed", status_after_reject)

    def test_completion_gate_rejects_unknown_criterion_mapping(self) -> None:
        self.server.mission_lock("s1", "t1", "ship fix", ["tests pass"])
        receipt = self.make_bash_receipt("s1", "t1", "pytest -q", exit_code=0)
        rejected = self.server.completion_gate(
            session_id="s1",
            task_id="t1",
            criterion_receipt_map=[
                {"criterion": "tests pass", "receipt_ids": [receipt.receipt_id]},
                {"criterion": "bonus evidence", "receipt_ids": [receipt.receipt_id]},
            ],
            completion_summary="Included an extra criterion mapping that is not part of the mission contract.",
        )
        self.assertIn("REJECTED", rejected)
        self.assertIn("Unknown criterion mappings", rejected)

    def test_completion_gate_rejects_same_receipt_reused_for_multiple_criteria_when_one_is_semantically_invalid(self) -> None:
        self.server.mission_lock("s1", "t1", "ship fix", ["tests pass", "file changed"])
        receipt = self.make_bash_receipt("s1", "t1", "pytest -q", exit_code=0)
        rejected = self.server.completion_gate(
            session_id="s1",
            task_id="t1",
            criterion_receipt_map=[
                {"criterion": "tests pass", "receipt_ids": [receipt.receipt_id]},
                {"criterion": "file changed", "receipt_ids": [receipt.receipt_id]},
            ],
            completion_summary="Reused one test execution receipt for both the test and file-change criteria to audit criterion mixing.",
        )
        self.assertIn("REJECTED", rejected)
        self.assertIn("file changed", rejected)

    def test_completion_gate_marks_done_when_all_criteria_are_covered(self) -> None:
        self.server.mission_lock("s1", "t1", "ship fix", ["tests pass"])
        receipt = self.make_bash_receipt("s1", "t1", "pytest -q", exit_code=0)
        approved = self.server.completion_gate(
            session_id="s1",
            task_id="t1",
            criterion_receipt_map=[
                {"criterion": "tests pass", "receipt_ids": [receipt.receipt_id]}
            ],
            completion_summary="Ran the required test command and observed a zero-exit result.",
        )
        self.assertIn("APPROVED", approved)
        status = self.server.mission_status("s1", "t1")
        self.assertIn("status: completed", status)

    def test_decision_records_and_counterexamples_can_be_logged(self) -> None:
        self.server.mission_lock("s1", "t1", "analyze change", ["tests pass"])
        receipt = self.make_bash_receipt("s1", "t1", "pytest -q", exit_code=0)
        decision = self.server.record_decision_record(
            "s1",
            "t1",
            "choose minimal fix",
            "patch parser only",
            ["rewrite tokenizer"],
            [receipt.receipt_id],
            "reversible",
            ["new failing corpus"],
        )
        counter = self.server.record_counterexample_check(
            "s1",
            "t1",
            "the parser fix generalizes",
            ["run negative case"],
            "negative case did not fail",
            [receipt.receipt_id],
            "hidden corpus risk remains",
        )
        status = self.server.mission_status("s1", "t1")
        self.assertIn("DECISION RECORDED", decision)
        self.assertIn("COUNTEREXAMPLE CHECK RECORDED", counter)
        self.assertIn("decision_records: 1", status)
        self.assertIn("counterexample_checks: 1", status)

    def test_record_stuck_attempt_rejects_duplicate_receipt_ids(self) -> None:
        self.server.mission_lock("s1", "dup-stuck", "goal", ["criterion"])
        receipt = self.make_bash_receipt("s1", "dup-stuck", "pytest -q", exit_code=1)
        with self.assertRaisesRegex(ValueError, "duplicate receipt_id"):
            self.server.record_stuck_attempt(
                "s1",
                "dup-stuck",
                "strategy-a",
                "repeated the same receipt id to test duplicate evidence rejection",
                [receipt.receipt_id, receipt.receipt_id],
            )

    def test_record_decision_record_rejects_duplicate_receipt_ids(self) -> None:
        self.server.mission_lock("s1", "dup-decision", "goal", ["criterion"])
        receipt = self.make_bash_receipt("s1", "dup-decision", "pytest -q", exit_code=0)
        with self.assertRaisesRegex(ValueError, "duplicate receipt_id"):
            self.server.record_decision_record(
                "s1",
                "dup-decision",
                "choose minimal fix",
                "patch parser only",
                ["rewrite tokenizer"],
                [receipt.receipt_id, receipt.receipt_id],
                "reversible",
                ["new failing corpus"],
            )

    def test_record_counterexample_check_rejects_duplicate_receipt_ids(self) -> None:
        self.server.mission_lock("s1", "dup-counterexample", "goal", ["criterion"])
        receipt = self.make_bash_receipt("s1", "dup-counterexample", "pytest -q", exit_code=0)
        with self.assertRaisesRegex(ValueError, "duplicate receipt_id"):
            self.server.record_counterexample_check(
                "s1",
                "dup-counterexample",
                "the parser fix generalizes",
                ["run negative case"],
                "negative case did not fail",
                [receipt.receipt_id, receipt.receipt_id],
                "hidden corpus risk remains",
            )

    def test_completion_gate_rejects_when_required_counterexample_missing(self) -> None:
        self.server.mission_lock(
            "s1",
            "t1",
            "ship fix",
            ["tests pass"],
            counterexample_required=True,
            decision_records_required=True,
        )
        receipt = self.make_bash_receipt("s1", "t1", "pytest -q", exit_code=0)
        rejected = self.server.completion_gate(
            session_id="s1",
            task_id="t1",
            criterion_receipt_map=[
                {"criterion": "tests pass", "receipt_ids": [receipt.receipt_id]}
            ],
            completion_summary="Ran the required test command and observed a zero-exit result.",
        )
        self.assertIn("REJECTED", rejected)
        self.assertIn("counterexample", rejected.lower())
        self.assertIn("decision record", rejected.lower())
        self.server.record_decision_record(
            "s1",
            "t1",
            "choose minimal fix",
            "patch parser only",
            ["rewrite tokenizer"],
            [receipt.receipt_id],
            "reversible",
            ["new failing corpus"],
        )
        self.server.record_counterexample_check(
            "s1",
            "t1",
            "the parser fix generalizes",
            ["run negative case"],
            "negative case did not fail",
            [receipt.receipt_id],
            "hidden corpus risk remains",
        )
        approved = self.server.completion_gate(
            session_id="s1",
            task_id="t1",
            criterion_receipt_map=[
                {"criterion": "tests pass", "receipt_ids": [receipt.receipt_id]}
            ],
            completion_summary="Ran the required test command, recorded the decision, and recorded the counterexample check.",
        )
        self.assertIn("APPROVED", approved)

    def test_verify_receipt_integrity_and_handoff_packet(self) -> None:
        self.server.mission_lock(
            "s1",
            "t1",
            "ship fix",
            ["tests pass"],
            time_budget_minutes=30,
            risk_budget="local reversible edits only",
        )
        receipt = self.make_bash_receipt("s1", "t1", "pytest -q", exit_code=0)
        integrity = json.loads(
            self.server.verify_receipt_integrity("s1", [receipt.receipt_id], "t1")
        )
        self.assertTrue(integrity["all_valid"])
        packet = json.loads(self.server.export_handoff_packet("s1", "t1"))
        self.assertEqual(packet["mission"]["goal"], "ship fix")
        self.assertEqual(packet["mission"]["notes"]["time_budget_minutes"], 30)
        self.assertIn("recommended_next_action", packet)

    def test_verify_receipt_integrity_rejects_duplicate_receipt_ids(self) -> None:
        self.server.mission_lock("s1", "dup-verify", "goal", ["criterion"])
        receipt = self.make_bash_receipt("s1", "dup-verify", "pytest -q", exit_code=0)
        with self.assertRaisesRegex(ValueError, "duplicate receipt_id"):
            self.server.verify_receipt_integrity(
                "s1", [receipt.receipt_id, receipt.receipt_id], "dup-verify"
            )

    def test_list_recent_receipts_whitespace_scope_prefers_active_mission(self) -> None:
        self.server.mission_lock("s1", "task-a", "goal", ["criterion"])
        self.server.mission_lock("s1", "task-b", "goal", ["criterion"])
        receipt_a = self.make_bash_receipt("s1", "task-a", "pytest task_a", exit_code=0)
        receipt_b = self.make_bash_receipt("s1", "task-b", "pytest task_b", exit_code=0)

        scoped = self.server.list_recent_receipts("s1", "task-a", 10)
        whitespace_all = self.server.list_recent_receipts("s1", "   ", 10)

        self.assertIn(receipt_a.receipt_id, scoped)
        self.assertNotIn(receipt_b.receipt_id, scoped)
        self.assertIn(receipt_b.receipt_id, whitespace_all)
        self.assertNotIn(receipt_a.receipt_id, whitespace_all)

    def test_mission_status_trims_whitespace_task_scope(self) -> None:
        self.server.mission_lock("s1", "task-a", "goal a", ["criterion a"])
        self.server.mission_lock("s1", "task-b", "goal b", ["criterion b"])

        explicit = self.server.mission_status("s1", "task-b")
        implicit = self.server.mission_status("s1", "   ")

        self.assertIn("task_id: task-b", explicit)
        self.assertIn("task_id: task-b", implicit)

    def test_verify_receipt_integrity_trims_whitespace_task_scope(self) -> None:
        self.server.mission_lock("s1", "verify-task", "goal", ["criterion"])
        receipt = self.make_bash_receipt("s1", "verify-task", "pytest -q", exit_code=0)
        explicit = json.loads(
            self.server.verify_receipt_integrity("s1", [receipt.receipt_id], "verify-task")
        )
        implicit = json.loads(
            self.server.verify_receipt_integrity("s1", [receipt.receipt_id], "   ")
        )
        self.assertEqual(explicit, implicit)

    def test_budget_status_authorization_status_and_handoff_accept_whitespace_task_scope(
        self,
    ) -> None:
        self.server.mission_lock("s1", "task-b", "goal b", ["criterion b"])
        receipt = self.make_bash_receipt("s1", "task-b", "pytest -q", exit_code=0)
        self.server.record_user_authorization(
            "s1",
            "task-b",
            "publish docs",
            "current branch only",
            "User explicitly approved the action.",
        )
        self.server.turn_end_gate(
            session_id="s1",
            task_id="task-b",
            stop_condition="slice_verified",
            work_summary="Ran one verified slice with concrete command output evidence.",
            receipt_ids=[receipt.receipt_id],
        )

        implicit_budget = json.loads(self.server.budget_status("s1", "   "))
        implicit_auth = json.loads(self.server.authorization_status("s1", "   "))
        implicit_handoff = json.loads(self.server.export_handoff_packet("s1", "   "))

        self.assertNotIn("error", implicit_budget)
        self.assertEqual(implicit_auth["task_id"], "task-b")
        self.assertEqual(implicit_handoff["mission"]["task_id"], "task-b")

    def test_budget_status_authorization_status_and_handoff_reject_whitespace_scope_when_no_active_mission(
        self,
    ) -> None:
        self.server.mission_lock("s1", "task-b", "goal b", ["criterion b"])
        receipt = self.make_bash_receipt("s1", "task-b", "pytest -q", exit_code=0)
        self.server.completion_gate(
            session_id="s1",
            task_id="task-b",
            criterion_receipt_map=[
                {"criterion": "criterion b", "receipt_ids": [receipt.receipt_id]}
            ],
            completion_summary="Mapped the only criterion to a successful execution receipt and completed the mission.",
        )

        budget = json.loads(self.server.budget_status("s1", "   "))
        auth = json.loads(self.server.authorization_status("s1", "   "))
        handoff = json.loads(self.server.export_handoff_packet("s1", "   "))

        self.assertEqual(budget["error"], "No mission found for this session/task.")
        self.assertEqual(auth["error"], "No mission found for this session/task.")
        self.assertEqual(handoff["error"], "No mission found for this session/task.")

    def test_verify_receipt_integrity_can_read_taskless_receipt_from_session_scope(self) -> None:
        receipt = self.store.record_receipt(
            session_id="taskless-session",
            task_id=None,
            source="test",
            tool_name="Bash",
            command_text="pytest -q",
            exit_code=0,
            metadata={"stdout_sha256": "abc"},
        )
        payload = json.loads(
            self.server.verify_receipt_integrity(
                "taskless-session", [receipt.receipt_id], ""
            )
        )
        self.assertTrue(payload["all_valid"])
        self.assertEqual(payload["results"][0]["task_id"], None)

    def test_record_receipt_rejects_explicit_forged_identity(self) -> None:
        self.server.mission_lock("s1", "forge-id-task", "goal", ["criterion"])
        legit = self.make_bash_receipt("s1", "forge-id-task", "pytest -q")
        with self.assertRaisesRegex(ValueError, "Receipt signature mismatch"):
            self.store.record_receipt(
                session_id="s1",
                task_id="forge-id-task",
                source="test",
                tool_name="Bash",
                command_text="pytest -q --maxfail=1",
                exit_code=0,
                metadata={"stdout_sha256": "abc"},
                created_at=legit.created_at,
                receipt_id=legit.receipt_id,
                signature=legit.signature,
            )

    def test_slice_budget_is_enforced_after_limit(self) -> None:
        self.server.mission_lock(
            "s1",
            "t1",
            "limit slices",
            ["one slice"],
            slice_budget=1,
            time_budget_minutes=10,
        )
        receipt = self.make_bash_receipt("s1", "t1", "python one.py", exit_code=0)
        approved = self.server.turn_end_gate(
            session_id="s1",
            task_id="t1",
            stop_condition="slice_verified",
            work_summary="Executed the only allowed verified slice for this mission.",
            receipt_ids=[receipt.receipt_id],
        )
        self.assertIn("APPROVED", approved)
        receipt_two = self.make_bash_receipt("s1", "t1", "python two.py", exit_code=0)
        rejected = self.server.turn_end_gate(
            session_id="s1",
            task_id="t1",
            stop_condition="slice_verified",
            work_summary="Attempted to claim a second verified slice after the slice budget was exhausted.",
            receipt_ids=[receipt_two.receipt_id],
        )
        self.assertIn("REJECTED", rejected)
        self.assertIn("slice_budget is exhausted", rejected)
        self.assertIn("wrap_up_guidance:", rejected)

        status = json.loads(self.server.budget_status("s1", "t1"))
        self.assertTrue(status["budget_exhausted"])
        self.assertIn("Do not claim another verified slice", status["wrap_up_guidance"])
        packet = json.loads(self.server.export_handoff_packet("s1", "t1"))
        self.assertEqual(packet["recommended_next_action"], status["wrap_up_guidance"])

    def test_relocking_mission_resets_slice_count_and_created_at(self) -> None:
        self.server.mission_lock("s1", "t1", "initial goal", ["criterion"], slice_budget=4)
        for index in range(3):
            receipt = self.make_bash_receipt("s1", "t1", f"python slice_{index}.py")
            self.server.turn_end_gate(
                session_id="s1",
                task_id="t1",
                stop_condition="slice_verified",
                work_summary=f"Verified slice {index} with direct command output evidence.",
                receipt_ids=[receipt.receipt_id],
            )
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute(
                "UPDATE missions SET created_at=? WHERE session_id=? AND task_id=?",
                ("2000-01-01T00:00:00Z", "s1", "t1"),
            )

        self.server.mission_lock("s1", "t1", "relocked goal", ["criterion"], slice_budget=2)
        mission = self.store.get_mission("s1", "t1")
        self.assertEqual(mission.slice_count, 0)
        self.assertNotEqual(mission.created_at, "2000-01-01T00:00:00Z")

        receipt = self.make_bash_receipt("s1", "t1", "python after_relock.py")
        approved = self.server.turn_end_gate(
            session_id="s1",
            task_id="t1",
            stop_condition="slice_verified",
            work_summary="Verified a fresh slice after relocking the mission with a smaller budget.",
            receipt_ids=[receipt.receipt_id],
        )
        self.assertIn("APPROVED", approved)

    def test_mission_lock_preserves_existing_session_host_and_cwd(self) -> None:
        self.server.mission_lock(
            "s1",
            "t1",
            "goal",
            ["criterion"],
            host="claude-code",
            cwd="/project/root",
        )
        self.server.mission_lock("s1", "t2", "second goal", ["criterion"])
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT host, cwd FROM sessions WHERE session_id=?", ("s1",)
            ).fetchone()
        self.assertEqual(row["host"], "claude-code")
        self.assertEqual(row["cwd"], "/project/root")

    def test_mission_lock_upgrades_default_session_host_and_cwd(self) -> None:
        self.store.ensure_session("s1")
        self.server.mission_lock(
            "s1",
            "t1",
            "goal",
            ["criterion"],
            host="claude-code",
            cwd="/project/root",
        )
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT host, cwd FROM sessions WHERE session_id=?", ("s1",)
            ).fetchone()
        self.assertEqual(row["host"], "claude-code")
        self.assertEqual(row["cwd"], "/project/root")

    def test_goal_alignment_only_triggers_on_third_verified_slice(self) -> None:
        self.server.mission_lock("s1", "align-task", "goal", ["criterion"], slice_budget=5)
        third_result = ""
        for index in range(3):
            receipt = self.make_bash_receipt("s1", "align-task", f"python slice_{index}.py")
            third_result = self.server.turn_end_gate(
                session_id="s1",
                task_id="align-task",
                stop_condition="slice_verified",
                work_summary=f"Verified bounded slice {index} with direct command output evidence.",
                receipt_ids=[receipt.receipt_id],
            )
        self.assertIn("goal_alignment_check_due: yes", third_result)

        receipt = self.make_bash_receipt("s1", "align-task", "python inspect.py")
        non_slice_stop = self.server.turn_end_gate(
            session_id="s1",
            task_id="align-task",
            stop_condition="frontier_exhausted",
            work_summary="Inspected the remaining local frontier and found no executable in-scope action.",
            receipt_ids=[receipt.receipt_id],
        )
        self.assertNotIn("goal_alignment_check_due: yes", non_slice_stop)

    def test_approval_required_does_not_consume_slice_budget(self) -> None:
        self.server.mission_lock(
            "s1",
            "approval-task",
            "wait for approval then execute",
            ["one verified slice"],
            slice_budget=1,
        )
        prep_receipt = self.make_bash_receipt(
            "s1", "approval-task", "python prepare.py", exit_code=0
        )
        approval_stop = self.server.turn_end_gate(
            session_id="s1",
            task_id="approval-task",
            stop_condition="approval_required",
            work_summary="Prepared the external action and now need explicit approval before crossing the authority boundary.",
            receipt_ids=[prep_receipt.receipt_id],
            reason_for_stopping="The next step is externally visible and requires explicit approval before execution.",
        )
        self.assertIn("APPROVED", approval_stop)
        status_after_approval = self.server.mission_status("s1", "approval-task")
        self.assertIn("slice_count: 0/1", status_after_approval)

        verify_receipt = self.make_bash_receipt(
            "s1", "approval-task", "python execute.py", exit_code=0
        )
        verified_stop = self.server.turn_end_gate(
            session_id="s1",
            task_id="approval-task",
            stop_condition="slice_verified",
            work_summary="Executed the approved action and verified the requested slice successfully.",
            receipt_ids=[verify_receipt.receipt_id],
        )
        self.assertIn("APPROVED", verified_stop)

    def test_budget_status_reports_remaining_capacity_and_freshness(self) -> None:
        self.server.mission_lock(
            "s1",
            "t1",
            "observe budgets",
            ["tests pass"],
            slice_budget=2,
            retry_budget=3,
            time_budget_minutes=30,
        )
        receipt = self.make_bash_receipt("s1", "t1", "pytest -q", exit_code=0)
        self.server.turn_end_gate(
            session_id="s1",
            task_id="t1",
            stop_condition="slice_verified",
            work_summary="Ran a first verified slice and now want to inspect the mission budget status.",
            receipt_ids=[receipt.receipt_id],
        )
        status = json.loads(self.server.budget_status("s1", "t1"))
        self.assertEqual(status["slices_remaining"], 1)
        self.assertEqual(status["retries_remaining"], 3)
        self.assertFalse(status["budget_exhausted"])
        self.assertIn("high-value reversible slice", status["wrap_up_guidance"])
        self.assertTrue(status["latest_turn_gate_fresh"])
        receipt_two = self.make_bash_receipt("s1", "t1", "python stale.py", exit_code=0)
        status_two = json.loads(self.server.budget_status("s1", "t1"))
        self.assertEqual(receipt_two.task_id, "t1")
        self.assertFalse(status_two["latest_turn_gate_fresh"])

    def test_list_recent_receipts_clamps_limit_bounds(self) -> None:
        self.server.mission_lock("s1", "limit-task", "goal", ["criterion"])
        newest = None
        oldest_kept = None
        oldest_dropped = None
        for index in range(55):
            receipt = self.make_bash_receipt("s1", "limit-task", f"pytest case_{index}", exit_code=0)
            if index == 54:
                newest = receipt
            if index == 5:
                oldest_kept = receipt
            if index == 4:
                oldest_dropped = receipt

        zero_limit = self.server.list_recent_receipts("s1", "limit-task", 0)
        large_limit = self.server.list_recent_receipts("s1", "limit-task", 999)

        self.assertIsNotNone(newest)
        self.assertIsNotNone(oldest_kept)
        self.assertIsNotNone(oldest_dropped)
        self.assertIn(newest.receipt_id, zero_limit)
        self.assertIn(oldest_kept.receipt_id, large_limit)
        self.assertNotIn(oldest_dropped.receipt_id, large_limit)
        self.assertEqual(len([line for line in large_limit.splitlines() if line.strip()]), 50)

    def test_user_authorization_status_and_handoff(self) -> None:
        self.server.mission_lock(
            "s1", "t1", "perform approved external action", ["approval recorded"]
        )
        receipt = self.make_bash_receipt("s1", "t1", "python prepare.py", exit_code=0)
        recorded = self.server.record_user_authorization(
            "s1",
            "t1",
            "send one outbound status email",
            "single outbound email only",
            "Yes, send that one email.",
            True,
            900,
        )
        self.assertIn("USER AUTHORIZATION RECORDED", recorded)
        status = json.loads(self.server.authorization_status("s1", "t1"))
        self.assertTrue(status["authorization"]["fresh"])
        self.assertTrue(status["authorization"]["irreversible"])
        self.make_bash_receipt("s1", "t1", "python after_auth.py", exit_code=0)
        stale_status = json.loads(self.server.authorization_status("s1", "t1"))
        self.assertFalse(stale_status["authorization"]["fresh"])
        packet = json.loads(self.server.export_handoff_packet("s1", "t1"))
        self.assertIn("latest_user_authorization", packet)
        self.assertEqual(
            packet["latest_user_authorization"]["approval_scope"],
            "single outbound email only",
        )

    def test_record_user_authorization_clamps_ttl_seconds_bounds(self) -> None:
        self.server.mission_lock("s1", "ttl-low", "goal", ["criterion"])
        low_record = self.server.record_user_authorization(
            "s1",
            "ttl-low",
            "publish docs",
            "docs branch only",
            "User approved the docs publish.",
            False,
            1,
        )
        self.assertIn("USER AUTHORIZATION RECORDED", low_record)
        low_approval = self.store.latest_approval("s1", "ttl-low", "user_authorization")
        self.assertIsNotNone(low_approval)
        low_created = datetime.fromisoformat(low_approval.created_at.replace("Z", "+00:00"))
        low_expires = datetime.fromisoformat(low_approval.expires_at.replace("Z", "+00:00"))
        self.assertEqual(int((low_expires - low_created).total_seconds()), 60)

        self.server.mission_lock("s1", "ttl-high", "goal", ["criterion"])
        high_record = self.server.record_user_authorization(
            "s1",
            "ttl-high",
            "publish docs",
            "docs branch only",
            "User approved the docs publish.",
            False,
            999999,
        )
        self.assertIn("USER AUTHORIZATION RECORDED", high_record)
        high_approval = self.store.latest_approval("s1", "ttl-high", "user_authorization")
        self.assertIsNotNone(high_approval)
        high_created = datetime.fromisoformat(high_approval.created_at.replace("Z", "+00:00"))
        high_expires = datetime.fromisoformat(high_approval.expires_at.replace("Z", "+00:00"))
        self.assertEqual(int((high_expires - high_created).total_seconds()), 7200)

    def test_authorization_status_uses_latest_approval_when_timestamps_tie(self) -> None:
        self.server.mission_lock("s1", "t1", "goal", ["criterion"])
        self.server.record_user_authorization(
            "s1",
            "t1",
            "first action",
            "first scope",
            "Approve first action.",
            False,
            900,
        )
        self.server.record_user_authorization(
            "s1",
            "t1",
            "second action",
            "second scope",
            "Approve second action.",
            True,
            900,
        )
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute(
                "UPDATE approvals SET created_at=? WHERE session_id=? AND task_id=? AND gate_type=?",
                ("2026-01-01T00:00:00Z", "s1", "t1", "user_authorization"),
            )
        status = json.loads(self.server.authorization_status("s1", "t1"))
        self.assertEqual(status["authorization"]["approval_scope"], "second scope")
        self.assertTrue(status["authorization"]["irreversible"])

    def test_relock_clears_user_authorization_freshness(self) -> None:
        self.server.mission_lock("s1", "t1", "goal one", ["criterion"])
        self.server.record_user_authorization(
            "s1",
            "t1",
            "send one email",
            "single email only",
            "Yes, do it.",
            True,
            900,
        )
        before = json.loads(self.server.authorization_status("s1", "t1"))
        self.assertTrue(before["authorization"]["fresh"])

        self.server.mission_lock("s1", "t1", "goal two", ["criterion"])
        after = json.loads(self.server.authorization_status("s1", "t1"))
        self.assertIsNone(after["authorization"])

    def test_relock_clears_latest_turn_gate_freshness(self) -> None:
        self.server.mission_lock("s1", "t1", "goal one", ["criterion"])
        receipt = self.make_bash_receipt("s1", "t1", "pytest -q", exit_code=0)
        self.server.turn_end_gate(
            session_id="s1",
            task_id="t1",
            stop_condition="slice_verified",
            work_summary="Ran a verified slice with concrete command output evidence.",
            receipt_ids=[receipt.receipt_id],
        )
        before = self.server.mission_status("s1", "t1")
        self.assertIn("latest_turn_gate_fresh: True", before)

        self.server.mission_lock("s1", "t1", "goal two", ["criterion"])
        after = self.server.mission_status("s1", "t1")
        self.assertNotIn("latest_turn_gate:", after)
        self.assertNotIn("latest_turn_gate_fresh: True", after)

    def test_handoff_packet_includes_budget_snapshot_and_completion_notes(self) -> None:
        self.server.mission_lock(
            "s1",
            "t1",
            "ship fix",
            ["tests pass"],
            time_budget_minutes=30,
            risk_budget="local reversible edits only",
        )
        receipt = self.make_bash_receipt("s1", "t1", "pytest -q", exit_code=0)
        self.server.completion_gate(
            session_id="s1",
            task_id="t1",
            criterion_receipt_map=[
                {"criterion": "tests pass", "receipt_ids": [receipt.receipt_id]}
            ],
            completion_summary="Ran the required test command and observed a zero-exit result.",
            known_risks=["no live deployment performed"],
            unverified_items=["production traffic not exercised"],
        )
        packet = json.loads(self.server.export_handoff_packet("s1", "t1"))
        self.assertIn("budget_status", packet)
        self.assertIn("criterion_coverage", packet)
        self.assertIn("known_risks", packet)
        self.assertIn("unverified_items", packet)
        self.assertEqual(packet["criterion_coverage"][0]["criterion"], "tests pass")

    def test_completion_gate_rejects_receipts_older_than_latest_mutation(self) -> None:
        self.server.mission_lock("s1", "stale-task", "ship fix", ["tests pass"])
        old_test = self.make_bash_receipt("s1", "stale-task", "pytest -q")
        self.store.record_receipt(
            session_id="s1",
            task_id="stale-task",
            source="test",
            tool_name="Edit",
            command_text="src/core.py",
            exit_code=0,
            metadata={"file_path": "src/core.py"},
        )
        rejected = self.server.completion_gate(
            session_id="s1",
            task_id="stale-task",
            criterion_receipt_map=[
                {"criterion": "tests pass", "receipt_ids": [old_test.receipt_id]}
            ],
            completion_summary="Mapped the tests pass criterion to a receipt from before the edit.",
        )
        self.assertIn("REJECTED", rejected)
        self.assertIn("stale evidence", rejected)

    def test_completion_gate_rejects_stale_receipt_laundered_with_mutation_receipt(self) -> None:
        self.server.mission_lock("s1", "launder-task", "ship fix", ["tests pass"])
        old_test = self.make_bash_receipt("s1", "launder-task", "pytest -q")
        edit = self.store.record_receipt(
            session_id="s1",
            task_id="launder-task",
            source="test",
            tool_name="Edit",
            command_text="src/core.py",
            exit_code=0,
            metadata={"file_path": "src/core.py"},
        )
        rejected = self.server.completion_gate(
            session_id="s1",
            task_id="launder-task",
            criterion_receipt_map=[
                {"criterion": "tests pass", "receipt_ids": [old_test.receipt_id, edit.receipt_id]}
            ],
            completion_summary="Mapped tests pass to an old test receipt plus the edit receipt itself.",
        )
        self.assertIn("REJECTED", rejected)
        self.assertIn("stale evidence", rejected)

    def test_completion_gate_rejects_stale_test_laundered_with_read_receipt(self) -> None:
        self.server.mission_lock("s1", "read-launder-task", "ship fix", ["tests pass"])
        old_test = self.make_bash_receipt("s1", "read-launder-task", "pytest -q")
        self.store.record_receipt(
            session_id="s1",
            task_id="read-launder-task",
            source="test",
            tool_name="Edit",
            command_text="src/core.py",
            exit_code=0,
            metadata={"file_path": "src/core.py"},
        )
        read = self.store.record_receipt(
            session_id="s1",
            task_id="read-launder-task",
            source="test",
            tool_name="Read",
            command_text="src/core.py",
            exit_code=0,
            metadata={"file_path": "src/core.py"},
        )
        rejected = self.server.completion_gate(
            session_id="s1",
            task_id="read-launder-task",
            criterion_receipt_map=[
                {"criterion": "tests pass", "receipt_ids": [old_test.receipt_id, read.receipt_id]}
            ],
            completion_summary="Mapped tests pass to an old test receipt plus a read receipt after the edit.",
        )
        self.assertIn("REJECTED", rejected)
        self.assertIn("stale evidence", rejected)

    def test_completion_gate_accepts_receipts_after_latest_mutation(self) -> None:
        self.server.mission_lock("s1", "fresh-task", "ship fix", ["tests pass"])
        self.store.record_receipt(
            session_id="s1",
            task_id="fresh-task",
            source="test",
            tool_name="Edit",
            command_text="src/core.py",
            exit_code=0,
            metadata={"file_path": "src/core.py"},
        )
        fresh_test = self.make_bash_receipt("s1", "fresh-task", "pytest -q")
        approved = self.server.completion_gate(
            session_id="s1",
            task_id="fresh-task",
            criterion_receipt_map=[
                {"criterion": "tests pass", "receipt_ids": [fresh_test.receipt_id]}
            ],
            completion_summary="Mapped the tests pass criterion to a post-edit test receipt.",
        )
        self.assertIn("APPROVED", approved)

    def test_status_tools_report_missing_mission_without_keyerror(self) -> None:
        budget = json.loads(self.server.budget_status("s1", "missing-task"))
        authorization = json.loads(self.server.authorization_status("s1", "missing-task"))
        handoff = json.loads(self.server.export_handoff_packet("s1", "missing-task"))

        self.assertEqual(budget["error"], "No mission found for this session/task.")
        self.assertEqual(authorization["error"], "No mission found for this session/task.")
        self.assertEqual(handoff["error"], "No mission found for this session/task.")

    def test_relocked_deleted_approval_object_is_not_fresh(self) -> None:
        self.server.mission_lock("s1", "approval-task", "goal one", ["criterion"])
        receipt = self.make_bash_receipt("s1", "approval-task", "pytest -q")
        self.server.turn_end_gate(
            session_id="s1",
            task_id="approval-task",
            stop_condition="slice_verified",
            work_summary="Ran one verified slice with concrete command output evidence.",
            receipt_ids=[receipt.receipt_id],
        )
        approval = self.store.latest_approval("s1", "approval-task", "turn_end_gate")
        self.assertTrue(self.store.is_approval_fresh(approval, "s1", "approval-task"))

        self.server.mission_lock("s1", "approval-task", "goal two", ["criterion"])
        self.assertFalse(self.store.is_approval_fresh(approval, "s1", "approval-task"))

    def test_receipts_from_same_session_invalidate_gate_approval(self) -> None:
        self.server.mission_lock("s1", "freshness-task", "goal", ["criterion"])
        receipt = self.make_bash_receipt("s1", "freshness-task", "pytest -q")
        self.server.turn_end_gate(
            session_id="s1",
            task_id="freshness-task",
            stop_condition="slice_verified",
            work_summary="Ran one verified slice with concrete command output evidence.",
            receipt_ids=[receipt.receipt_id],
        )
        approval = self.store.latest_approval("s1", "freshness-task", "turn_end_gate")
        self.assertTrue(self.store.is_approval_fresh(approval, "s1", "freshness-task"))

        self.store.record_receipt(
            session_id="s1",
            task_id="other-task",
            source="test",
            tool_name="Bash",
            command_text="pytest other",
            exit_code=0,
            metadata={},
        )
        self.assertFalse(self.store.is_approval_fresh(approval, "s1", "freshness-task"))

    def test_completion_gate_finds_latest_mutation_beyond_recent_receipt_limit(self) -> None:
        self.server.mission_lock("s1", "deep-stale-task", "ship fix", ["tests pass"])
        old_test = self.make_bash_receipt("s1", "deep-stale-task", "pytest -q")
        self.store.record_receipt(
            session_id="s1",
            task_id="deep-stale-task",
            source="test",
            tool_name="Edit",
            command_text="src/core.py",
            exit_code=0,
            metadata={"file_path": "src/core.py"},
        )
        for index in range(1001):
            self.store.record_receipt(
                session_id="s1",
                task_id="deep-stale-task",
                source="test",
                tool_name="Read",
                command_text=f"file-{index}.txt",
                exit_code=0,
                metadata={"index": index},
            )

        rejected = self.server.completion_gate(
            session_id="s1",
            task_id="deep-stale-task",
            criterion_receipt_map=[
                {"criterion": "tests pass", "receipt_ids": [old_test.receipt_id]}
            ],
            completion_summary="Mapped the tests criterion to a receipt from before an old edit.",
        )
        self.assertIn("REJECTED", rejected)
        self.assertIn("stale evidence", rejected)

    def test_assertion_language_uses_precise_patterns(self) -> None:
        self.server.mission_lock("s1", "assertion-task", "goal", ["criterion"])
        benign_receipt = self.make_bash_receipt("s1", "assertion-task", "pytest -q")
        benign = self.server.turn_end_gate(
            session_id="s1",
            task_id="assertion-task",
            stop_condition="slice_verified",
            work_summary="The user asked whether i should rerun the suite; rerun completed with all green.",
            receipt_ids=[benign_receipt.receipt_id],
        )
        self.assertIn("APPROVED", benign)

        hedge_receipt = self.make_bash_receipt("s1", "assertion-task", "pytest -q")
        rejected = self.server.turn_end_gate(
            session_id="s1",
            task_id="assertion-task",
            stop_condition="slice_verified",
            work_summary="The change should pass now based on the updated implementation.",
            receipt_ids=[hedge_receipt.receipt_id],
        )
        self.assertIn("REJECTED", rejected)

    def test_assertion_language_rejects_chinese_hedging_phrases(self) -> None:
        self.server.mission_lock("s1", "cn-assertion-task", "goal", ["criterion"])
        cases = [
            "这个改动应该可以了，我先停在这里，虽然我还没有给出新的可核验结果。",
            "现在大概没问题了，可以先算完成，不过我还没有补充新的验证证据。",
            "结果看起来对了，应该不用继续查，但当前总结仍然缺少明确的动作与结果对应。",
            "我觉得这次能过，先结束这一轮，不过这里仍然是在凭感觉判断而不是基于新证据。",
        ]
        for index, summary in enumerate(cases):
            with self.subTest(summary=summary):
                receipt = self.make_bash_receipt(
                    "s1", "cn-assertion-task", f"pytest -q  # {index}"
                )
                rejected = self.server.turn_end_gate(
                    session_id="s1",
                    task_id="cn-assertion-task",
                    stop_condition="slice_verified",
                    work_summary=summary,
                    receipt_ids=[receipt.receipt_id],
                )
                self.assertIn("REJECTED", rejected)

    def test_assertion_language_allows_chinese_user_question_without_hedging(self) -> None:
        self.server.mission_lock("s1", "cn-benign-assertion-task", "goal", ["criterion"])
        receipt = self.make_bash_receipt("s1", "cn-benign-assertion-task", "pytest -q")
        approved = self.server.turn_end_gate(
            session_id="s1",
            task_id="cn-benign-assertion-task",
            stop_condition="slice_verified",
            work_summary="用户刚才问我要不要再跑一次测试；我已经重跑并记录了新的命令输出与失败信息。",
            receipt_ids=[receipt.receipt_id],
        )
        self.assertIn("APPROVED", approved)

    def test_assertion_language_allows_quoted_english_phrase_in_work_summary(self) -> None:
        self.server.mission_lock("s1", "quoted-assertion-task", "goal", ["criterion"])
        receipt = self.make_bash_receipt("s1", "quoted-assertion-task", "pytest -q")
        approved = self.server.turn_end_gate(
            session_id="s1",
            task_id="quoted-assertion-task",
            stop_condition="slice_verified",
            work_summary='The user wrote "should pass now" in the bug thread, and I reran the suite to compare that claim against fresh evidence.',
            receipt_ids=[receipt.receipt_id],
        )
        self.assertIn("APPROVED", approved)

    def test_assertion_language_allows_quoted_chinese_phrase_in_work_summary(self) -> None:
        self.server.mission_lock("s1", "quoted-cn-assertion-task", "goal", ["criterion"])
        receipt = self.make_bash_receipt("s1", "quoted-cn-assertion-task", "pytest -q")
        approved = self.server.turn_end_gate(
            session_id="s1",
            task_id="quoted-cn-assertion-task",
            stop_condition="slice_verified",
            work_summary='用户在工单里写了“应该可以了”，我已经重新执行测试并把新输出和这句原话做了对照。',
            receipt_ids=[receipt.receipt_id],
        )
        self.assertIn("APPROVED", approved)

    def test_assertion_language_rejects_self_quoted_english_hedging(self) -> None:
        self.server.mission_lock("s1", "self-quoted-assertion-task", "goal", ["criterion"])
        receipt = self.make_bash_receipt("s1", "self-quoted-assertion-task", "pytest -q")
        rejected = self.server.turn_end_gate(
            session_id="s1",
            task_id="self-quoted-assertion-task",
            stop_condition="slice_verified",
            work_summary='I wrote "should pass now" in my summary and stopped there instead of presenting concrete verification results.',
            receipt_ids=[receipt.receipt_id],
        )
        self.assertIn("REJECTED", rejected)

    def test_assertion_language_rejects_self_quoted_chinese_hedging(self) -> None:
        self.server.mission_lock("s1", "self-quoted-cn-assertion-task", "goal", ["criterion"])
        receipt = self.make_bash_receipt("s1", "self-quoted-cn-assertion-task", "pytest -q")
        rejected = self.server.turn_end_gate(
            session_id="s1",
            task_id="self-quoted-cn-assertion-task",
            stop_condition="slice_verified",
            work_summary='我在总结里写了“应该可以了”，然后就停下来了，并没有补充新的可核验证据。',
            receipt_ids=[receipt.receipt_id],
        )
        self.assertIn("REJECTED", rejected)

    def test_multiple_observational_receipts_emit_warning(self) -> None:
        self.server.mission_lock("s1", "warn-task", "goal", ["criterion"])
        read_receipt = self.store.record_receipt(
            session_id="s1",
            task_id="warn-task",
            source="test",
            tool_name="Read",
            command_text="README.md",
            exit_code=0,
            metadata={},
        )
        grep_receipt = self.store.record_receipt(
            session_id="s1",
            task_id="warn-task",
            source="test",
            tool_name="Grep",
            command_text="TODO",
            exit_code=0,
            metadata={},
        )
        approved = self.server.turn_end_gate(
            session_id="s1",
            task_id="warn-task",
            stop_condition="frontier_exhausted",
            work_summary="Inspected the remaining local frontier and found no executable in-scope action after multiple observational reads.",
            receipt_ids=[read_receipt.receipt_id, grep_receipt.receipt_id],
        )
        self.assertIn("warnings:", approved)
        self.assertIn("Only observational receipts were supplied", approved)

    def test_completion_gate_rejects_failed_non_bash_receipt(self) -> None:
        self.server.mission_lock("s1", "powershell-task", "goal", ["tests pass"])
        receipt = self.store.record_receipt(
            session_id="s1",
            task_id="powershell-task",
            source="test",
            tool_name="PowerShell",
            command_text="pytest -q",
            exit_code=1,
            metadata={},
        )
        rejected = self.server.completion_gate(
            session_id="s1",
            task_id="powershell-task",
            criterion_receipt_map=[
                {"criterion": "tests pass", "receipt_ids": [receipt.receipt_id]}
            ],
            completion_summary="Mapped the tests criterion to a failed PowerShell execution receipt for direct audit.",
        )
        self.assertIn("REJECTED", rejected)
        self.assertIn("failed", rejected.lower())

    def test_completion_gate_rejects_observational_receipt_for_tests_pass(self) -> None:
        self.server.mission_lock("s1", "semantic-task", "goal", ["tests pass"])
        receipt = self.store.record_receipt(
            session_id="s1",
            task_id="semantic-task",
            source="test",
            tool_name="Read",
            command_text="README.md",
            exit_code=0,
            metadata={},
        )
        rejected = self.server.completion_gate(
            session_id="s1",
            task_id="semantic-task",
            criterion_receipt_map=[
                {"criterion": "tests pass", "receipt_ids": [receipt.receipt_id]}
            ],
            completion_summary="Mapped the tests criterion to a read receipt to verify semantic enforcement.",
        )
        self.assertIn("REJECTED", rejected)
        self.assertIn("semantic", rejected.lower())

    def test_completion_gate_accepts_execution_receipt_for_tests_pass(self) -> None:
        self.server.mission_lock("s1", "semantic-good-task", "goal", ["tests pass"])
        receipt = self.make_bash_receipt("s1", "semantic-good-task", "pytest -q")
        approved = self.server.completion_gate(
            session_id="s1",
            task_id="semantic-good-task",
            criterion_receipt_map=[
                {"criterion": "tests pass", "receipt_ids": [receipt.receipt_id]}
            ],
            completion_summary="Mapped the tests criterion to a successful test execution receipt.",
        )
        self.assertIn("APPROVED", approved)

    def test_completion_gate_accepts_shell_receipt_for_tests_pass(self) -> None:
        self.server.mission_lock("s1", "shell-task", "goal", ["tests pass"])
        receipt = self.store.record_receipt(
            session_id="s1",
            task_id="shell-task",
            source="test",
            tool_name="Shell",
            command_text="pytest -q",
            exit_code=0,
            metadata={},
        )
        approved = self.server.completion_gate(
            session_id="s1",
            task_id="shell-task",
            criterion_receipt_map=[
                {"criterion": "tests pass", "receipt_ids": [receipt.receipt_id]}
            ],
            completion_summary="Mapped the tests criterion to a successful generic shell execution receipt.",
        )
        self.assertIn("APPROVED", approved)

    def test_completion_gate_accepts_codex_receipt_for_tests_pass(self) -> None:
        self.server.mission_lock("s1", "codex-task", "goal", ["tests pass"])
        receipt = self.store.record_receipt(
            session_id="s1",
            task_id="codex-task",
            source="test",
            tool_name="Codex",
            command_text="pytest -q",
            exit_code=0,
            metadata={},
        )
        approved = self.server.completion_gate(
            session_id="s1",
            task_id="codex-task",
            criterion_receipt_map=[
                {"criterion": "tests pass", "receipt_ids": [receipt.receipt_id]}
            ],
            completion_summary="Mapped the tests criterion to a successful Codex execution receipt.",
        )
        self.assertIn("APPROVED", approved)

    def test_completion_gate_rejects_observational_receipts_for_cross_domain_execution_criteria(
        self,
    ) -> None:
        cases = [
            ("video-task", "render final video cut"),
            ("hardware-task", "simulate pcb timing"),
            ("security-task", "scan malware signatures"),
            ("driver-task", "fuzz driver ioctls"),
        ]
        for task_id, criterion in cases:
            with self.subTest(criterion=criterion):
                self.server.mission_lock("s1", task_id, "goal", [criterion])
                receipt = self.store.record_receipt(
                    session_id="s1",
                    task_id=task_id,
                    source="test",
                    tool_name="Read",
                    command_text="artifact.txt",
                    exit_code=0,
                    metadata={},
                )
                rejected = self.server.completion_gate(
                    session_id="s1",
                    task_id=task_id,
                    criterion_receipt_map=[
                        {"criterion": criterion, "receipt_ids": [receipt.receipt_id]}
                    ],
                    completion_summary="Mapped a cross-domain execution criterion to an observational receipt to audit semantic enforcement.",
                )
                self.assertIn("REJECTED", rejected)
                self.assertIn("semantic", rejected.lower())

    def test_completion_gate_accepts_execution_receipts_for_cross_domain_execution_criteria(
        self,
    ) -> None:
        cases = [
            ("video-good-task", "render final video cut"),
            ("hardware-good-task", "simulate pcb timing"),
            ("security-good-task", "scan malware signatures"),
            ("driver-good-task", "fuzz driver ioctls"),
        ]
        for task_id, criterion in cases:
            with self.subTest(criterion=criterion):
                self.server.mission_lock("s1", task_id, "goal", [criterion])
                receipt = self.make_bash_receipt("s1", task_id, f"python -m task_runner --goal \"{criterion}\"")
                approved = self.server.completion_gate(
                    session_id="s1",
                    task_id=task_id,
                    criterion_receipt_map=[
                        {"criterion": criterion, "receipt_ids": [receipt.receipt_id]}
                    ],
                    completion_summary="Mapped a cross-domain execution criterion to a real execution receipt.",
                )
                self.assertIn("APPROVED", approved)

    def test_completion_gate_rejects_execution_receipt_for_cross_domain_mutation_criteria(
        self,
    ) -> None:
        cases = [
            ("novel-task", "write final chapter draft"),
            ("copy-task", "edit landing page copy"),
            ("slides-task", "updated slide deck"),
        ]
        for task_id, criterion in cases:
            with self.subTest(criterion=criterion):
                self.server.mission_lock("s1", task_id, "goal", [criterion])
                receipt = self.make_bash_receipt("s1", task_id, "python build_artifact.py")
                rejected = self.server.completion_gate(
                    session_id="s1",
                    task_id=task_id,
                    criterion_receipt_map=[
                        {"criterion": criterion, "receipt_ids": [receipt.receipt_id]}
                    ],
                    completion_summary="Mapped a creative mutation criterion to an execution receipt to verify semantic separation.",
                )
                self.assertIn("REJECTED", rejected)
                self.assertIn("semantic", rejected.lower())

    def test_completion_gate_accepts_mutation_receipt_for_cross_domain_mutation_criteria(
        self,
    ) -> None:
        cases = [
            ("novel-good-task", "write final chapter draft", "novel/chapter.md"),
            ("copy-good-task", "edit landing page copy", "marketing/copy.md"),
            ("slides-good-task", "updated slide deck", "slides/final.pptx"),
        ]
        for task_id, criterion, path in cases:
            with self.subTest(criterion=criterion):
                self.server.mission_lock("s1", task_id, "goal", [criterion])
                receipt = self.store.record_receipt(
                    session_id="s1",
                    task_id=task_id,
                    source="test",
                    tool_name="Edit",
                    command_text=path,
                    exit_code=0,
                    metadata={"file_path": path},
                )
                approved = self.server.completion_gate(
                    session_id="s1",
                    task_id=task_id,
                    criterion_receipt_map=[
                        {"criterion": criterion, "receipt_ids": [receipt.receipt_id]}
                    ],
                    completion_summary="Mapped a creative mutation criterion to a file mutation receipt.",
                )
                self.assertIn("APPROVED", approved)

    def test_completion_gate_allows_observational_receipt_for_cross_domain_research_criteria(
        self,
    ) -> None:
        cases = [
            ("research-task", "analyze chapter themes"),
            ("ux-task", "review slide narrative"),
            ("security-research-task", "investigate exploit preconditions"),
        ]
        for task_id, criterion in cases:
            with self.subTest(criterion=criterion):
                self.server.mission_lock("s1", task_id, "goal", [criterion])
                receipt = self.store.record_receipt(
                    session_id="s1",
                    task_id=task_id,
                    source="test",
                    tool_name="Read",
                    command_text="notes.md",
                    exit_code=0,
                    metadata={},
                )
                approved = self.server.completion_gate(
                    session_id="s1",
                    task_id=task_id,
                    criterion_receipt_map=[
                        {"criterion": criterion, "receipt_ids": [receipt.receipt_id]}
                    ],
                    completion_summary="Mapped an analysis-only criterion to an observational receipt.",
                )
                self.assertIn("APPROVED", approved)

    def test_completion_gate_rejects_observational_receipt_for_chinese_execution_criteria(
        self,
    ) -> None:
        cases = [
            ("cn-quant-task", "运行量化因子回测"),
            ("cn-security-task", "扫描系统漏洞"),
            ("cn-video-task", "渲染最终视频"),
        ]
        for task_id, criterion in cases:
            with self.subTest(criterion=criterion):
                self.server.mission_lock("s1", task_id, "goal", [criterion])
                receipt = self.store.record_receipt(
                    session_id="s1",
                    task_id=task_id,
                    source="test",
                    tool_name="Read",
                    command_text="notes.md",
                    exit_code=0,
                    metadata={},
                )
                rejected = self.server.completion_gate(
                    session_id="s1",
                    task_id=task_id,
                    criterion_receipt_map=[
                        {"criterion": criterion, "receipt_ids": [receipt.receipt_id]}
                    ],
                    completion_summary="将中文执行型标准错误映射到观察型凭证，用于系统审计当前语义约束是否足够严格并可跨语言工作。",
                )
                self.assertIn("REJECTED", rejected)
                self.assertIn("semantic", rejected.lower())

    def test_completion_gate_accepts_mutation_receipt_for_chinese_mutation_criteria(
        self,
    ) -> None:
        cases = [
            ("cn-novel-task", "撰写小说终稿", "novel/final.md"),
            ("cn-copy-task", "修改宣传文案", "marketing/copy.md"),
            ("cn-ppt-task", "更新PPT终版", "slides/final.pptx"),
        ]
        for task_id, criterion, path in cases:
            with self.subTest(criterion=criterion):
                self.server.mission_lock("s1", task_id, "goal", [criterion])
                receipt = self.store.record_receipt(
                    session_id="s1",
                    task_id=task_id,
                    source="test",
                    tool_name="Edit",
                    command_text=path,
                    exit_code=0,
                    metadata={"file_path": path},
                )
                approved = self.server.completion_gate(
                    session_id="s1",
                    task_id=task_id,
                    criterion_receipt_map=[
                        {"criterion": criterion, "receipt_ids": [receipt.receipt_id]}
                    ],
                    completion_summary="将中文修改型标准映射到文件变更凭证，用于验证系统对跨语言创作交付物的语义支持是否稳定。",
                )
                self.assertIn("APPROVED", approved)

    def test_completion_gate_allows_observational_receipt_for_chinese_research_criteria(
        self,
    ) -> None:
        cases = [
            ("cn-research-task", "分析角色动机"),
            ("cn-vuln-research-task", "调研漏洞成因"),
        ]
        for task_id, criterion in cases:
            with self.subTest(criterion=criterion):
                self.server.mission_lock("s1", task_id, "goal", [criterion])
                receipt = self.store.record_receipt(
                    session_id="s1",
                    task_id=task_id,
                    source="test",
                    tool_name="Read",
                    command_text="notes.md",
                    exit_code=0,
                    metadata={},
                )
                approved = self.server.completion_gate(
                    session_id="s1",
                    task_id=task_id,
                    criterion_receipt_map=[
                        {"criterion": criterion, "receipt_ids": [receipt.receipt_id]}
                    ],
                    completion_summary="将中文分析型标准映射到观察型凭证，用于验证系统不会把研究类任务误判成执行或修改任务。",
                )
                self.assertIn("APPROVED", approved)

    def test_completion_gate_rejects_execution_only_receipt_for_mixed_execution_and_mutation_criterion(
        self,
    ) -> None:
        self.server.mission_lock(
            "s1",
            "mixed-task-a",
            "goal",
            ["run factor backtest and update report"],
        )
        receipt = self.make_bash_receipt(
            "s1", "mixed-task-a", "python -m backtest run_factor"
        )
        rejected = self.server.completion_gate(
            session_id="s1",
            task_id="mixed-task-a",
            criterion_receipt_map=[
                {
                    "criterion": "run factor backtest and update report",
                    "receipt_ids": [receipt.receipt_id],
                }
            ],
            completion_summary="Mapped a mixed criterion to execution evidence only to verify that mutation evidence is also required.",
        )
        self.assertIn("REJECTED", rejected)
        self.assertIn("semantic", rejected.lower())

    def test_completion_gate_rejects_mutation_only_receipt_for_mixed_execution_and_mutation_criterion(
        self,
    ) -> None:
        self.server.mission_lock(
            "s1",
            "mixed-task-b",
            "goal",
            ["run factor backtest and update report"],
        )
        receipt = self.store.record_receipt(
            session_id="s1",
            task_id="mixed-task-b",
            source="test",
            tool_name="Edit",
            command_text="reports/factor.md",
            exit_code=0,
            metadata={"file_path": "reports/factor.md"},
        )
        rejected = self.server.completion_gate(
            session_id="s1",
            task_id="mixed-task-b",
            criterion_receipt_map=[
                {
                    "criterion": "run factor backtest and update report",
                    "receipt_ids": [receipt.receipt_id],
                }
            ],
            completion_summary="Mapped a mixed criterion to mutation evidence only to verify that execution evidence is also required.",
        )
        self.assertIn("REJECTED", rejected)
        self.assertIn("semantic", rejected.lower())

    def test_completion_gate_accepts_both_receipt_types_for_mixed_execution_and_mutation_criterion(
        self,
    ) -> None:
        self.server.mission_lock(
            "s1",
            "mixed-task-c",
            "goal",
            ["run factor backtest and update report"],
        )
        edit_receipt = self.store.record_receipt(
            session_id="s1",
            task_id="mixed-task-c",
            source="test",
            tool_name="Edit",
            command_text="reports/factor.md",
            exit_code=0,
            metadata={"file_path": "reports/factor.md"},
        )
        run_receipt = self.make_bash_receipt(
            "s1", "mixed-task-c", "python -m backtest run_factor"
        )
        approved = self.server.completion_gate(
            session_id="s1",
            task_id="mixed-task-c",
            criterion_receipt_map=[
                {
                    "criterion": "run factor backtest and update report",
                    "receipt_ids": [edit_receipt.receipt_id, run_receipt.receipt_id],
                }
            ],
            completion_summary="Mapped a mixed criterion to both mutation and execution evidence, with the execution receipt recorded after the edit.",
        )
        self.assertIn("APPROVED", approved)

    def test_completion_gate_rejects_observational_receipt_when_analysis_phrase_hides_execution_requirement(
        self,
    ) -> None:
        self.server.mission_lock(
            "s1",
            "analysis-exec-task",
            "goal",
            ["review test plan and run smoke tests"],
        )
        receipt = self.store.record_receipt(
            session_id="s1",
            task_id="analysis-exec-task",
            source="test",
            tool_name="Read",
            command_text="test-plan.md",
            exit_code=0,
            metadata={},
        )
        rejected = self.server.completion_gate(
            session_id="s1",
            task_id="analysis-exec-task",
            criterion_receipt_map=[
                {
                    "criterion": "review test plan and run smoke tests",
                    "receipt_ids": [receipt.receipt_id],
                }
            ],
            completion_summary="Mapped a mixed review-plus-execution criterion to a read receipt only to verify that analysis wording cannot hide required execution evidence.",
        )
        self.assertIn("REJECTED", rejected)
        self.assertIn("semantic", rejected.lower())

    def test_completion_gate_rejects_observational_receipt_when_chinese_analysis_phrase_hides_execution_requirement(
        self,
    ) -> None:
        self.server.mission_lock(
            "s1",
            "cn-analysis-exec-task",
            "goal",
            ["分析漏洞报告并运行复现脚本"],
        )
        receipt = self.store.record_receipt(
            session_id="s1",
            task_id="cn-analysis-exec-task",
            source="test",
            tool_name="Read",
            command_text="vuln-report.md",
            exit_code=0,
            metadata={},
        )
        rejected = self.server.completion_gate(
            session_id="s1",
            task_id="cn-analysis-exec-task",
            criterion_receipt_map=[
                {
                    "criterion": "分析漏洞报告并运行复现脚本",
                    "receipt_ids": [receipt.receipt_id],
                }
            ],
            completion_summary="将带有分析措辞但实际要求执行的中文标准错误映射到观察型凭证，用于验证观察类短语不会掩盖真实执行要求。",
        )
        self.assertIn("REJECTED", rejected)
        self.assertIn("semantic", rejected.lower())

    def test_stuck_escalation_rejects_short_reason(self) -> None:
        self.server.mission_lock("s1", "t1", "refactor", ["tests pass"], retry_budget=2)
        receipt = self.make_bash_receipt("s1", "t1", "pytest -q", exit_code=1)
        self.server.record_stuck_attempt(
            "s1", "t1", "strategy-a", "first failed strategy", [receipt.receipt_id]
        )
        self.server.record_stuck_attempt(
            "s1", "t1", "strategy-b", "second failed strategy", [receipt.receipt_id]
        )
        rejected = self.server.turn_end_gate(
            session_id="s1",
            task_id="t1",
            stop_condition="stuck_escalation",
            work_summary="Two strategies failed and further local retries are not justified because the problem is upstream.",
            receipt_ids=[receipt.receipt_id],
            reason_for_stopping="done",
        )
        self.assertIn("REJECTED", rejected)

    def test_turn_end_gate_accepts_substantive_chinese_interpretation_deadlock_reason(
        self,
    ) -> None:
        self.server.mission_lock("s1", "cn-deadlock-task", "goal", ["criterion"])
        receipt = self.make_bash_receipt("s1", "cn-deadlock-task", "pytest -q")
        approved = self.server.turn_end_gate(
            session_id="s1",
            task_id="cn-deadlock-task",
            stop_condition="interpretation_deadlock",
            work_summary="我核对了需求说明、现有行为和测试信号，但关键术语仍存在两个互相冲突的解释。",
            receipt_ids=[receipt.receipt_id],
            reason_for_stopping="用户对上线前必须兼容旧协议的要求，与当前重构后只保留新协议的实现方向相互冲突，继续执行会在两个解释之间来回震荡。",
        )
        self.assertIn("APPROVED", approved)

    def test_turn_end_gate_accepts_substantive_chinese_stuck_escalation_reason(
        self,
    ) -> None:
        self.server.mission_lock(
            "s1", "cn-stuck-task", "goal", ["tests pass"], retry_budget=2
        )
        receipt = self.make_bash_receipt("s1", "cn-stuck-task", "pytest -q", exit_code=1)
        self.server.record_stuck_attempt(
            "s1", "cn-stuck-task", "strategy-a", "first failed strategy", [receipt.receipt_id]
        )
        self.server.record_stuck_attempt(
            "s1", "cn-stuck-task", "strategy-b", "second failed strategy", [receipt.receipt_id]
        )
        approved = self.server.turn_end_gate(
            session_id="s1",
            task_id="cn-stuck-task",
            stop_condition="stuck_escalation",
            work_summary="我尝试了两条不同的本地修复路径，失败证据都已记录，继续重试只会重复相同搜索空间。",
            receipt_ids=[receipt.receipt_id],
            reason_for_stopping="两种不同策略都在同一底层约束处失败，继续本地重试不会新增信息，只会重复消耗预算，因此需要升级处理。",
        )
        self.assertIn("APPROVED", approved)

    def test_turn_end_gate_accepts_concise_substantive_chinese_summary(self) -> None:
        self.server.mission_lock("s1", "cn-short-summary-task", "goal", ["criterion"])
        receipt = self.make_bash_receipt("s1", "cn-short-summary-task", "pytest -q")
        approved = self.server.turn_end_gate(
            session_id="s1",
            task_id="cn-short-summary-task",
            stop_condition="slice_verified",
            work_summary="已重跑测试并核对失败日志，确认问题仍稳定复现。",
            receipt_ids=[receipt.receipt_id],
        )
        self.assertIn("APPROVED", approved)

    def test_completion_gate_accepts_substantive_chinese_summary_when_semantics_are_satisfied(
        self,
    ) -> None:
        self.server.mission_lock("s1", "cn-summary-task", "goal", ["撰写小说终稿"])
        receipt = self.store.record_receipt(
            session_id="s1",
            task_id="cn-summary-task",
            source="test",
            tool_name="Edit",
            command_text="novel/final.md",
            exit_code=0,
            metadata={"file_path": "novel/final.md"},
        )
        approved = self.server.completion_gate(
            session_id="s1",
            task_id="cn-summary-task",
            criterion_receipt_map=[
                {"criterion": "撰写小说终稿", "receipt_ids": [receipt.receipt_id]}
            ],
            completion_summary="我已经完成终稿修改并核对章节衔接、角色语气和结尾落点，当前交付物与任务标准一致。",
        )
        self.assertIn("APPROVED", approved)

    def test_completion_gate_accepts_concise_substantive_chinese_summary(self) -> None:
        self.server.mission_lock("s1", "cn-short-completion-task", "goal", ["撰写小说终稿"])
        receipt = self.store.record_receipt(
            session_id="s1",
            task_id="cn-short-completion-task",
            source="test",
            tool_name="Edit",
            command_text="novel/final.md",
            exit_code=0,
            metadata={"file_path": "novel/final.md"},
        )
        approved = self.server.completion_gate(
            session_id="s1",
            task_id="cn-short-completion-task",
            criterion_receipt_map=[
                {"criterion": "撰写小说终稿", "receipt_ids": [receipt.receipt_id]}
            ],
            completion_summary="已完成终稿修改并核对章节衔接，交付物与标准一致。",
        )
        self.assertIn("APPROVED", approved)

    def test_turn_end_gate_rejects_duplicate_receipt_ids(self) -> None:
        self.server.mission_lock("s1", "duplicate-turn-task", "goal", ["criterion"])
        receipt = self.make_bash_receipt("s1", "duplicate-turn-task", "pytest -q")
        with self.assertRaisesRegex(ValueError, "duplicate receipt_id"):
            self.server.turn_end_gate(
                session_id="s1",
                task_id="duplicate-turn-task",
                stop_condition="slice_verified",
                work_summary="Ran one verified slice with concrete command output evidence and then duplicated the same receipt id in the gate call.",
                receipt_ids=[receipt.receipt_id, receipt.receipt_id],
            )

    def test_completion_gate_rejects_duplicate_receipt_ids_within_single_criterion(self) -> None:
        self.server.mission_lock("s1", "duplicate-completion-task", "goal", ["tests pass"])
        receipt = self.make_bash_receipt("s1", "duplicate-completion-task", "pytest -q")
        with self.assertRaisesRegex(ValueError, "duplicate receipt_id"):
            self.server.completion_gate(
                session_id="s1",
                task_id="duplicate-completion-task",
                criterion_receipt_map=[
                    {"criterion": "tests pass", "receipt_ids": [receipt.receipt_id, receipt.receipt_id]}
                ],
                completion_summary="Mapped the same receipt twice inside one criterion to ensure duplicate receipt ids are rejected instead of silently deduplicated.",
            )

    def test_completion_gate_rejects_english_assertion_language_in_completion_summary(
        self,
    ) -> None:
        self.server.mission_lock("s1", "completion-assertion-task", "goal", ["tests pass"])
        receipt = self.make_bash_receipt(
            "s1", "completion-assertion-task", "pytest -q"
        )
        rejected = self.server.completion_gate(
            session_id="s1",
            task_id="completion-assertion-task",
            criterion_receipt_map=[
                {"criterion": "tests pass", "receipt_ids": [receipt.receipt_id]}
            ],
            completion_summary="This should pass now based on the updated implementation and probably does not need deeper verification.",
        )
        self.assertIn("REJECTED", rejected)
        self.assertIn("assertion", rejected.lower())

    def test_completion_gate_rejects_chinese_assertion_language_in_completion_summary(
        self,
    ) -> None:
        self.server.mission_lock("s1", "cn-completion-assertion-task", "goal", ["撰写小说终稿"])
        receipt = self.store.record_receipt(
            session_id="s1",
            task_id="cn-completion-assertion-task",
            source="test",
            tool_name="Edit",
            command_text="novel/final.md",
            exit_code=0,
            metadata={"file_path": "novel/final.md"},
        )
        rejected = self.server.completion_gate(
            session_id="s1",
            task_id="cn-completion-assertion-task",
            criterion_receipt_map=[
                {"criterion": "撰写小说终稿", "receipt_ids": [receipt.receipt_id]}
            ],
            completion_summary="这个版本应该可以了，而且大概没问题了，所以我先按完成处理，不再补充更具体的核验说明。",
        )
        self.assertIn("REJECTED", rejected)
        self.assertIn("assertion", rejected.lower())

    def test_completion_gate_allows_quoted_english_assertion_phrase_in_summary(self) -> None:
        self.server.mission_lock("s1", "quoted-completion-task", "goal", ["tests pass"])
        receipt = self.make_bash_receipt("s1", "quoted-completion-task", "pytest -q")
        approved = self.server.completion_gate(
            session_id="s1",
            task_id="quoted-completion-task",
            criterion_receipt_map=[
                {"criterion": "tests pass", "receipt_ids": [receipt.receipt_id]}
            ],
            completion_summary='The issue thread said "should pass now", but I reran pytest and mapped the fresh zero-exit receipt instead of trusting that quote.',
        )
        self.assertIn("APPROVED", approved)

    def test_completion_gate_allows_quoted_chinese_assertion_phrase_in_summary(self) -> None:
        self.server.mission_lock("s1", "quoted-cn-completion-task", "goal", ["撰写小说终稿"])
        receipt = self.store.record_receipt(
            session_id="s1",
            task_id="quoted-cn-completion-task",
            source="test",
            tool_name="Edit",
            command_text="novel/final.md",
            exit_code=0,
            metadata={"file_path": "novel/final.md"},
        )
        approved = self.server.completion_gate(
            session_id="s1",
            task_id="quoted-cn-completion-task",
            criterion_receipt_map=[
                {"criterion": "撰写小说终稿", "receipt_ids": [receipt.receipt_id]}
            ],
            completion_summary='文档原话写的是“应该可以了”，但我这里映射的是实际修改凭证，并明确区分了引用原句与我的完成判断。',
        )
        self.assertIn("APPROVED", approved)

    def test_assertion_language_rejects_mixed_quote_plus_agent_hedging(self) -> None:
        self.server.mission_lock("s1", "mixed-quote-assertion-task", "goal", ["criterion"])
        receipt = self.make_bash_receipt("s1", "mixed-quote-assertion-task", "pytest -q")
        rejected = self.server.turn_end_gate(
            session_id="s1",
            task_id="mixed-quote-assertion-task",
            stop_condition="slice_verified",
            work_summary='The issue thread said "should pass now", and I think this should pass now too so I am stopping here.',
            receipt_ids=[receipt.receipt_id],
        )
        self.assertIn("REJECTED", rejected)

    def test_completion_gate_rejects_mixed_quote_plus_agent_hedging(self) -> None:
        self.server.mission_lock("s1", "mixed-quote-completion-task", "goal", ["tests pass"])
        receipt = self.make_bash_receipt("s1", "mixed-quote-completion-task", "pytest -q")
        rejected = self.server.completion_gate(
            session_id="s1",
            task_id="mixed-quote-completion-task",
            criterion_receipt_map=[
                {"criterion": "tests pass", "receipt_ids": [receipt.receipt_id]}
            ],
            completion_summary='The issue thread said "should pass now", and I believe it should pass now as well, so I am treating the task as complete.',
        )
        self.assertIn("REJECTED", rejected)

    def test_completion_gate_rejects_duplicate_criterion_entries(self) -> None:
        self.server.mission_lock("s1", "duplicate-criterion-task", "goal", ["tests pass"])
        receipt = self.make_bash_receipt("s1", "duplicate-criterion-task", "pytest -q")
        with self.assertRaisesRegex(ValueError, "duplicate criterion"):
            self.server.completion_gate(
                session_id="s1",
                task_id="duplicate-criterion-task",
                criterion_receipt_map=[
                    {"criterion": "tests pass", "receipt_ids": [receipt.receipt_id]},
                    {"criterion": "tests pass", "receipt_ids": [receipt.receipt_id]},
                ],
                completion_summary="Mapped the same criterion twice to verify duplicate entries are rejected instead of silently overwritten.",
            )

    def test_completion_gate_rejects_self_quoted_english_assertion_phrase(self) -> None:
        self.server.mission_lock("s1", "self-quoted-completion-task", "goal", ["tests pass"])
        receipt = self.make_bash_receipt("s1", "self-quoted-completion-task", "pytest -q")
        rejected = self.server.completion_gate(
            session_id="s1",
            task_id="self-quoted-completion-task",
            criterion_receipt_map=[
                {"criterion": "tests pass", "receipt_ids": [receipt.receipt_id]}
            ],
            completion_summary='I wrote "should pass now" in the completion note and relied on that wording instead of a concrete verified result statement.',
        )
        self.assertIn("REJECTED", rejected)

    def test_completion_gate_rejects_self_quoted_chinese_assertion_phrase(self) -> None:
        self.server.mission_lock("s1", "self-quoted-cn-completion-task", "goal", ["撰写小说终稿"])
        receipt = self.store.record_receipt(
            session_id="s1",
            task_id="self-quoted-cn-completion-task",
            source="test",
            tool_name="Edit",
            command_text="novel/final.md",
            exit_code=0,
            metadata={"file_path": "novel/final.md"},
        )
        rejected = self.server.completion_gate(
            session_id="s1",
            task_id="self-quoted-cn-completion-task",
            criterion_receipt_map=[
                {"criterion": "撰写小说终稿", "receipt_ids": [receipt.receipt_id]}
            ],
            completion_summary='我在完成说明里写了“应该可以了”，并试图用这句带引号的话替代具体的核验结论。',
        )
        self.assertIn("REJECTED", rejected)

    def test_completion_gate_allows_observational_receipt_for_english_false_positive_substrings(
        self,
    ) -> None:
        cases = [
            ("runtime-analysis-task", "analyze runtime memory model"),
            ("passage-analysis-task", "review passage structure"),
            ("copy-number-task", "investigate copy number variation"),
            ("draft-analysis-task", "analyze first draft themes"),
            ("test-plan-task", "review test plan"),
            ("benchmark-report-task", "analyze benchmark report"),
        ]
        for task_id, criterion in cases:
            with self.subTest(criterion=criterion):
                self.server.mission_lock("s1", task_id, "goal", [criterion])
                receipt = self.store.record_receipt(
                    session_id="s1",
                    task_id=task_id,
                    source="test",
                    tool_name="Read",
                    command_text="notes.md",
                    exit_code=0,
                    metadata={},
                )
                approved = self.server.completion_gate(
                    session_id="s1",
                    task_id=task_id,
                    criterion_receipt_map=[
                        {"criterion": criterion, "receipt_ids": [receipt.receipt_id]}
                    ],
                    completion_summary="Mapped a research criterion containing misleading substrings to an observational receipt to audit false-positive semantic matching.",
                )
                self.assertIn("APPROVED", approved)

    def test_completion_gate_allows_observational_receipt_for_chinese_false_positive_terms(
        self,
    ) -> None:
        cases = [
            ("cn-passage-task", "分析通过率叙事变化"),
            ("cn-runtime-task", "研究运行机制表述差异"),
            ("cn-test-plan-task", "审阅测试计划"),
            ("cn-benchmark-task", "分析性能基准报告"),
        ]
        for task_id, criterion in cases:
            with self.subTest(criterion=criterion):
                self.server.mission_lock("s1", task_id, "goal", [criterion])
                receipt = self.store.record_receipt(
                    session_id="s1",
                    task_id=task_id,
                    source="test",
                    tool_name="Read",
                    command_text="notes.md",
                    exit_code=0,
                    metadata={},
                )
                approved = self.server.completion_gate(
                    session_id="s1",
                    task_id=task_id,
                    criterion_receipt_map=[
                        {"criterion": criterion, "receipt_ids": [receipt.receipt_id]}
                    ],
                    completion_summary="将包含易误判词汇的中文研究标准映射到观察型凭证，用于审计子串匹配是否过度激进。",
                )
                self.assertIn("APPROVED", approved)

    def test_completion_gate_rejects_observational_receipt_for_verify_criterion(self) -> None:
        self.server.mission_lock("s1", "verify-task", "goal", ["verify build artifacts"])
        receipt = self.store.record_receipt(
            session_id="s1",
            task_id="verify-task",
            source="test",
            tool_name="Read",
            command_text="build.log",
            exit_code=0,
            metadata={},
        )
        rejected = self.server.completion_gate(
            session_id="s1",
            task_id="verify-task",
            criterion_receipt_map=[
                {"criterion": "verify build artifacts", "receipt_ids": [receipt.receipt_id]}
            ],
            completion_summary="Mapped verify criterion to a read receipt.",
        )
        self.assertIn("REJECTED", rejected)
        self.assertIn("semantic", rejected.lower())

    def test_secret_creation_fails_closed_when_windows_permissions_remain_broad(self) -> None:
        import agent_runway_runtime.store as store_module

        warning_secret = Path(self.temp_dir.name) / "warn-secret.key"
        os.environ["ILH_SECRET_PATH"] = str(warning_secret)
        original_run = store_module.subprocess.run
        original_platform = store_module.sys.platform
        calls: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)

            class Result:
                returncode = 1
                stdout = ""
                stderr = "icacls failed"

            return Result()

        store_module.subprocess.run = fake_run
        store_module.sys.platform = "win32"
        try:
            with self.assertRaisesRegex(PermissionError, "Windows secret ACL could not be tightened"):
                _ = store_module.RuntimeStore(db_path=str(Path(self.temp_dir.name) / "warn-state.db"))
        finally:
            store_module.subprocess.run = original_run
            store_module.sys.platform = original_platform
        self.assertTrue(any(cmd and cmd[0].lower() == "icacls" for cmd in calls))
        self.assertFalse(warning_secret.exists())

    def test_duplicate_receipt_id_does_not_replace_existing_receipt_row(self) -> None:
        self.server.mission_lock("s1", "ledger-task", "goal", ["criterion"])
        first = self.store.record_receipt(
            session_id="s1",
            task_id="ledger-task",
            source="test",
            tool_name="Bash",
            command_text="pytest -q",
            exit_code=0,
            metadata={"stdout_sha256": "abc"},
        )

        second = self.store.record_receipt(
            session_id="s1",
            task_id="ledger-task",
            source="test",
            tool_name="Bash",
            command_text="pytest -q",
            exit_code=0,
            metadata=first.metadata,
            created_at=first.created_at,
            signature=first.signature,
            receipt_id=first.receipt_id,
        )

        with closing(sqlite3.connect(self.db_path)) as conn:
            row = conn.execute(
                "SELECT receipt_id, seq FROM receipts WHERE receipt_id=?",
                (first.receipt_id,),
            ).fetchone()

        self.assertEqual(first.receipt_id, second.receipt_id)
        self.assertEqual(first.seq, 1)
        self.assertEqual(second.seq, 1)
        self.assertEqual(row[0], first.receipt_id)
        self.assertEqual(row[1], 1)

    def test_duplicate_receipt_id_preserves_original_receipt_contents(self) -> None:
        self.server.mission_lock("s1", "ledger-immutability", "goal", ["criterion"])
        first = self.store.record_receipt(
            session_id="s1",
            task_id="ledger-immutability",
            source="test",
            tool_name="Bash",
            command_text="pytest -q",
            exit_code=0,
            metadata={"stdout_sha256": "abc"},
        )

        _ = self.store.record_receipt(
            session_id="s1",
            task_id="ledger-immutability",
            source="test",
            tool_name="Bash",
            command_text="pytest -q",
            exit_code=0,
            metadata=first.metadata,
            created_at=first.created_at,
            signature=first.signature,
            receipt_id=first.receipt_id,
        )

        fetched = self.store.get_receipts(
            [first.receipt_id], session_id="s1", task_id="ledger-immutability"
        )[0]
        self.assertEqual(fetched.command_text, "pytest -q")
        self.assertEqual(fetched.tool_name, "Bash")
        self.assertEqual(fetched.metadata["stdout_sha256"], "abc")
        self.assertEqual(fetched.signature, first.signature)

    def test_runtime_store_recovers_when_secret_exists_check_races_with_read(self) -> None:
        import builtins
        import agent_runway_runtime.store as store_module

        race_secret = Path(self.temp_dir.name) / "race-secret.key"
        race_secret.write_text("seed\n", encoding="utf-8")
        original_exists = Path.exists
        original_read_text = Path.read_text
        original_token_hex = store_module.secrets.token_hex
        original_open = store_module.os.open
        original_fdopen = store_module.os.fdopen

        state = {"read_failed": False}

        def fake_exists(path: Path) -> bool:
            if path == race_secret:
                return True
            return original_exists(path)

        def fake_read_text(path: Path, *args, **kwargs):
            if path == race_secret and not state["read_failed"]:
                state["read_failed"] = True
                raise FileNotFoundError(path)
            return original_read_text(path, *args, **kwargs)

        def fake_token_hex(_n: int) -> str:
            return "b" * 64

        class FakeWriter:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def write(self, _text: str) -> int:
                return 0

        def fake_fdopen(_fd: int, _mode: str, encoding: str | None = None):
            return FakeWriter()

        def fake_open(path: Path, flags: int):
            self.assertEqual(Path(path), race_secret)
            return 1

        try:
            Path.exists = fake_exists
            Path.read_text = fake_read_text
            store_module.secrets.token_hex = fake_token_hex
            store_module.os.open = fake_open
            store_module.os.fdopen = fake_fdopen
            store = store_module.RuntimeStore(
                db_path=str(Path(self.temp_dir.name) / "race-state.db"),
                secret=None,
            )
        finally:
            Path.exists = original_exists
            Path.read_text = original_read_text
            store_module.secrets.token_hex = original_token_hex
            store_module.os.open = original_open
            store_module.os.fdopen = original_fdopen

        self.assertTrue(store.secret)
        self.assertEqual(len(store.secret), 64)

    def test_runtime_store_uses_agent_runway_default_db_directory_when_env_is_unset(self) -> None:
        import agent_runway_runtime.store as store_module

        os.environ.pop("ILH_DB_PATH", None)
        original_cwd = Path.cwd()
        try:
            os.chdir(self.temp_dir.name)
            store = store_module.RuntimeStore(db_path=None, secret="x" * 64)
        finally:
            os.chdir(original_cwd)
        self.assertEqual(store.db_path.name, "state.db")
        self.assertEqual(store.db_path.parent.name, ".agent-runway")
        self.assertEqual(store.db_path.parent.parent, Path(self.temp_dir.name).resolve())

    def test_runtime_store_uses_agent_runway_defaults_when_env_is_unset(self) -> None:
        import agent_runway_runtime.store as store_module

        os.environ.pop("ILH_DB_PATH", None)
        os.environ.pop("ILH_SECRET_PATH", None)
        original_cwd = Path.cwd()
        try:
            os.chdir(self.temp_dir.name)
            store = store_module.RuntimeStore(
                db_path=None,
                secret="x" * 64,
            )
        finally:
            os.chdir(original_cwd)
        self.assertEqual(store.db_path.name, "state.db")
        self.assertEqual(store.db_path.parent.name, ".agent-runway")
        self.assertEqual(store.db_path.parent.parent, Path(self.temp_dir.name).resolve())

        original_expanduser = Path.expanduser

        def fake_expanduser(path_obj: Path):
            text = str(path_obj)
            if text == "~/.config/agent-runway/secret.key":
                return Path(self.temp_dir.name) / "agent-runway" / "secret.key"
            return original_expanduser(path_obj)

        try:
            Path.expanduser = fake_expanduser
            store_default_secret = store_module.RuntimeStore(db_path=str(self.db_path), secret=None)
        finally:
            Path.expanduser = original_expanduser
        self.assertTrue(store_default_secret.secret)


if __name__ == "__main__":
    unittest.main()
