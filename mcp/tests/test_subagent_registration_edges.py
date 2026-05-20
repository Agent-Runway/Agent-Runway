from __future__ import annotations

import importlib
import json
import os
import sqlite3
import sys
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path


MCP_ROOT = Path(__file__).resolve().parents[1]
if str(MCP_ROOT) not in sys.path:
    sys.path.insert(0, str(MCP_ROOT))


class SubagentRegistrationEdgesTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self._old_env = {
            key: os.environ.get(key)
            for key in ("ILH_DB_PATH", "ILH_SECRET_PATH", "ILH_HARNESS_SECRET")
        }
        os.environ["ILH_DB_PATH"] = str(Path(self.temp_dir.name) / "state.db")
        os.environ["ILH_SECRET_PATH"] = str(Path(self.temp_dir.name) / "secret.key")
        os.environ["ILH_HARNESS_SECRET"] = "a" * 64
        self.server = importlib.reload(importlib.import_module("server"))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()
        for key, value in self._old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def lock_parent(self) -> None:
        self.server.mission_lock("s1", "parent", "goal", ["tests pass"])

    def start_child(self, host_child_id: str, host: str = "test") -> dict:
        return json.loads(
            self.server.register_subagent_start(
                session_id="s1",
                task_id="parent",
                subagent_type="reviewer",
                delegated_scope="review only",
                delegated_budget={},
                host=host,
                host_child_id=host_child_id,
            )
        )

    def test_rejects_duplicate_non_empty_host_child_id_for_same_mission(self) -> None:
        self.lock_parent()
        first = self.start_child("host-child-1")

        with self.assertRaisesRegex(ValueError, "host_child_id"):
            self.start_child("host-child-1")

        spans = self.server.store.list_subagent_spans("s1", "parent")
        self.assertEqual(1, len(spans))
        self.assertEqual(first["child_span_id"], spans[0].child_span_id)

    def test_allows_blank_host_child_id_for_multiple_children(self) -> None:
        self.lock_parent()

        first = self.start_child("")
        second = self.start_child("")

        self.assertNotEqual(first["child_span_id"], second["child_span_id"])

    def test_treats_invisible_only_host_child_id_as_blank(self) -> None:
        self.lock_parent()

        first = self.start_child("\u200b")
        second = self.start_child("\x00")

        self.assertEqual("", first["host_child_id"])
        self.assertEqual("", second["host_child_id"])
        self.assertNotEqual(first["child_span_id"], second["child_span_id"])

    def test_rejects_invisible_only_subagent_type_and_delegated_scope(self) -> None:
        self.lock_parent()

        with self.assertRaisesRegex(ValueError, "subagent_type must not be empty"):
            self.server.register_subagent_start(
                "s1", "parent", "\u200b", "review only", {}
            )
        with self.assertRaisesRegex(ValueError, "delegated_scope must not be empty"):
            self.server.register_subagent_start(
                "s1", "parent", "reviewer", "\x00", {}
            )
        self.assertEqual([], self.server.store.list_subagent_spans("s1", "parent"))

    def test_allows_same_host_child_id_from_different_hosts(self) -> None:
        self.lock_parent()

        first = self.start_child("host-child-1", host="host-a")
        second = self.start_child("host-child-1", host="host-b")

        self.assertNotEqual(first["child_span_id"], second["child_span_id"])

    def test_allows_same_host_child_id_for_different_missions(self) -> None:
        self.server.mission_lock("s1", "parent-a", "goal", ["tests pass"])
        self.server.mission_lock("s1", "parent-b", "goal", ["tests pass"])

        first = json.loads(
            self.server.register_subagent_start(
                session_id="s1",
                task_id="parent-a",
                subagent_type="reviewer",
                delegated_scope="review only",
                delegated_budget={},
                host="test",
                host_child_id="host-child-1",
            )
        )
        second = json.loads(
            self.server.register_subagent_start(
                session_id="s1",
                task_id="parent-b",
                subagent_type="reviewer",
                delegated_scope="review only",
                delegated_budget={},
                host="test",
                host_child_id="host-child-1",
            )
        )

        self.assertNotEqual(first["child_span_id"], second["child_span_id"])
        self.assertEqual(1, len(self.server.store.list_subagent_spans("s1", "parent-a")))
        self.assertEqual(1, len(self.server.store.list_subagent_spans("s1", "parent-b")))

    def test_rejects_more_than_max_running_subagents_for_one_mission(self) -> None:
        self.lock_parent()

        for index in range(self.server.MAX_RUNNING_SUBAGENTS_PER_MISSION):
            child = self.server.register_subagent_start(
                session_id="s1",
                task_id="parent",
                subagent_type="reviewer",
                delegated_scope=f"review slice {index}",
                delegated_budget={},
            )
            self.assertIn("child_span_id", child)

        with self.assertRaisesRegex(ValueError, "running subagent"):
            self.server.register_subagent_start(
                session_id="s1",
                task_id="parent",
                subagent_type="reviewer",
                delegated_scope="review overflow",
                delegated_budget={},
            )

    def test_concurrent_same_host_child_id_registration_has_single_winner(self) -> None:
        self.lock_parent()
        successes = []
        errors: list[Exception] = []
        result_lock = threading.Lock()
        start = threading.Barrier(10)

        def worker() -> None:
            try:
                start.wait()
                child = self.start_child("host-child-race", host="test")
                with result_lock:
                    successes.append(child)
            except Exception as exc:
                with result_lock:
                    errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(1, len(successes))
        self.assertEqual(9, len(errors))
        self.assertTrue(all("host_child_id" in str(exc) for exc in errors))
        spans = self.server.store.list_subagent_spans("s1", "parent")
        self.assertEqual(1, len(spans))
        self.assertEqual(successes[0]["child_span_id"], spans[0].child_span_id)

    def test_handoff_and_stop_reject_blank_child_span_id_before_lookup(self) -> None:
        self.lock_parent()
        child = self.start_child("host-child-1")
        receipt = self.server.store.record_receipt(
            session_id="s1",
            task_id="parent",
            source="test",
            tool_name="Bash",
            command_text="pytest -q",
            exit_code=0,
            metadata={"stdout_sha256": "abc", "child_span_id": child["child_span_id"]},
        )

        with self.assertRaisesRegex(ValueError, "child_span_id must not be empty"):
            self.server.record_subagent_handoff(
                "s1",
                "parent",
                " ",
                "Collected concrete child evidence for this delegated task.",
                [],
                [receipt.receipt_id],
            )
        with self.assertRaisesRegex(ValueError, "child_span_id must not be empty"):
            self.server.register_subagent_stop("s1", "parent", "\t", "completed")
        with self.assertRaisesRegex(ValueError, "child_span_id must not be empty"):
            self.server.register_subagent_stop("s1", "parent", "\u200b", "completed")

        span = self.server.store.get_subagent_span("s1", "parent", child["child_span_id"])
        self.assertEqual("running", span.status)
        self.assertEqual(
            [],
            self.server.store.list_subagent_handoffs(
                "s1", "parent", child["child_span_id"]
            ),
        )

    def test_schema_has_partial_unique_index_for_non_empty_host_child_id(self) -> None:
        with closing(sqlite3.connect(os.environ["ILH_DB_PATH"])) as conn:
            indexes = conn.execute("PRAGMA index_list(subagent_spans)").fetchall()
            index_sql = conn.execute(
                """
                SELECT sql FROM sqlite_master
                WHERE type='index' AND name='idx_subagent_spans_host_child_unique'
                """
            ).fetchone()[0]

        unique_indexes = {row[1]: row[2] for row in indexes}
        self.assertEqual(1, unique_indexes["idx_subagent_spans_host_child_unique"])
        self.assertIn("session_id, task_id, host, host_child_id", index_sql)
        self.assertIn("WHERE host_child_id<>''", index_sql)

    def test_rejects_delegated_slices_above_parent_remaining_budget(self) -> None:
        self.server.mission_lock("s1", "parent", "goal", ["tests pass"], slice_budget=3)
        receipt = self.server.store.record_receipt(
            session_id="s1",
            task_id="parent",
            source="test",
            tool_name="Bash",
            command_text="pytest -q",
            exit_code=0,
            metadata={"stdout_sha256": "abc"},
        )
        self.server.turn_end_gate(
            "s1",
            "parent",
            "slice_verified",
            "Completed one verified slice before attempting to delegate more slices than remain.",
            [receipt.receipt_id],
        )

        with self.assertRaisesRegex(ValueError, "max_slices"):
            self.server.register_subagent_start(
                session_id="s1",
                task_id="parent",
                subagent_type="reviewer",
                delegated_scope="review only",
                delegated_budget={"max_slices": 3},
            )

    def test_rejects_negative_and_non_numeric_delegated_budget_values(self) -> None:
        self.lock_parent()
        cases = [
            {"max_slices": -1},
            {"max_slices": True},
            {"max_tool_calls": "five"},
            {"max_tool_calls": False},
            {"max_elapsed_seconds": 0},
            {"max_elapsed_seconds": True},
        ]
        for delegated_budget in cases:
            with self.subTest(delegated_budget=delegated_budget):
                with self.assertRaisesRegex(ValueError, "delegated_budget"):
                    self.server.register_subagent_start(
                        session_id="s1",
                        task_id="parent",
                        subagent_type="reviewer",
                        delegated_scope="review only",
                        delegated_budget=delegated_budget,
                    )

    def test_rejects_delegated_elapsed_seconds_above_parent_remaining_time_budget(self) -> None:
        self.server.mission_lock(
            "s1", "parent", "goal", ["tests pass"], time_budget_minutes=1
        )

        with self.assertRaisesRegex(ValueError, "max_elapsed_seconds"):
            self.server.register_subagent_start(
                session_id="s1",
                task_id="parent",
                subagent_type="reviewer",
                delegated_scope="review only",
                delegated_budget={"max_elapsed_seconds": 61},
            )

    def test_rejects_delegated_elapsed_seconds_above_default_when_parent_has_no_time_budget(self) -> None:
        self.server.mission_lock("s1", "parent", "goal", ["tests pass"])

        with self.assertRaisesRegex(ValueError, "max_elapsed_seconds.*default"):
            self.server.register_subagent_start(
                session_id="s1",
                task_id="parent",
                subagent_type="reviewer",
                delegated_scope="review only",
                delegated_budget={"max_elapsed_seconds": 3601},
            )

    def test_rejects_delegated_tool_calls_above_parent_slice_budget_ceiling(self) -> None:
        self.server.mission_lock("s1", "parent", "goal", ["tests pass"], slice_budget=2)

        with self.assertRaisesRegex(ValueError, "max_tool_calls"):
            self.server.register_subagent_start(
                session_id="s1",
                task_id="parent",
                subagent_type="reviewer",
                delegated_scope="review only",
                delegated_budget={"max_tool_calls": 99999},
            )

    def test_allows_delegated_tool_calls_within_parent_slice_budget_ceiling(self) -> None:
        self.server.mission_lock("s1", "parent", "goal", ["tests pass"], slice_budget=2)

        child = json.loads(
            self.server.register_subagent_start(
                session_id="s1",
                task_id="parent",
                subagent_type="reviewer",
                delegated_scope="review only",
                delegated_budget={"max_tool_calls": 20},
            )
        )

        self.assertEqual(20, child["delegated_budget"]["max_tool_calls"])


if __name__ == "__main__":
    unittest.main()
