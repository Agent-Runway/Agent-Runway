from __future__ import annotations

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

    def make_tool_receipt(
        self,
        session_id: str,
        task_id: str,
        tool_name: str,
        command: str,
        *,
        source: str = "test",
    ):
        return self.store.record_receipt(
            session_id=session_id,
            task_id=task_id,
            source=source,
            tool_name=tool_name,
            command_text=command,
            exit_code=0,
            metadata={"stdout_sha256": "abc"},
        )

    def approve_turn_for_receipt(self, session_id: str, task_id: str, receipt_id: str) -> None:
        approved = self.server.turn_end_gate(
            session_id=session_id,
            task_id=task_id,
            stop_condition="slice_verified",
            work_summary="Verified the current slice with direct receipt evidence before completion.",
            receipt_ids=[receipt_id],
        )
        self.assertIn("APPROVED", approved)

    def test_completion_gate_accepts_apply_patch_as_mutation_evidence(self) -> None:
        self.server.mission_lock("s1", "patch-task", "goal", ["file updated"])
        receipt = self.make_tool_receipt(
            "s1", "patch-task", "apply_patch", "*** Begin Patch", source="claude-hook"
        )
        self.approve_turn_for_receipt("s1", "patch-task", receipt.receipt_id)

        result = self.server.completion_gate(
            session_id="s1",
            task_id="patch-task",
            criterion_receipt_map=[
                {"criterion": "file updated", "receipt_ids": [receipt.receipt_id]}
            ],
            completion_summary="Mapped the file update criterion to a verified apply_patch mutation receipt.",
        )

        self.assertIn("APPROVED", result)

    def test_completion_gate_rejects_shell_write_flag_as_mutation_evidence(self) -> None:
        self.server.mission_lock("s1", "write-task", "goal", ["README table --write updates file"])
        receipt = self.make_tool_receipt(
            "s1",
            "write-task",
            "Bash",
            "python archive/release-tests/readme_api_tool_table_check.py . --json --write",
        )

        result = self.server.completion_gate(
            session_id="s1",
            task_id="write-task",
            criterion_receipt_map=[
                {"criterion": "README table --write updates file", "receipt_ids": [receipt.receipt_id]}
            ],
            completion_summary="Mapped the README table update criterion to the explicit --write command receipt.",
        )

        self.assertIn("REJECTED", result)
        self.assertIn("semantic", result.lower())

    def test_completion_gate_accepts_apply_patch_for_write_flag_criterion(self) -> None:
        self.server.mission_lock("s1", "write-tool-task", "goal", ["README table --write updates file"])
        receipt = self.make_tool_receipt(
            "s1", "write-tool-task", "apply_patch", "*** Begin Patch", source="claude-hook"
        )
        self.approve_turn_for_receipt("s1", "write-tool-task", receipt.receipt_id)

        result = self.server.completion_gate(
            session_id="s1",
            task_id="write-tool-task",
            criterion_receipt_map=[
                {"criterion": "README table --write updates file", "receipt_ids": [receipt.receipt_id]}
            ],
            completion_summary="Mapped the README table update criterion to a real mutation tool receipt.",
        )

        self.assertIn("APPROVED", result)

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
        successes = []
        errors: list[Exception] = []
        result_lock = threading.Lock()
        start = threading.Barrier(20)

        def worker(index: int) -> None:
            try:
                start.wait()
                receipt = self.store.record_receipt(
                    session_id="s1",
                    task_id="race-task",
                    source="test",
                    tool_name="Bash",
                    command_text=f"cmd {index}",
                    exit_code=0,
                    metadata={"index": index},
                )
                with result_lock:
                    successes.append(receipt)
            except Exception as exc:
                with result_lock:
                    errors.append(exc)

        threads = [threading.Thread(target=worker, args=(index,)) for index in range(20)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertFalse(errors)
        self.assertEqual(20, len(successes))
        self.assertEqual(list(range(1, 21)), sorted(receipt.seq for receipt in successes))
        with closing(sqlite3.connect(self.db_path)) as conn:
            duplicate_rows = conn.execute(
                "SELECT seq, COUNT(*) FROM receipts WHERE session_id=? GROUP BY seq HAVING COUNT(*) > 1",
                ("s1",),
            ).fetchall()
            persisted = conn.execute(
                "SELECT seq FROM receipts WHERE session_id=? ORDER BY seq",
                ("s1",),
            ).fetchall()
        self.assertEqual([], duplicate_rows)
        self.assertEqual(list(range(1, 21)), [row[0] for row in persisted])

    def test_receipt_sequence_is_independent_across_concurrent_sessions(self) -> None:
        self.server.mission_lock("s1", "race-task", "goal", ["criterion"])
        self.server.mission_lock("s2", "race-task", "goal", ["criterion"])
        successes = []
        errors: list[Exception] = []
        result_lock = threading.Lock()
        start = threading.Barrier(20)

        def worker(index: int, session_id: str) -> None:
            try:
                start.wait()
                receipt = self.store.record_receipt(
                    session_id=session_id,
                    task_id="race-task",
                    source="test",
                    tool_name="Bash",
                    command_text=f"{session_id} cmd {index}",
                    exit_code=0,
                    metadata={"index": index, "session_id": session_id},
                )
                with result_lock:
                    successes.append(receipt)
            except Exception as exc:
                with result_lock:
                    errors.append(exc)

        threads = [
            threading.Thread(target=worker, args=(index, "s1" if index % 2 == 0 else "s2"))
            for index in range(20)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertFalse(errors)
        self.assertEqual(20, len(successes))
        by_session = {
            session_id: sorted(receipt.seq for receipt in successes if receipt.session_id == session_id)
            for session_id in ("s1", "s2")
        }
        self.assertEqual(list(range(1, 11)), by_session["s1"])
        self.assertEqual(list(range(1, 11)), by_session["s2"])
        with closing(sqlite3.connect(self.db_path)) as conn:
            persisted = conn.execute(
                "SELECT session_id, seq FROM receipts ORDER BY session_id, seq"
            ).fetchall()
        self.assertEqual(
            [("s1", seq) for seq in range(1, 11)]
            + [("s2", seq) for seq in range(1, 11)],
            persisted,
        )

    def test_failed_receipt_insert_rolls_back_without_consuming_sequence(self) -> None:
        self.server.mission_lock("s1", "rollback-task", "goal", ["criterion"])
        import agent_runway_runtime.store as store_module

        original_canonical_json = store_module.canonical_json
        call_state = {"count": 0}

        def fail_only_when_serializing_insert_metadata(value):
            call_state["count"] += 1
            if call_state["count"] == 2:
                raise TypeError("metadata insert serialization failed")
            return original_canonical_json(value)

        store_module.canonical_json = fail_only_when_serializing_insert_metadata
        try:
            with self.assertRaisesRegex(TypeError, "metadata insert serialization failed"):
                self.store.record_receipt(
                    session_id="s1",
                    task_id="rollback-task",
                    source="test",
                    tool_name="Bash",
                    command_text="failing command",
                    exit_code=0,
                    metadata={"raise_on_insert": True},
                )
        finally:
            store_module.canonical_json = original_canonical_json

        recovered = self.store.record_receipt(
            session_id="s1",
            task_id="rollback-task",
            source="test",
            tool_name="Bash",
            command_text="recovered command",
            exit_code=0,
            metadata={"stdout_sha256": "abc"},
        )

        with closing(sqlite3.connect(self.db_path)) as conn:
            rows = conn.execute(
                "SELECT seq, command_text FROM receipts WHERE session_id=? ORDER BY seq",
                ("s1",),
            ).fetchall()
        self.assertEqual(1, recovered.seq)
        self.assertEqual([(1, "recovered command")], rows)

    def test_create_mission_same_task_concurrent_race_has_single_winner(self) -> None:
        successes = []
        errors: list[Exception] = []
        result_lock = threading.Lock()
        start = threading.Barrier(10)

        def worker(index: int) -> None:
            try:
                start.wait()
                mission = self.store.create_mission(
                    "s1",
                    "race-mission",
                    f"goal from worker {index}",
                    ["criterion"],
                    "",
                    [],
                    24,
                    3,
                    notes={"worker": index},
                )
                with result_lock:
                    successes.append(mission)
            except Exception as exc:
                with result_lock:
                    errors.append(exc)

        threads = [threading.Thread(target=worker, args=(index,)) for index in range(10)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(1, len(successes))
        self.assertEqual(9, len(errors))
        self.assertTrue(
            all(
                isinstance(exc, ValueError)
                and "relocking an active mission" in str(exc)
                for exc in errors
            )
        )
        with closing(sqlite3.connect(self.db_path)) as conn:
            rows = conn.execute(
                "SELECT goal, status, notes FROM missions WHERE session_id=? AND task_id=?",
                ("s1", "race-mission"),
            ).fetchall()
        self.assertEqual(1, len(rows))
        self.assertEqual(successes[0].goal, rows[0][0])
        self.assertEqual("active", rows[0][1])
        self.assertEqual(successes[0].notes["worker"], json.loads(rows[0][2])["worker"])

    def test_create_mission_different_tasks_concurrent_do_not_block_each_other(self) -> None:
        successes = []
        errors: list[Exception] = []
        result_lock = threading.Lock()
        start = threading.Barrier(10)

        def worker(index: int) -> None:
            try:
                start.wait()
                mission = self.store.create_mission(
                    "s1",
                    f"race-mission-{index}",
                    f"goal from worker {index}",
                    ["criterion"],
                    "",
                    [],
                    24,
                    3,
                    notes={"worker": index},
                )
                with result_lock:
                    successes.append(mission)
            except Exception as exc:  # pragma: no cover
                with result_lock:
                    errors.append(exc)

        threads = [threading.Thread(target=worker, args=(index,)) for index in range(10)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertFalse(errors)
        self.assertEqual(10, len(successes))
        with closing(sqlite3.connect(self.db_path)) as conn:
            rows = conn.execute(
                "SELECT task_id, status FROM missions WHERE session_id=?",
                ("s1",),
            ).fetchall()
        self.assertEqual(
            {f"race-mission-{index}" for index in range(10)},
            {row[0] for row in rows},
        )
        self.assertEqual({"active"}, {row[1] for row in rows})

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
        self.assertEqual(original, replay)
        with closing(sqlite3.connect(self.db_path)) as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM receipts WHERE session_id=? AND task_id=?",
                ("s1", "replay-task"),
            ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_explicit_receipt_replay_rejects_persisted_db_mismatch(self) -> None:
        self.server.mission_lock("s1", "replay-db-identity", "goal", ["criterion"])
        original = self.store.record_receipt(
            session_id="s1",
            task_id="replay-db-identity",
            source="test",
            tool_name="Bash",
            command_text="pytest -q",
            exit_code=0,
            metadata={"stdout_sha256": "same"},
            created_at="2026-01-01T00:00:00Z",
        )

        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute(
                """
                UPDATE receipts
                SET source=?, tool_name=?, command_text=?, exit_code=?, metadata=?, created_at=?
                WHERE receipt_id=?
                """,
                (
                    "persisted-source",
                    "Read",
                    "Get-Content API.md",
                    None,
                    json.dumps({"persisted": True}, sort_keys=True, separators=(",", ":")),
                    "2026-01-01T00:00:01Z",
                    original.receipt_id,
                ),
            )
            conn.commit()

        with self.assertRaisesRegex(ValueError, "Existing receipt_id row mismatch"):
            self.store.record_receipt(
                session_id="s1",
                task_id="replay-db-identity",
                source="test",
                tool_name="Bash",
                command_text="pytest -q",
                exit_code=0,
                metadata=dict(original.metadata),
                created_at=original.created_at,
                receipt_id=original.receipt_id,
                signature=original.signature,
            )

    def test_receipt_replay_rejects_different_task_scope(self) -> None:
        self.server.mission_lock("s1", "receipt-scope-a", "goal", ["criterion"])
        self.server.mission_lock("s1", "receipt-scope-b", "goal", ["criterion"])
        original = self.make_bash_receipt("s1", "receipt-scope-a", "pytest -q")

        with self.assertRaisesRegex(ValueError, "Receipt signature mismatch"):
            self.store.record_receipt(
                session_id="s1",
                task_id="receipt-scope-b",
                source="test",
                tool_name="Bash",
                command_text="pytest -q",
                exit_code=0,
                metadata=dict(original.metadata),
                created_at=original.created_at,
                receipt_id=original.receipt_id,
                signature=original.signature,
            )

    def test_receipt_replay_rejects_same_task_metadata_change(self) -> None:
        self.server.mission_lock("s1", "receipt-metadata", "goal", ["criterion"])
        original = self.make_bash_receipt("s1", "receipt-metadata", "pytest -q")

        with self.assertRaisesRegex(ValueError, "Receipt signature mismatch"):
            self.store.record_receipt(
                session_id="s1",
                task_id="receipt-metadata",
                source="test",
                tool_name="Bash",
                command_text="pytest -q",
                exit_code=0,
                metadata={"stdout_sha256": "different"},
                created_at=original.created_at,
                receipt_id=original.receipt_id,
                signature=original.signature,
            )

    def test_receipt_replay_rejects_different_session_scope(self) -> None:
        self.server.mission_lock("s1", "receipt-scope", "goal", ["criterion"])
        self.server.mission_lock("s2", "receipt-scope", "goal", ["criterion"])
        original = self.make_bash_receipt("s1", "receipt-scope", "pytest -q")

        with self.assertRaisesRegex(ValueError, "Receipt signature mismatch"):
            self.store.record_receipt(
                session_id="s2",
                task_id="receipt-scope",
                source="test",
                tool_name="Bash",
                command_text="pytest -q",
                exit_code=0,
                metadata=dict(original.metadata),
                created_at=original.created_at,
                receipt_id=original.receipt_id,
                signature=original.signature,
            )

    def test_secret_creation_is_atomic_when_file_appears_mid_create(self) -> None:
        import agent_runway_runtime.store as store_module

        race_secret = Path(self.temp_dir.name) / "race-secret.key"
        winner_value = "c" * 64
        original_harness_secret = os.environ.pop("ILH_HARNESS_SECRET", None)
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
            if original_harness_secret is not None:
                os.environ["ILH_HARNESS_SECRET"] = original_harness_secret
            else:
                os.environ.pop("ILH_HARNESS_SECRET", None)
            Path.exists = original_exists
            store_module.os.open = original_os_open
        self.assertEqual(winner_value, store.secret)
        self.assertEqual(
            winner_value, race_secret.read_text(encoding="utf-8").strip()
        )

    def test_relock_rejected_preserves_stuck_attempts(self) -> None:
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

        with self.assertRaisesRegex(ValueError, "relocking an active mission"):
            self.server.mission_lock("s1", "t1", "refreshed goal", ["criterion"], retry_budget=2)

        attempts_after = self.store.list_stuck_attempts("s1", "t1")
        self.assertEqual(len(attempts_after), 2)

    def test_stuck_escalation_does_not_depend_on_relock(self) -> None:
        self.server.mission_lock("s1", "t1", "initial goal", ["criterion"], retry_budget=2)
        receipt = self.make_bash_receipt("s1", "t1", "python fail1.py", exit_code=1)
        self.server.record_stuck_attempt(
            "s1", "t1", "strategy-alpha", "first failed approach", [receipt.receipt_id]
        )
        receipt_two = self.make_bash_receipt("s1", "t1", "python fail2.py", exit_code=1)
        self.server.record_stuck_attempt(
            "s1", "t1", "strategy-gamma", "post-relock failed approach", [receipt_two.receipt_id]
        )
        result = self.server.turn_end_gate(
            session_id="s1",
            task_id="t1",
            stop_condition="stuck_escalation",
            work_summary="Exhausted two materially different strategies and cannot make further local progress.",
            receipt_ids=[receipt_two.receipt_id],
            reason_for_stopping="Two materially different strategies both failed; further retries would repeat the same search space.",
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

    def test_relock_rejected_preserves_decision_records(self) -> None:
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
        with self.assertRaisesRegex(ValueError, "relocking an active mission"):
            self.server.mission_lock(
                "s1",
                "t1",
                "refreshed goal",
                ["tests pass"],
                decision_records_required=True,
            )
        self.assertEqual(len(self.store.list_decision_records("s1", "t1")), 1)

    def test_relock_rejected_preserves_counterexample_checks(self) -> None:
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
        with self.assertRaisesRegex(ValueError, "relocking an active mission"):
            self.server.mission_lock(
                "s1",
                "t1",
                "refreshed goal",
                ["tests pass"],
                counterexample_required=True,
            )
        self.assertEqual(len(self.store.list_counterexample_checks("s1", "t1")), 1)

    def test_completion_gate_keeps_existing_governance_records(self) -> None:
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
        fresh_receipt = self.make_bash_receipt("s1", "t1", "pytest -q")
        self.approve_turn_for_receipt("s1", "t1", fresh_receipt.receipt_id)
        approved = self.server.completion_gate(
            session_id="s1",
            task_id="t1",
            criterion_receipt_map=[
                {"criterion": "tests pass", "receipt_ids": [fresh_receipt.receipt_id]}
            ],
            completion_summary="Ran tests after preserving the existing governance records.",
        )
        self.assertIn("APPROVED", approved)

    def test_store_mark_completed_without_notes_preserves_existing_notes(self) -> None:
        mission = self.store.create_mission(
            session_id="s1",
            task_id="notes-task",
            goal="goal",
            completion_criteria=["tests pass"],
            scope_boundary="",
            red_lines=[],
            slice_budget=3,
            retry_budget=2,
            notes={"custom": "keep"},
        )

        completed = self.store.mark_completed("s1", "notes-task")

        self.assertEqual("completed", completed.status)
        self.assertEqual("keep", completed.notes["custom"])
        self.assertEqual(
            mission.notes["mission_start_receipt_seq"],
            completed.notes["mission_start_receipt_seq"],
        )

    def test_store_mark_completed_with_notes_overrides_only_supplied_keys(self) -> None:
        self.store.create_mission(
            session_id="s1",
            task_id="notes-merge-task",
            goal="goal",
            completion_criteria=["tests pass"],
            scope_boundary="",
            red_lines=[],
            slice_budget=3,
            retry_budget=2,
            notes={
                "custom": "keep",
                "replace": "old",
                "audit": {"rounds_required": 2, "status": "in_progress"},
            },
        )

        completed = self.store.mark_completed(
            "s1",
            "notes-merge-task",
            notes={"replace": "new", "completion_summary": "completed with evidence"},
        )

        self.assertEqual("completed", completed.status)
        self.assertEqual("keep", completed.notes["custom"])
        self.assertEqual("new", completed.notes["replace"])
        self.assertEqual(
            {"rounds_required": 2, "status": "in_progress"},
            completed.notes["audit"],
        )
        self.assertEqual("completed with evidence", completed.notes["completion_summary"])
        self.assertIn("mission_start_receipt_seq", completed.notes)

    def test_store_mark_completed_rejects_completed_failed_superseded_and_missing(self) -> None:
        self.store.create_mission(
            session_id="s1",
            task_id="completed-task",
            goal="goal",
            completion_criteria=["tests pass"],
            scope_boundary="",
            red_lines=[],
            slice_budget=3,
            retry_budget=2,
            notes={"marker": "completed"},
        )
        self.store.mark_completed("s1", "completed-task")

        terminal_statuses = [
            ("completed-task", "completed"),
            ("failed-task", "failed"),
            ("superseded-task", "superseded"),
        ]
        for task_id, status in terminal_statuses[1:]:
            self.store.create_mission(
                session_id="s1",
                task_id=task_id,
                goal="goal",
                completion_criteria=["tests pass"],
                scope_boundary="",
                red_lines=[],
                slice_budget=3,
                retry_budget=2,
                notes={"marker": status},
            )
            with closing(sqlite3.connect(self.db_path)) as conn, conn:
                conn.execute(
                    "UPDATE missions SET status=? WHERE session_id=? AND task_id=?",
                    (status, "s1", task_id),
                )

        for task_id, status in terminal_statuses:
            with self.subTest(status=status):
                with self.assertRaisesRegex(ValueError, status):
                    self.store.mark_completed("s1", task_id, notes={"attempted": "overwrite"})

                preserved = self.store.get_mission("s1", task_id)
                self.assertEqual(status, preserved.status)
                self.assertEqual(status, preserved.notes["marker"])
                self.assertNotIn("attempted", preserved.notes)

        with self.assertRaisesRegex(KeyError, "Unknown mission"):
            self.store.mark_completed("s1", "missing-task")

    def test_completion_gate_preserves_nested_existing_notes_and_epoch(self) -> None:
        self.server.mission_lock("s1", "completion-nested-notes", "goal", ["tests pass"])
        notes = dict(self.store.get_mission("s1", "completion-nested-notes").notes)
        start_seq = notes["mission_start_receipt_seq"]
        notes["audit"] = {
            "rounds_required": 2,
            "accepted_points": ["preserve nested notes"],
        }
        notes["custom"] = "keep"
        self.store.update_mission_notes("s1", "completion-nested-notes", notes)
        receipt = self.make_bash_receipt("s1", "completion-nested-notes", "pytest -q")
        self.approve_turn_for_receipt("s1", "completion-nested-notes", receipt.receipt_id)

        approved = self.server.completion_gate(
            session_id="s1",
            task_id="completion-nested-notes",
            criterion_receipt_map=[
                {"criterion": "tests pass", "receipt_ids": [receipt.receipt_id]}
            ],
            completion_summary="Mapped fresh test evidence while preserving existing mission notes.",
            known_risks=["host receipt capture remains adapter dependent"],
            unverified_items=["broader suite not part of this narrow row"],
        )

        completed = self.store.get_mission("s1", "completion-nested-notes")
        self.assertIn("APPROVED", approved)
        self.assertEqual("completed", completed.status)
        self.assertEqual(start_seq, completed.notes["mission_start_receipt_seq"])
        self.assertEqual("keep", completed.notes["custom"])
        self.assertEqual(
            {
                "rounds_required": 2,
                "accepted_points": ["preserve nested notes"],
            },
            completed.notes["audit"],
        )
        self.assertEqual(
            [{"criterion": "tests pass", "receipt_ids": [receipt.receipt_id]}],
            completed.notes["criterion_receipt_map"],
        )
        self.assertEqual(
            ["host receipt capture remains adapter dependent"],
            completed.notes["known_risks"],
        )
        self.assertEqual(
            ["broader suite not part of this narrow row"],
            completed.notes["unverified_items"],
        )

    def test_rejected_completion_gate_does_not_write_completion_notes(self) -> None:
        self.server.mission_lock(
            "s1",
            "completion-rejected-notes",
            "goal",
            ["tests pass", "lint passes"],
        )
        notes = dict(self.store.get_mission("s1", "completion-rejected-notes").notes)
        notes["audit"] = {"status": "must-survive-rejection"}
        self.store.update_mission_notes("s1", "completion-rejected-notes", notes)
        receipt = self.make_bash_receipt("s1", "completion-rejected-notes", "pytest -q")

        rejected = self.server.completion_gate(
            session_id="s1",
            task_id="completion-rejected-notes",
            criterion_receipt_map=[
                {"criterion": "tests pass", "receipt_ids": [receipt.receipt_id]}
            ],
            completion_summary="Attempted completion while lint evidence was still missing.",
        )

        mission = self.store.get_mission("s1", "completion-rejected-notes")
        self.assertIn("REJECTED", rejected)
        self.assertEqual("active", mission.status)
        self.assertEqual({"status": "must-survive-rejection"}, mission.notes["audit"])
        self.assertNotIn("completion_summary", mission.notes)
        self.assertNotIn("criterion_receipt_map", mission.notes)

    def test_mission_lock_rejects_reusing_completed_task_id(self) -> None:
        self.server.mission_lock("s1", "completed-task", "initial goal", ["tests pass"])
        receipt = self.make_bash_receipt("s1", "completed-task", "pytest -q")
        self.approve_turn_for_receipt("s1", "completed-task", receipt.receipt_id)
        self.server.completion_gate(
            session_id="s1",
            task_id="completed-task",
            criterion_receipt_map=[
                {"criterion": "tests pass", "receipt_ids": [receipt.receipt_id]}
            ],
            completion_summary="Completed the first mission using a fresh test receipt.",
        )

        with self.assertRaisesRegex(ValueError, "reusing an existing mission"):
            self.server.mission_lock(
                "s1", "completed-task", "new goal", ["new criterion"]
            )

    def test_create_mission_rejects_reusing_terminal_task_ids(self) -> None:
        session_id = "s1"
        terminal_cases = [
            (
                "completed-task",
                "completed",
                {"existing": "completed", "completion_source": "test"},
            ),
            (
                "failed-task",
                "failed",
                {"existing": "failed", "failure_reason": "integration error"},
            ),
            (
                "abandoned-task",
                "abandoned",
                {"existing": "abandoned", "abandon_reason": "scope stop"},
            ),
        ]

        for task_id, status, notes in terminal_cases:
            with self.subTest(status=status):
                original = self.store.create_mission(
                    session_id=session_id,
                    task_id=task_id,
                    goal="goal",
                    completion_criteria=["tests pass"],
                    scope_boundary="",
                    red_lines=[],
                    slice_budget=3,
                    retry_budget=2,
                    notes=notes,
                )
                with closing(sqlite3.connect(self.db_path)) as conn, conn:
                    conn.execute(
                        "UPDATE missions SET status=? WHERE session_id=? AND task_id=?",
                        (status, session_id, task_id),
                    )

                with self.assertRaisesRegex(ValueError, "reusing an existing mission task_id"):
                    self.store.create_mission(
                        session_id=session_id,
                        task_id=task_id,
                        goal="new goal",
                        completion_criteria=["new criterion"],
                        scope_boundary="new boundary",
                        red_lines=["new red line"],
                        slice_budget=5,
                        retry_budget=4,
                        notes={"attempted": "overwrite"},
                    )

                preserved = self.store.get_mission(session_id, task_id)
                self.assertEqual(status, preserved.status)
                self.assertEqual("goal", preserved.goal)
                self.assertEqual(["tests pass"], preserved.completion_criteria)
                self.assertEqual("", preserved.scope_boundary)
                self.assertEqual([], preserved.red_lines)
                self.assertEqual(3, preserved.slice_budget)
                self.assertEqual(2, preserved.retry_budget)
                for key, value in notes.items():
                    self.assertEqual(value, preserved.notes[key])
                self.assertEqual(original.notes, preserved.notes)
                self.assertNotIn("attempted", preserved.notes)
                with closing(sqlite3.connect(self.db_path)) as conn:
                    row_count = conn.execute(
                        "SELECT COUNT(*) FROM missions WHERE session_id=? AND task_id=?",
                        (session_id, task_id),
                    ).fetchone()[0]
                self.assertEqual(1, row_count)

    def test_create_mission_allows_new_task_id_after_completed_mission(self) -> None:
        self.server.mission_lock("s1", "completed-original", "initial goal", ["tests pass"])
        receipt = self.make_bash_receipt("s1", "completed-original", "pytest -q")
        self.approve_turn_for_receipt("s1", "completed-original", receipt.receipt_id)
        self.server.completion_gate(
            session_id="s1",
            task_id="completed-original",
            criterion_receipt_map=[
                {"criterion": "tests pass", "receipt_ids": [receipt.receipt_id]}
            ],
            completion_summary="Completed the original mission using fresh test evidence.",
        )

        created = self.store.create_mission(
            session_id="s1",
            task_id="completed-followup",
            goal="new goal",
            completion_criteria=["new criterion"],
            scope_boundary="new boundary",
            red_lines=[],
            slice_budget=4,
            retry_budget=2,
        )

        original = self.store.get_mission("s1", "completed-original")
        self.assertEqual("completed", original.status)
        self.assertEqual("active", created.status)
        self.assertEqual("completed-followup", created.task_id)


    def test_turn_end_gate_rejects_old_receipt_for_active_mission(self) -> None:
        old_receipt = self.make_bash_receipt("s1", "epoch-task", "pytest -q")
        self.server.mission_lock("s1", "epoch-task", "initial goal", ["tests pass"])
        rejected = self.server.turn_end_gate(
            session_id="s1",
            task_id="epoch-task",
            stop_condition="slice_verified",
            work_summary="Tried to close the active mission using old evidence.",
            receipt_ids=[old_receipt.receipt_id],
        )
        self.assertIn("REJECTED", rejected)
        self.assertIn("stale receipt", rejected.lower())

    def test_completion_gate_rejects_old_receipt_for_active_mission(self) -> None:
        old_receipt = self.make_bash_receipt("s1", "epoch-complete", "pytest -q")
        self.server.mission_lock("s1", "epoch-complete", "initial goal", ["tests pass"])
        rejected = self.server.completion_gate(
            session_id="s1",
            task_id="epoch-complete",
            criterion_receipt_map=[
                {"criterion": "tests pass", "receipt_ids": [old_receipt.receipt_id]}
            ],
            completion_summary="Tried to complete the active mission using old test evidence.",
        )
        self.assertIn("REJECTED", rejected)
        self.assertIn("stale receipt", rejected.lower())

    def test_completion_gate_accepts_new_receipt_on_active_mission(self) -> None:
        self.server.mission_lock("s1", "epoch-fresh", "initial goal", ["tests pass"])
        fresh_receipt = self.make_bash_receipt("s1", "epoch-fresh", "pytest -q")
        self.approve_turn_for_receipt("s1", "epoch-fresh", fresh_receipt.receipt_id)
        approved = self.server.completion_gate(
            session_id="s1",
            task_id="epoch-fresh",
            criterion_receipt_map=[
                {"criterion": "tests pass", "receipt_ids": [fresh_receipt.receipt_id]}
            ],
            completion_summary="Ran the verification command on the active mission and mapped it to the criterion.",
        )
        self.assertIn("APPROVED", approved)

    def test_completion_gate_rejects_receipt_reuse_across_criteria(self) -> None:
        self.server.mission_lock("s1", "reuse-task", "goal", ["c1", "c2"])
        receipt = self.make_bash_receipt("s1", "reuse-task", "pytest -q")
        with self.assertRaisesRegex(ValueError, "may not be reused across multiple criteria"):
            self.server.completion_gate(
                session_id="s1",
                task_id="reuse-task",
                criterion_receipt_map=[
                    {"criterion": "c1", "receipt_ids": [receipt.receipt_id]},
                    {"criterion": "c2", "receipt_ids": [receipt.receipt_id]},
                ],
                completion_summary="Attempted to reuse one receipt for two distinct criteria.",
            )

    def test_soft_stop_loop_is_limited(self) -> None:
        self.server.mission_lock("s1", "soft-stop-task", "goal", ["criterion"])
        receipt = self.make_bash_receipt("s1", "soft-stop-task", "pytest -q")
        for i in range(2):
            approved = self.server.turn_end_gate(
                session_id="s1",
                task_id="soft-stop-task",
                stop_condition="user_information_required",
                work_summary=f"Need user input for step {i} before proceeding with the next bounded action.",
                receipt_ids=[receipt.receipt_id],
                reason_for_stopping="Need clarification before the next step.",
            )
            self.assertIn("APPROVED", approved)
        rejected = self.server.turn_end_gate(
            session_id="s1",
            task_id="soft-stop-task",
            stop_condition="user_information_required",
            work_summary="Need user input again after already pausing twice without new work.",
            receipt_ids=[receipt.receipt_id],
            reason_for_stopping="Need clarification before the next step.",
        )
        self.assertIn("REJECTED", rejected)

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
        self.approve_turn_for_receipt("s1", "opencode-task", receipt.receipt_id)
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
