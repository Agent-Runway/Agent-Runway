from __future__ import annotations

import importlib
import io
import os
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from contextlib import redirect_stderr
from pathlib import Path


class RuntimeRegressionTestCase(unittest.TestCase):
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

    def test_interpretation_deadlock_requires_substantive_reason(self) -> None:
        self.server.mission_lock("s1", "deadlock-task", "goal", ["criterion"])
        receipt = self.make_bash_receipt("s1", "deadlock-task", "pytest -q")
        rejected = self.server.turn_end_gate(
            session_id="s1",
            task_id="deadlock-task",
            stop_condition="interpretation_deadlock",
            work_summary="Collected concrete evidence and now claim an interpretation deadlock for audit purposes.",
            receipt_ids=[receipt.receipt_id],
            reason_for_stopping="x" * 30,
        )
        self.assertIn("REJECTED", rejected)
        self.assertIn("interpretation_deadlock", rejected)

    def test_verify_receipt_uses_compare_digest(self) -> None:
        self.server.mission_lock("s1", "compare-task", "goal", ["criterion"])
        receipt = self.make_bash_receipt("s1", "compare-task", "pytest -q")
        import agent_runway_runtime.store as store_module

        calls: list[tuple[str, str]] = []
        original_compare = store_module.hmac.compare_digest

        def tracking_compare(left, right):
            calls.append((left, right))
            return original_compare(left, right)

        store_module.hmac.compare_digest = tracking_compare
        try:
            self.assertTrue(self.store.verify_receipt(receipt))
        finally:
            store_module.hmac.compare_digest = original_compare
        self.assertTrue(calls)

    def test_receipt_sequence_is_unique_under_concurrent_writes(self) -> None:
        self.server.mission_lock("s1", "race-task", "goal", ["criterion"])
        errors: list[Exception] = []

        def worker(index: int) -> None:
            try:
                self.store.record_receipt(
                    session_id="s1",
                    task_id="race-task",
                    source="test",
                    tool_name="Bash",
                    command_text=f"cmd {index}",
                    exit_code=0,
                    metadata={"index": index},
                )
            except Exception as exc:  # pragma: no cover
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(index,)) for index in range(20)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertFalse(errors)
        with closing(sqlite3.connect(self.db_path)) as conn:
            duplicate_rows = conn.execute(
                "SELECT seq, COUNT(*) FROM receipts WHERE session_id=? GROUP BY seq HAVING COUNT(*) > 1",
                ("s1",),
            ).fetchall()
        self.assertEqual([], duplicate_rows)


    def test_receipt_nonce_distinguishes_identical_new_receipts_same_second(self) -> None:
        self.server.mission_lock("s1", "nonce-task", "goal", ["criterion"])
        fixed_time = "2026-01-01T00:00:00Z"
        first = self.store.record_receipt(
            session_id="s1",
            task_id="nonce-task",
            source="test",
            tool_name="Bash",
            command_text="pytest -q",
            exit_code=0,
            metadata={"stdout_sha256": "same"},
            created_at=fixed_time,
        )
        second = self.store.record_receipt(
            session_id="s1",
            task_id="nonce-task",
            source="test",
            tool_name="Bash",
            command_text="pytest -q",
            exit_code=0,
            metadata={"stdout_sha256": "same"},
            created_at=fixed_time,
        )
        self.assertNotEqual(first.receipt_id, second.receipt_id)
        self.assertNotEqual(first.signature, second.signature)
        self.assertNotEqual(first.seq, second.seq)
        self.assertIn("_receipt_nonce", first.metadata)
        self.assertIn("_receipt_nonce", second.metadata)
        self.assertNotEqual(first.metadata["_receipt_nonce"], second.metadata["_receipt_nonce"])
        self.assertTrue(self.store.verify_receipt(first))
        self.assertTrue(self.store.verify_receipt(second))

    def test_explicit_receipt_replay_reuses_existing_receipt_identity(self) -> None:
        self.server.mission_lock("s1", "replay-task", "goal", ["criterion"])
        original = self.store.record_receipt(
            session_id="s1",
            task_id="replay-task",
            source="test",
            tool_name="Bash",
            command_text="pytest -q",
            exit_code=0,
            metadata={"stdout_sha256": "same"},
            created_at="2026-01-01T00:00:00Z",
        )
        replay = self.store.record_receipt(
            session_id="s1",
            task_id="replay-task",
            source="test",
            tool_name="Bash",
            command_text="pytest -q",
            exit_code=0,
            metadata=dict(original.metadata),
            created_at=original.created_at,
            receipt_id=original.receipt_id,
            signature=original.signature,
        )
        self.assertEqual(original.receipt_id, replay.receipt_id)
        self.assertEqual(original.signature, replay.signature)
        self.assertEqual(original.seq, replay.seq)
        with closing(sqlite3.connect(self.db_path)) as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM receipts WHERE session_id=? AND task_id=?",
                ("s1", "replay-task"),
            ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_secret_creation_is_atomic_when_file_appears_mid_create(self) -> None:
        import agent_runway_runtime.store as store_module

        race_secret = Path(self.temp_dir.name) / "race-secret.key"
        winner_value = "winner-secret"
        original_exists = Path.exists
        original_os_open = store_module.os.open
        seen_exists = {"count": 0}

        def patched_exists(path_obj):
            if Path(path_obj) == race_secret and seen_exists["count"] == 0:
                seen_exists["count"] += 1
                return False
            return original_exists(path_obj)

        def patched_os_open(file, flags, mode=0o777, *, dir_fd=None):
            path_obj = Path(file)
            if path_obj == race_secret and flags & store_module.os.O_EXCL:
                race_secret.write_text(winner_value + "\n", encoding="utf-8")
                raise FileExistsError("simulated concurrent create")
            return original_os_open(file, flags, mode, dir_fd=dir_fd)

        Path.exists = patched_exists
        store_module.os.open = patched_os_open
        os.environ["ILH_SECRET_PATH"] = str(race_secret)
        try:
            store = store_module.RuntimeStore(
                db_path=str(Path(self.temp_dir.name) / "atomic-state.db")
            )
        finally:
            Path.exists = original_exists
            store_module.os.open = original_os_open
        self.assertEqual(winner_value, store.secret)
        self.assertEqual(
            winner_value, race_secret.read_text(encoding="utf-8").strip()
        )

    def test_relock_clears_stuck_attempts(self) -> None:
        self.server.mission_lock("s1", "t1", "initial goal", ["criterion"], retry_budget=2)
        receipt = self.make_bash_receipt("s1", "t1", "python fail1.py", exit_code=1)
        self.server.record_stuck_attempt(
            "s1", "t1", "strategy-alpha", "first failed approach", [receipt.receipt_id]
        )
        self.server.record_stuck_attempt(
            "s1", "t1", "strategy-beta", "second failed approach", [receipt.receipt_id]
        )
        attempts_before = self.store.list_stuck_attempts("s1", "t1")
        self.assertEqual(len(attempts_before), 2)
        self.server.mission_lock("s1", "t1", "refreshed goal", ["criterion"], retry_budget=2)
        attempts_after = self.store.list_stuck_attempts("s1", "t1")
        self.assertEqual(len(attempts_after), 0)

    def test_stuck_escalation_works_after_relock(self) -> None:
        self.server.mission_lock("s1", "t1", "initial goal", ["criterion"], retry_budget=2)
        receipt = self.make_bash_receipt("s1", "t1", "python fail1.py", exit_code=1)
        self.server.record_stuck_attempt(
            "s1", "t1", "strategy-alpha", "first failed approach", [receipt.receipt_id]
        )
        self.server.mission_lock("s1", "t1", "refreshed goal", ["criterion"], retry_budget=2)
        receipt_two = self.make_bash_receipt("s1", "t1", "python fail2.py", exit_code=1)
        self.server.record_stuck_attempt(
            "s1", "t1", "strategy-gamma", "post-relock failed approach", [receipt_two.receipt_id]
        )
        self.server.record_stuck_attempt(
            "s1", "t1", "strategy-delta", "second post-relock approach", [receipt_two.receipt_id]
        )
        result = self.server.turn_end_gate(
            session_id="s1",
            task_id="t1",
            stop_condition="stuck_escalation",
            work_summary="Exhausted two post-relock strategies and cannot make further local progress.",
            receipt_ids=[receipt_two.receipt_id],
            reason_for_stopping="Two materially different strategies after relock both failed; further retries would repeat the same search space.",
        )
        self.assertIn("APPROVED", result)

    def test_child_task_receipt_stales_parent_task_approval_in_same_session_by_design(
        self,
    ) -> None:
        self.server.mission_lock("s1", "parent-task", "goal", ["criterion"])
        parent_receipt = self.make_bash_receipt("s1", "parent-task", "pytest -q")
        self.server.turn_end_gate(
            session_id="s1",
            task_id="parent-task",
            stop_condition="slice_verified",
            work_summary="Verified the parent task with concrete command output evidence.",
            receipt_ids=[parent_receipt.receipt_id],
        )
        parent_approval = self.store.latest_approval("s1", "parent-task", "turn_end_gate")
        self.assertTrue(self.store.is_approval_fresh(parent_approval, "s1", "parent-task"))

        self.server.mission_lock("s1", "child-task", "goal", ["criterion"])
        self.make_bash_receipt("s1", "child-task", "python child_agent.py")

        self.assertFalse(self.store.is_approval_fresh(parent_approval, "s1", "parent-task"))

    def test_handoff_and_recent_receipts_remain_task_scoped_under_shared_session(self) -> None:
        self.server.mission_lock("s1", "parent-task", "goal", ["tests pass"])
        parent_receipt = self.make_bash_receipt("s1", "parent-task", "pytest parent")
        self.server.mission_lock("s1", "child-task", "goal", ["tests pass"])
        child_receipt = self.make_bash_receipt("s1", "child-task", "pytest child")

        parent_recent = self.store.list_recent_receipts("s1", "parent-task", limit=10)
        child_recent = self.store.list_recent_receipts("s1", "child-task", limit=10)
        self.assertEqual([receipt.receipt_id for receipt in parent_recent], [parent_receipt.receipt_id])
        self.assertEqual([receipt.receipt_id for receipt in child_recent], [child_receipt.receipt_id])

        parent_handoff = io.StringIO(self.server.export_handoff_packet("s1", "parent-task"))
        child_handoff = io.StringIO(self.server.export_handoff_packet("s1", "child-task"))
        self.assertIn(parent_receipt.receipt_id, parent_handoff.getvalue())
        self.assertNotIn(child_receipt.receipt_id, parent_handoff.getvalue())
        self.assertIn(child_receipt.receipt_id, child_handoff.getvalue())
        self.assertNotIn(parent_receipt.receipt_id, child_handoff.getvalue())

    def test_relock_clears_decision_records(self) -> None:
        self.server.mission_lock(
            "s1",
            "t1",
            "initial goal",
            ["tests pass"],
            decision_records_required=True,
        )
        receipt = self.make_bash_receipt("s1", "t1", "pytest -q")
        self.server.record_decision_record(
            "s1",
            "t1",
            "old decision",
            "take path a",
            ["path b"],
            [receipt.receipt_id],
            "reversible",
            ["new evidence"],
        )
        self.server.mission_lock(
            "s1",
            "t1",
            "refreshed goal",
            ["tests pass"],
            decision_records_required=True,
        )
        self.assertEqual(self.store.list_decision_records("s1", "t1"), [])

    def test_relock_clears_counterexample_checks(self) -> None:
        self.server.mission_lock(
            "s1",
            "t1",
            "initial goal",
            ["tests pass"],
            counterexample_required=True,
        )
        receipt = self.make_bash_receipt("s1", "t1", "pytest -q")
        self.server.record_counterexample_check(
            "s1",
            "t1",
            "old hypothesis",
            ["run negative case"],
            "negative case passed",
            [receipt.receipt_id],
            "old residual risk",
        )
        self.server.mission_lock(
            "s1",
            "t1",
            "refreshed goal",
            ["tests pass"],
            counterexample_required=True,
        )
        self.assertEqual(self.store.list_counterexample_checks("s1", "t1"), [])

    def test_completion_gate_rejects_relock_without_new_governance_records(self) -> None:
        self.server.mission_lock(
            "s1",
            "t1",
            "initial goal",
            ["tests pass"],
            decision_records_required=True,
            counterexample_required=True,
        )
        old_receipt = self.make_bash_receipt("s1", "t1", "pytest -q")
        self.server.record_decision_record(
            "s1",
            "t1",
            "old decision",
            "take path a",
            ["path b"],
            [old_receipt.receipt_id],
            "reversible",
            ["new evidence"],
        )
        self.server.record_counterexample_check(
            "s1",
            "t1",
            "old hypothesis",
            ["run negative case"],
            "negative case passed",
            [old_receipt.receipt_id],
            "old residual risk",
        )
        self.server.mission_lock(
            "s1",
            "t1",
            "refreshed goal",
            ["tests pass"],
            decision_records_required=True,
            counterexample_required=True,
        )
        fresh_receipt = self.make_bash_receipt("s1", "t1", "pytest -q")
        rejected = self.server.completion_gate(
            session_id="s1",
            task_id="t1",
            criterion_receipt_map=[
                {"criterion": "tests pass", "receipt_ids": [fresh_receipt.receipt_id]}
            ],
            completion_summary="Ran tests after relock but did not create new governance records.",
        )
        self.assertIn("REJECTED", rejected)
        self.assertIn("decision record", rejected.lower())
        self.assertIn("counterexample", rejected.lower())


    def test_relock_rejects_old_receipt_for_turn_end_gate(self) -> None:
        self.server.mission_lock("s1", "epoch-task", "initial goal", ["tests pass"])
        old_receipt = self.make_bash_receipt("s1", "epoch-task", "pytest -q")
        self.server.mission_lock("s1", "epoch-task", "refreshed goal", ["tests pass"])
        rejected = self.server.turn_end_gate(
            session_id="s1",
            task_id="epoch-task",
            stop_condition="slice_verified",
            work_summary="Tried to close a refreshed mission using old pre-lock evidence.",
            receipt_ids=[old_receipt.receipt_id],
        )
        self.assertIn("REJECTED", rejected)
        self.assertIn("stale receipt", rejected.lower())

    def test_relock_rejects_old_receipt_for_completion_gate(self) -> None:
        self.server.mission_lock("s1", "epoch-complete", "initial goal", ["tests pass"])
        old_receipt = self.make_bash_receipt("s1", "epoch-complete", "pytest -q")
        self.server.mission_lock("s1", "epoch-complete", "refreshed goal", ["tests pass"])
        rejected = self.server.completion_gate(
            session_id="s1",
            task_id="epoch-complete",
            criterion_receipt_map=[
                {"criterion": "tests pass", "receipt_ids": [old_receipt.receipt_id]}
            ],
            completion_summary="Tried to complete a refreshed mission using old pre-lock test evidence.",
        )
        self.assertIn("REJECTED", rejected)
        self.assertIn("stale receipt", rejected.lower())

    def test_relock_accepts_new_receipt_after_epoch(self) -> None:
        self.server.mission_lock("s1", "epoch-fresh", "initial goal", ["tests pass"])
        self.make_bash_receipt("s1", "epoch-fresh", "pytest -q")
        self.server.mission_lock("s1", "epoch-fresh", "refreshed goal", ["tests pass"])
        fresh_receipt = self.make_bash_receipt("s1", "epoch-fresh", "pytest -q")
        approved = self.server.completion_gate(
            session_id="s1",
            task_id="epoch-fresh",
            criterion_receipt_map=[
                {"criterion": "tests pass", "receipt_ids": [fresh_receipt.receipt_id]}
            ],
            completion_summary="Ran the verification command after the refreshed mission lock and mapped it to the criterion.",
        )
        self.assertIn("APPROVED", approved)

    def test_completion_gate_accepts_opencode_receipt_for_tests_pass(self) -> None:
        self.server.mission_lock("s1", "opencode-task", "goal", ["tests pass"])
        receipt = self.store.record_receipt(
            session_id="s1",
            task_id="opencode-task",
            source="test",
            tool_name="OpenCode",
            command_text="pytest -q",
            exit_code=0,
            metadata={},
        )
        approved = self.server.completion_gate(
            session_id="s1",
            task_id="opencode-task",
            criterion_receipt_map=[
                {"criterion": "tests pass", "receipt_ids": [receipt.receipt_id]}
            ],
            completion_summary="Mapped the tests criterion to a successful OpenCode execution receipt.",
        )
        self.assertIn("APPROVED", approved)


if __name__ == "__main__":
    unittest.main()
