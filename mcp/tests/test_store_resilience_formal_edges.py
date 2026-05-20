from __future__ import annotations

import gc
import importlib
import os
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path


class StoreResilienceFormalEdgeTests(unittest.TestCase):
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
        self.store_module = importlib.import_module("agent_runway_runtime.store")
        self.store_module = importlib.reload(self.store_module)

    def tearDown(self) -> None:
        gc.collect()
        for _ in range(5):
            try:
                self.temp_dir.cleanup()
                break
            except PermissionError:
                gc.collect()
                time.sleep(0.05)
        os.environ.pop("ILH_DB_PATH", None)
        os.environ.pop("ILH_SECRET_PATH", None)

    def test_runtime_store_raises_on_corrupted_sqlite_header(self) -> None:
        self.db_path.write_bytes(b"not-a-sqlite-file\x00\x01garbage")

        with self.assertRaises(sqlite3.DatabaseError):
            self.store_module.RuntimeStore(db_path=str(self.db_path), secret="x" * 64)

    def test_get_receipts_returns_empty_for_empty_ids(self) -> None:
        store = self.store_module.RuntimeStore(db_path=str(self.db_path), secret="x" * 64)

        self.assertEqual(store.get_receipts([], session_id="s1"), [])

    def test_get_receipts_deduplicates_input_ids(self) -> None:
        store = self.store_module.RuntimeStore(db_path=str(self.db_path), secret="x" * 64)
        store.ensure_session("s1")
        receipt = store.record_receipt(
            session_id="s1",
            task_id="t1",
            source="test",
            tool_name="Bash",
            command_text="pytest",
            exit_code=0,
            metadata={},
        )

        rows = store.get_receipts([receipt.receipt_id, receipt.receipt_id], session_id="s1")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].receipt_id, receipt.receipt_id)

    def test_get_receipts_distinguishes_omitted_task_id_explicit_none_and_explicit_task(self) -> None:
        store = self.store_module.RuntimeStore(db_path=str(self.db_path), secret="x" * 64)
        store.ensure_session("s1")
        store.ensure_session("s2")
        taskless = store.record_receipt(
            session_id="s1",
            task_id=None,
            source="test",
            tool_name="Bash",
            command_text="pytest taskless",
            exit_code=0,
            metadata={"stdout_sha256": "taskless"},
        )
        task_a = store.record_receipt(
            session_id="s1",
            task_id="task-a",
            source="test",
            tool_name="Bash",
            command_text="pytest task-a",
            exit_code=0,
            metadata={"stdout_sha256": "task-a"},
        )
        task_b = store.record_receipt(
            session_id="s1",
            task_id="task-b",
            source="test",
            tool_name="Bash",
            command_text="pytest task-b",
            exit_code=0,
            metadata={"stdout_sha256": "task-b"},
        )
        other_session = store.record_receipt(
            session_id="s2",
            task_id="task-a",
            source="test",
            tool_name="Bash",
            command_text="pytest other-session",
            exit_code=0,
            metadata={"stdout_sha256": "other-session"},
        )
        receipt_ids = [
            taskless.receipt_id,
            task_a.receipt_id,
            task_b.receipt_id,
            other_session.receipt_id,
        ]

        omitted = store.get_receipts(receipt_ids, session_id="s1")
        explicit_none = store.get_receipts(receipt_ids, session_id="s1", task_id=None)
        explicit_task = store.get_receipts(receipt_ids, session_id="s1", task_id="task-a")
        explicit_empty_task = store.get_receipts(receipt_ids, session_id="s1", task_id="")

        self.assertEqual(
            {row.receipt_id for row in omitted},
            {taskless.receipt_id, task_a.receipt_id, task_b.receipt_id},
        )
        self.assertEqual([row.receipt_id for row in explicit_none], [taskless.receipt_id])
        self.assertEqual([row.receipt_id for row in explicit_task], [task_a.receipt_id])
        self.assertEqual(explicit_empty_task, [])

    def test_mark_completed_returns_completed_mission_and_merges_notes(self) -> None:
        store = self.store_module.RuntimeStore(db_path=str(self.db_path), secret="x" * 64)
        store.create_mission(
            session_id="s1",
            task_id="complete-task",
            goal="goal",
            completion_criteria=["criterion"],
            scope_boundary="",
            red_lines=[],
            slice_budget=3,
            retry_budget=2,
            notes={"old": "replace"},
        )

        completed = store.mark_completed("s1", "complete-task", notes={"new": "kept"})

        self.assertEqual("completed", completed.status)
        self.assertIsNotNone(completed.completed_at)
        self.assertEqual("replace", completed.notes["old"])
        self.assertEqual("kept", completed.notes["new"])
        self.assertIn("mission_start_receipt_seq", completed.notes)

    def test_mark_completed_without_notes_preserves_existing_notes(self) -> None:
        store = self.store_module.RuntimeStore(db_path=str(self.db_path), secret="x" * 64)
        store.create_mission(
            session_id="s1",
            task_id="complete-task",
            goal="goal",
            completion_criteria=["criterion"],
            scope_boundary="",
            red_lines=[],
            slice_budget=3,
            retry_budget=2,
            notes={"old": "keep"},
        )

        completed = store.mark_completed("s1", "complete-task")

        self.assertEqual("completed", completed.status)
        self.assertEqual("keep", completed.notes["old"])
        self.assertIn("mission_start_receipt_seq", completed.notes)

    def test_mark_completed_missing_mission_raises_instead_of_returning_none(self) -> None:
        store = self.store_module.RuntimeStore(db_path=str(self.db_path), secret="x" * 64)

        with self.assertRaisesRegex(KeyError, "Unknown mission"):
            store.mark_completed("s1", "missing-task")

    def test_mark_completed_rejects_non_active_mission_without_overwriting_notes(self) -> None:
        store = self.store_module.RuntimeStore(db_path=str(self.db_path), secret="x" * 64)
        store.create_mission(
            session_id="s1",
            task_id="failed-task",
            goal="goal",
            completion_criteria=["criterion"],
            scope_boundary="",
            red_lines=[],
            slice_budget=3,
            retry_budget=2,
            notes={"failure_reason": "child failed"},
        )
        with sqlite3.connect(self.db_path) as conn, conn:
            conn.execute(
                "UPDATE missions SET status=? WHERE session_id=? AND task_id=?",
                ("failed", "s1", "failed-task"),
            )

        with self.assertRaisesRegex(ValueError, "status 'failed'"):
            store.mark_completed("s1", "failed-task", notes={"completion_summary": "bad"})

        mission = store.get_mission("s1", "failed-task")
        self.assertEqual("failed", mission.status)
        self.assertEqual("child failed", mission.notes["failure_reason"])
        self.assertNotIn("completion_summary", mission.notes)

    def test_stop_subagent_span_uses_immediate_transaction_before_status_read(self) -> None:
        source = Path(self.store_module.__file__).read_text(encoding="utf-8")
        start = source.index("    def stop_subagent_span(")
        end = source.index("    def record_subagent_handoff(", start)
        body = source[start:end]

        begin_index = body.index('conn.execute("BEGIN IMMEDIATE")')
        status_read_index = body.index("SELECT status FROM subagent_spans")
        self.assertLess(begin_index, status_read_index)

    def test_increment_slice_returns_updated_mission(self) -> None:
        store = self.store_module.RuntimeStore(db_path=str(self.db_path), secret="x" * 64)
        store.create_mission(
            session_id="s1",
            task_id="slice-task",
            goal="goal",
            completion_criteria=["criterion"],
            scope_boundary="",
            red_lines=[],
            slice_budget=3,
            retry_budget=2,
        )

        updated = store.increment_slice("s1", "slice-task")

        self.assertEqual(1, updated.slice_count)
        self.assertEqual("active", updated.status)
        updated_again = store.increment_slice("s1", "slice-task")
        self.assertEqual(2, updated_again.slice_count)
        self.assertEqual("active", updated_again.status)

    def test_increment_slice_missing_mission_raises_instead_of_returning_none(self) -> None:
        store = self.store_module.RuntimeStore(db_path=str(self.db_path), secret="x" * 64)

        with self.assertRaisesRegex(KeyError, "Unknown mission"):
            store.increment_slice("s1", "missing-task")

    def test_list_subagent_handoffs_raises_on_invalid_json_payload(self) -> None:
        store = self.store_module.RuntimeStore(db_path=str(self.db_path), secret="x" * 64)
        store.ensure_session("s1")
        store.create_mission("s1", "t1", "goal", ["criterion"], "", [], 24, 3)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO subagent_handoffs(
                    child_span_id, session_id, task_id, summary, verified_claims,
                    receipt_ids, risks, unverified_items, created_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "child-1",
                    "s1",
                    "t1",
                    "summary",
                    "{bad-json",
                    "[]",
                    "[]",
                    "[]",
                    "2026-01-01T00:00:00Z",
                ),
            )
        store = None
        gc.collect()

        reread = self.store_module.RuntimeStore(db_path=str(self.db_path), secret="x" * 64)

        with self.assertRaises(ValueError):
            reread.list_subagent_handoffs("s1", "t1")
        reread = None
        gc.collect()

    def test_list_subagent_spans_raises_on_invalid_json_payload(self) -> None:
        store = self.store_module.RuntimeStore(db_path=str(self.db_path), secret="x" * 64)
        store.ensure_session("s1")
        store.create_mission("s1", "t1", "goal", ["criterion"], "", [], 24, 3)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO subagent_spans(
                    child_span_id, session_id, task_id, host, subagent_type, host_child_id,
                    context_mode, workspace_kind, status, delegated_scope, delegated_budget,
                    budget_consumed, started_at, ended_at, transcript_ref, artifact_refs,
                    last_message, parent_receipt_seq, terminal_receipt_seq
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "child-1",
                    "s1",
                    "t1",
                    "host",
                    "reviewer",
                    "",
                    "fresh",
                    "shared_checkout",
                    "running",
                    "scope",
                    "{bad-json",
                    "{}",
                    "2026-01-01T00:00:00Z",
                    None,
                    "",
                    "[]",
                    "",
                    0,
                    0,
                ),
            )
        store = None
        gc.collect()

        reread = self.store_module.RuntimeStore(db_path=str(self.db_path), secret="x" * 64)

        with self.assertRaises(ValueError):
            reread.list_subagent_spans("s1", "t1")
        reread = None
        gc.collect()


if __name__ == "__main__":
    unittest.main()
