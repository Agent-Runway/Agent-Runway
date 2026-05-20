from __future__ import annotations

import importlib
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path


class FindBug0515FormalGapTestCase(unittest.TestCase):
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
        session_id: str,
        task_id: str,
        *,
        tool_name: str = "Read",
        command_text: str = "notes.md",
        source: str = "formal-gap-test",
        metadata: dict[str, object] | None = None,
    ):
        return self.store.record_receipt(
            session_id=session_id,
            task_id=task_id,
            source=source,
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
            work_summary="Mapped current evidence through turn_end_gate before completion.",
            receipt_ids=[receipt_id],
        )
        self.assertIn("APPROVED", approved)

    def test_completion_gate_rejects_fake_write_flag_as_mutation_evidence(self) -> None:
        cases = [("fake-write-true", "true --write"), ("fake-write-echo", "echo --write ok")]
        for task_id, command_text in cases:
            with self.subTest(command_text=command_text):
                self.server.mission_lock("s1", task_id, "goal", ["fix the bug"])
                receipt = self.make_receipt(
                    "s1", task_id, tool_name="Bash", command_text=command_text
                )
                self.approve_verified_slice(task_id, receipt.receipt_id)

                rejected = self.server.completion_gate(
                    session_id="s1",
                    task_id=task_id,
                    criterion_receipt_map=[
                        {"criterion": "fix the bug", "receipt_ids": [receipt.receipt_id]}
                    ],
                    completion_summary="Mapped a fake shell write flag to a fix criterion for mutation evidence hardening.",
                )

                self.assertIn("REJECTED", rejected)
                self.assertIn("semantic", rejected.lower())

    def test_completion_gate_rejects_read_only_receipts_for_common_work_verbs(self) -> None:
        cases = [
            ("fix", "fix the bug"),
            ("resolve", "resolve the incident"),
            ("implement", "implement the feature"),
            ("add", "add the option"),
            ("debug", "debug the failure"),
            ("ensure", "ensure the workflow passes"),
            ("confirm", "confirm the outcome"),
            ("create", "create the config file"),
            ("remove", "remove the legacy path"),
            ("delete", "delete the obsolete file"),
            ("refactor", "refactor the module"),
            ("deploy", "deploy the application"),
            ("migrate", "migrate the database"),
            ("improve", "improve the code"),
            ("validate", "validate the data"),
            ("optimize", "optimize the speed"),
            ("document", "document the API"),
            ("repair", "repair the integration"),
            ("configure", "configure the service"),
            ("patch", "patch the parser"),
            ("update", "update the documentation"),
            ("run", "run the regression tests"),
        ]
        for task_id, criterion in cases:
            with self.subTest(criterion=criterion):
                self.server.mission_lock("s1", task_id, "goal", [criterion])
                receipt = self.make_receipt("s1", task_id)
                self.approve_verified_slice(task_id, receipt.receipt_id)

                rejected = self.server.completion_gate(
                    session_id="s1",
                    task_id=task_id,
                    criterion_receipt_map=[{"criterion": criterion, "receipt_ids": [receipt.receipt_id]}],
                    completion_summary="Mapped a read-only receipt to a common work criterion for semantic hardening.",
                )

                self.assertIn("REJECTED", rejected)
                self.assertIn("semantic", rejected.lower())

    def test_completion_gate_accepts_matching_receipts_for_newly_covered_work_verbs(self) -> None:
        cases = [
            ("confirm", "confirm the outcome", "Bash", "python confirm_outcome.py"),
            ("create", "create the config file", "Edit", "config/app.toml"),
            ("remove", "remove the legacy path", "Edit", "src/legacy.py"),
            ("delete", "delete the obsolete file", "Edit", "src/obsolete.py"),
        ]
        for task_id, criterion, tool_name, command_text in cases:
            with self.subTest(criterion=criterion):
                self.server.mission_lock("s1", task_id, "goal", [criterion])
                receipt = self.make_receipt(
                    "s1",
                    task_id,
                    tool_name=tool_name,
                    command_text=command_text,
                    source="claude-hook" if tool_name == "Edit" else "formal-gap-test",
                )
                self.approve_verified_slice(task_id, receipt.receipt_id)

                approved = self.server.completion_gate(
                    session_id="s1",
                    task_id=task_id,
                    criterion_receipt_map=[{"criterion": criterion, "receipt_ids": [receipt.receipt_id]}],
                    completion_summary="Mapped the work criterion to a matching execution or mutation receipt.",
                )

                self.assertIn("APPROVED", approved)

    def test_completion_gate_rejects_mismatched_receipts_for_newly_covered_work_verbs(self) -> None:
        cases = [
            ("confirm-mutation-only", "confirm the outcome", "Edit", "reports/outcome.md"),
            ("create-execution-only", "create the config file", "Bash", "python inspect.py"),
            ("remove-execution-only", "remove the legacy path", "Bash", "python inspect.py"),
            ("delete-execution-only", "delete the obsolete file", "Bash", "python inspect.py"),
        ]
        for task_id, criterion, tool_name, command_text in cases:
            with self.subTest(criterion=criterion):
                self.server.mission_lock("s1", task_id, "goal", [criterion])
                receipt = self.make_receipt(
                    "s1", task_id, tool_name=tool_name, command_text=command_text
                )
                self.approve_verified_slice(task_id, receipt.receipt_id)

                rejected = self.server.completion_gate(
                    session_id="s1",
                    task_id=task_id,
                    criterion_receipt_map=[{"criterion": criterion, "receipt_ids": [receipt.receipt_id]}],
                    completion_summary="Mapped the work criterion to a mismatched receipt type for semantic hardening.",
                )

                self.assertIn("REJECTED", rejected)
                self.assertIn("semantic", rejected.lower())

    def test_completion_gate_rejects_list_summary_when_map_is_also_list(self) -> None:
        with self.assertRaisesRegex(ValueError, "completion_summary must be a string"):
            self.server._completion_gate_arguments(
                [{"criterion": "c1", "receipt_ids": ["r1"]}],
                [{"criterion": "c2", "receipt_ids": ["r2"]}],
            )

    def test_budget_status_reports_mission_idle_minutes_and_last_activity(self) -> None:
        self.server.mission_lock("s1", "idle-task", "goal", ["criterion"])
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute(
                "UPDATE missions SET created_at=? WHERE session_id=? AND task_id=?",
                ("2000-01-01T00:00:00Z", "s1", "idle-task"),
            )

        payload = json.loads(self.server.budget_status("s1", "idle-task"))

        self.assertIn("mission_idle_minutes", payload)
        self.assertGreater(payload["mission_idle_minutes"], 0)
        self.assertEqual(payload["last_activity_at"], "2000-01-01T00:00:00Z")

    def test_subagent_status_reports_child_idle_minutes_and_last_receipt_at(self) -> None:
        self.server.mission_lock("s1", "parent", "goal", ["criterion"])
        child = json.loads(
            self.server.register_subagent_start(
                "s1", "parent", "explore", "inspect parser behavior", {"max_tool_calls": 3},
            )
        )
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute(
                "UPDATE subagent_spans SET started_at=? WHERE child_span_id=?",
                ("2000-01-01T00:00:00Z", child["child_span_id"]),
            )

        payload = json.loads(self.server.subagent_status("s1", "parent"))
        span = payload["child_spans"][0]

        self.assertIn("idle_minutes", span)
        self.assertGreater(span["idle_minutes"], 0)
        self.assertIsNone(span["last_receipt_at"])
        self.assertEqual(span["last_activity_at"], "2000-01-01T00:00:00Z")

    def test_subagent_status_counts_fresh_taskless_child_receipts_as_activity(self) -> None:
        self.server.mission_lock("s1", "parent", "goal", ["criterion"])
        child = json.loads(
            self.server.register_subagent_start(
                "s1", "parent", "explore", "inspect parser behavior", {"max_tool_calls": 3},
            )
        )
        receipt = self.store.record_receipt(
            session_id="s1",
            task_id=None,
            source="hook-test",
            tool_name="Bash",
            command_text="pytest -q",
            exit_code=0,
            metadata={"child_span_id": child["child_span_id"]},
        )

        payload = json.loads(self.server.subagent_status("s1", "parent"))
        span = payload["child_spans"][0]

        self.assertEqual(span["last_receipt_at"], receipt.created_at)
        self.assertEqual(span["last_activity_at"], receipt.created_at)


if __name__ == "__main__":
    unittest.main()
