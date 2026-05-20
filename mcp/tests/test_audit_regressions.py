from __future__ import annotations

import importlib
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path


class AuditRegressionTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "state.db"
        self.secret_path = Path(self.temp_dir.name) / "secret.key"
        os.environ["ILH_DB_PATH"] = str(self.db_path)
        os.environ["ILH_SECRET_PATH"] = str(self.secret_path)

        repo_root = Path(__file__).resolve().parents[2]
        for path in (repo_root / "mcp", repo_root / "scripts"):
            if str(path) not in sys.path:
                sys.path.insert(0, str(path))
        self.server = importlib.import_module("server")
        self.server = importlib.reload(self.server)
        self.hooks = importlib.import_module("claude_hooks")
        self.hooks = importlib.reload(self.hooks)
        self.store = self.server.store

    def tearDown(self) -> None:
        self.temp_dir.cleanup()
        os.environ.pop("ILH_DB_PATH", None)
        os.environ.pop("ILH_SECRET_PATH", None)

    def make_receipt(
        self,
        session_id: str,
        task_id: str,
        tool_name: str = "Bash",
        command_text: str = "pytest -q",
        exit_code: int = 0,
    ):
        return self.store.record_receipt(
            session_id=session_id,
            task_id=task_id,
            source="audit-regression",
            tool_name=tool_name,
            command_text=command_text,
            exit_code=exit_code,
            metadata={"stdout_sha256": "audit"},
        )

    def approve_verified_slice(self, session_id: str, task_id: str, receipt_id: str) -> None:
        approved = self.server.turn_end_gate(
            session_id=session_id,
            task_id=task_id,
            stop_condition="slice_verified",
            work_summary="Recorded a verified slice before testing completion behavior.",
            receipt_ids=[receipt_id],
        )
        self.assertIn("APPROVED", approved)

    def test_hooks_deny_state_db_reads_from_read_and_shell_tools(self) -> None:
        cases = [
            ("Read", {"file_path": str(self.db_path)}),
            ("Bash", {"command": f"cat {self.db_path}"}),
        ]
        for tool_name, tool_input in cases:
            with self.subTest(tool_name=tool_name):
                decision = self.hooks.pre_tool_use_decision(tool_name, tool_input)
                self.assertIsNotNone(decision)
                self.assertEqual(decision["permissionDecision"], "deny")

    def test_completion_gate_requires_execution_for_chinese_verify(self) -> None:
        criterion = "验证模型精度"
        self.server.mission_lock("s1", "cn-verify", "goal", [criterion])
        receipt = self.make_receipt("s1", "cn-verify", "Read", "metrics.md")
        self.approve_verified_slice("s1", "cn-verify", receipt.receipt_id)
        rejected = self.server.completion_gate(
            "s1",
            "cn-verify",
            [{"criterion": criterion, "receipt_ids": [receipt.receipt_id]}],
            "Mapped a Chinese verification criterion to a read receipt for audit.",
        )
        self.assertIn("REJECTED", rejected)
        self.assertIn("semantic", rejected.lower())

    def test_completion_gate_requires_mutation_for_chinese_mutation_verbs(self) -> None:
        cases = [
            ("cn-delete", "删除废弃模块"),
            ("cn-refactor", "重构认证模块"),
            ("cn-create", "创建配置文件"),
            ("cn-add", "新增配置项"),
            ("cn-remove", "移除废弃文件"),
        ]
        for task_id, criterion in cases:
            with self.subTest(criterion=criterion):
                self.server.mission_lock("s1", task_id, "goal", [criterion])
                receipt = self.make_receipt("s1", task_id, "Read", "notes.md")
                self.approve_verified_slice("s1", task_id, receipt.receipt_id)
                rejected = self.server.completion_gate(
                    "s1",
                    task_id,
                    [{"criterion": criterion, "receipt_ids": [receipt.receipt_id]}],
                    "Mapped a Chinese mutation criterion to a read receipt for audit.",
                )
                self.assertIn("REJECTED", rejected)
                self.assertIn("semantic", rejected.lower())

    def test_assertion_language_rejects_should_be_enough_variants(self) -> None:
        cases = [
            ("en-enough", "Ran the required command and captured output; should be enough to stop now."),
            ("en-ok", "Ran the required command and captured output; should be ok to stop now."),
            ("cn-enough", "已经重跑测试并记录证据，应该够了可以结束。"),
            ("cn-close", "已经重跑测试并记录证据，应该差不多了可以结束。"),
        ]
        for task_id, summary in cases:
            with self.subTest(summary=summary):
                self.server.mission_lock("s1", task_id, "goal", ["criterion"])
                receipt = self.make_receipt("s1", task_id)
                rejected = self.server.turn_end_gate(
                    session_id="s1",
                    task_id=task_id,
                    stop_condition="slice_verified",
                    work_summary=summary,
                    receipt_ids=[receipt.receipt_id],
                )
                self.assertIn("REJECTED", rejected)
                self.assertIn("assertion language", rejected)

    def test_sql_like_identifiers_are_treated_as_data(self) -> None:
        session_id = "s1'; DROP TABLE receipts;--"
        task_id = "t1'; DROP TABLE missions;--"
        self.server.mission_lock(session_id, task_id, "goal", ["tests pass"])
        receipt = self.make_receipt(session_id, task_id)
        self.approve_verified_slice(session_id, task_id, receipt.receipt_id)
        approved = self.server.completion_gate(
            session_id,
            task_id,
            [{"criterion": "tests pass", "receipt_ids": [receipt.receipt_id]}],
            "Mapped a receipt with SQL-like identifiers to verify parameterized storage.",
        )
        self.assertIn("APPROVED", approved)
        with closing(sqlite3.connect(self.db_path)) as conn:
            receipt_count = conn.execute("SELECT COUNT(*) FROM receipts").fetchone()[0]
            mission_count = conn.execute("SELECT COUNT(*) FROM missions").fetchone()[0]
        self.assertEqual(receipt_count, 1)
        self.assertEqual(mission_count, 1)

    def test_completion_gate_rejects_cross_session_receipt_injection(self) -> None:
        self.server.mission_lock("session-a", "shared", "goal a", ["tests pass"])
        self.server.mission_lock("session-b", "shared", "goal b", ["tests pass"])
        receipt = self.make_receipt("session-a", "shared")
        with self.assertRaisesRegex(ValueError, "belongs to session_id='session-a'"):
            self.server.completion_gate(
                "session-b",
                "shared",
                [{"criterion": "tests pass", "receipt_ids": [receipt.receipt_id]}],
                "Attempted to map another session's receipt into this mission.",
            )

    def test_completed_mission_rejects_later_state_transitions(self) -> None:
        self.server.mission_lock("s1", "done-task", "goal", ["tests pass"])
        receipt = self.make_receipt("s1", "done-task")
        self.approve_verified_slice("s1", "done-task", receipt.receipt_id)
        self.server.completion_gate(
            "s1",
            "done-task",
            [{"criterion": "tests pass", "receipt_ids": [receipt.receipt_id]}],
            "Completed the mission with a valid execution receipt.",
        )
        actions = [
            lambda: self.server.turn_end_gate(
                "s1",
                "done-task",
                "slice_verified",
                "Attempted to close an already completed mission.",
                [receipt.receipt_id],
            ),
            lambda: self.server.record_stuck_attempt(
                "s1", "done-task", "strategy", "late failure", [receipt.receipt_id]
            ),
            lambda: self.server.record_user_authorization(
                "s1", "done-task", "publish", "scope", "User approved."
            ),
            lambda: self.server.completion_gate(
                "s1",
                "done-task",
                [{"criterion": "tests pass", "receipt_ids": [receipt.receipt_id]}],
                "Attempted duplicate completion after the mission was completed.",
            ),
        ]
        for action in actions:
            with self.subTest(action=action):
                with self.assertRaisesRegex(ValueError, "No active mission"):
                    action()

    def test_boundary_value_errors_are_explicit(self) -> None:
        with self.assertRaisesRegex(ValueError, "goal must not be empty"):
            self.server.mission_lock("s1", "empty-goal", "   ", ["criterion"])
        with self.assertRaisesRegex(ValueError, "at least one"):
            self.server.mission_lock("s1", "empty-criteria", "goal", [])

        self.server.mission_lock("s1", "boundary-task", "goal", ["criterion"])
        receipt = self.make_receipt("s1", "boundary-task")
        with self.assertRaisesRegex(ValueError, "stop_condition must be one of"):
            self.server.turn_end_gate(
                "s1",
                "boundary-task",
                "not-a-stop-condition",
                "Attempted an invalid stop condition for audit.",
                [receipt.receipt_id],
            )
        with self.assertRaisesRegex(ValueError, "must not be empty"):
            self.server.record_user_authorization(
                "s1", "boundary-task", " ", "scope", "User approved."
            )

    def test_database_file_loss_is_exposed_without_fake_recovery(self) -> None:
        self.server.mission_lock("s1", "db-loss", "goal", ["criterion"])
        self.db_path.unlink()
        with self.assertRaises(sqlite3.OperationalError):
            self.store.list_recent_receipts("s1", "db-loss", 10)

    def test_corrupt_database_is_exposed_without_fake_recovery(self) -> None:
        self.server.mission_lock("s1", "db-corrupt", "goal", ["criterion"])
        self.db_path.write_bytes(b"not a sqlite database")
        with self.assertRaises(sqlite3.DatabaseError):
            self.store.list_recent_receipts("s1", "db-corrupt", 10)


if __name__ == "__main__":
    unittest.main()
