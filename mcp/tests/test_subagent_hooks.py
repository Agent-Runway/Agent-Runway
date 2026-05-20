from __future__ import annotations

import importlib
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


class SubagentHookTestCase(unittest.TestCase):
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
        self.server = importlib.reload(importlib.import_module("server"))
        self.hooks = importlib.reload(importlib.import_module("claude_hooks"))
        self.store = self.server.store

    def tearDown(self) -> None:
        self.temp_dir.cleanup()
        os.environ.pop("ILH_DB_PATH", None)
        os.environ.pop("ILH_SECRET_PATH", None)
        os.environ.pop("ILH_DEBUG", None)
        os.environ.pop("ILH_DEBUG_LOG_PATH", None)

    def lock_parent(self) -> None:
        self.server.mission_lock("s1", "parent-task", "goal", ["criterion"])

    def lock_parent_with_cwd(self) -> None:
        self.server.mission_lock(
            "s1",
            "parent-task",
            "goal",
            ["criterion"],
            cwd=self.temp_dir.name,
        )

    def approve_parent_slice(self, receipt_id: str) -> None:
        approved = self.server.turn_end_gate(
            session_id="s1",
            task_id="parent-task",
            stop_condition="slice_verified",
            work_summary="Verified the parent mission before testing completed-parent child hooks.",
            receipt_ids=[receipt_id],
        )
        self.assertIn("APPROVED", approved)

    def start_event(self, **overrides: object) -> dict[str, object]:
        event: dict[str, object] = {
            "session_id": "s1",
            "hook_event_name": "SubagentStart",
            "agent_runway": {
                "task_id": "parent-task",
                "subagent_type": "code-reviewer",
                "delegated_scope": "review parser changes only",
                "host_child_id": "claude-child-1",
            },
        }
        event.update(overrides)
        return event

    def test_subagent_start_defaults_unknown_host_to_claude_code(self) -> None:
        self.lock_parent()

        with redirect_stdout(io.StringIO()):
            result = self.hooks.subagent_start(self.start_event())

        spans = self.store.list_subagent_spans("s1", "parent-task")
        self.assertEqual(result, 0)
        self.assertEqual(len(spans), 1)
        self.assertEqual(spans[0].host, "claude-code")

    def test_subagent_start_preserves_explicit_event_host(self) -> None:
        self.lock_parent()

        with redirect_stdout(io.StringIO()):
            self.hooks.subagent_start(self.start_event(host="claude-code-devcontainer"))

        spans = self.store.list_subagent_spans("s1", "parent-task")
        self.assertEqual(spans[0].host, "claude-code-devcontainer")

    def test_subagent_start_rejects_malformed_contract_without_span(self) -> None:
        self.lock_parent()
        event = self.start_event(agent_runway="bad-contract")

        with self.assertRaisesRegex(ValueError, "agent_runway must be an object"):
            self.hooks.subagent_start(event)

        self.assertEqual(self.store.list_subagent_spans("s1", "parent-task"), [])

    def test_subagent_start_rejects_invalid_context_mode_without_span(self) -> None:
        self.lock_parent()
        contract = dict(self.start_event()["agent_runway"])
        contract["context_mode"] = "telepathic"

        with self.assertRaisesRegex(ValueError, "agent_runway.context_mode"):
            self.hooks.subagent_start(self.start_event(agent_runway=contract))

        self.assertEqual(self.store.list_subagent_spans("s1", "parent-task"), [])

    def test_subagent_start_parse_failure_does_not_record_visibility(self) -> None:
        self.lock_parent()

        result = self.hooks.subagent_start(
            {"error": "json_decode_failed", "raw_preview_sha256": "abc123"}
        )

        self.assertEqual(result, 0)
        self.assertEqual(self.store.list_subagent_spans("s1", "parent-task"), [])
        self.assertEqual(self.store.list_recent_receipts("s1", "parent-task", limit=1), [])

    def test_subagent_start_routes_visibility_event_by_cwd_when_session_unknown(self) -> None:
        self.lock_parent_with_cwd()
        event = {
            "session_id": "host-session",
            "hook_event_name": "SubagentStart",
            "cwd": self.temp_dir.name,
        }

        result = self.hooks.subagent_start(event)

        receipts = self.store.list_recent_receipts("s1", "parent-task", limit=1)
        self.assertEqual(result, 0)
        self.assertEqual(receipts[0].tool_name, "SubagentStart")
        self.assertTrue(receipts[0].metadata["visibility_only"])

    def test_subagent_start_routes_contract_event_by_cwd_when_session_unknown(self) -> None:
        self.lock_parent_with_cwd()

        with redirect_stdout(io.StringIO()):
            result = self.hooks.subagent_start(
                self.start_event(session_id="host-session", cwd=self.temp_dir.name)
            )

        spans = self.store.list_subagent_spans("s1", "parent-task")
        self.assertEqual(result, 0)
        self.assertEqual(len(spans), 1)
        self.assertEqual(spans[0].session_id, "s1")

    def test_subagent_start_rejects_ambiguous_cwd_contract_without_span(self) -> None:
        self.lock_parent_with_cwd()
        self.server.mission_lock("s2", "parent-task", "goal", ["criterion"], cwd=self.temp_dir.name)

        with self.assertRaisesRegex(ValueError, "multiple active cwd missions"):
            self.hooks.subagent_start(
                self.start_event(session_id="host-session", cwd=self.temp_dir.name)
            )

        self.assertEqual(self.store.list_subagent_spans("s1", "parent-task"), [])
        self.assertEqual(self.store.list_subagent_spans("s2", "parent-task"), [])

    def test_subagent_start_uses_contract_session_id_to_disambiguate_cwd(self) -> None:
        self.lock_parent_with_cwd()
        self.server.mission_lock("s2", "parent-task", "goal", ["criterion"], cwd=self.temp_dir.name)
        contract = dict(self.start_event()["agent_runway"])
        contract["session_id"] = "s2"

        with redirect_stdout(io.StringIO()):
            result = self.hooks.subagent_start(
                self.start_event(session_id="host-session", cwd=self.temp_dir.name, agent_runway=contract)
            )

        self.assertEqual(result, 0)
        self.assertEqual(self.store.list_subagent_spans("s1", "parent-task"), [])
        self.assertEqual(len(self.store.list_subagent_spans("s2", "parent-task")), 1)

    def test_subagent_start_rejects_completed_parent_mission_without_span(self) -> None:
        self.lock_parent()
        receipt = self.store.record_receipt(
            session_id="s1",
            task_id="parent-task",
            source="test",
            tool_name="Bash",
            command_text="pytest",
            exit_code=0,
            metadata={},
        )
        self.approve_parent_slice(receipt.receipt_id)
        self.server.completion_gate(
            session_id="s1",
            task_id="parent-task",
            criterion_receipt_map=[{"criterion": "criterion", "receipt_ids": [receipt.receipt_id]}],
            completion_summary="Completed parent mission before a host child event arrived.",
        )

        with self.assertRaisesRegex(ValueError, "no active parent mission"):
            self.hooks.subagent_start(self.start_event())

        self.assertEqual(self.store.list_subagent_spans("s1", "parent-task"), [])

    def test_subagent_stop_without_contract_records_visibility_only(self) -> None:
        self.lock_parent()
        child = json.loads(
            self.server.register_subagent_start(
                session_id="s1",
                task_id="parent-task",
                subagent_type="code-reviewer",
                delegated_scope="review parser changes only",
                delegated_budget={},
                host="claude-code",
                host_child_id="claude-child-1",
            )
        )
        event = {"session_id": "s1", "hook_event_name": "SubagentStop", "cwd": self.temp_dir.name}

        result = self.hooks.subagent_stop(event)

        span = self.store.get_subagent_span("s1", "parent-task", child["child_span_id"])
        receipts = self.store.list_recent_receipts("s1", "parent-task", limit=1)
        self.assertEqual(result, 0)
        self.assertEqual(span.status, "running")
        self.assertEqual(receipts[0].tool_name, "SubagentStop")
        self.assertTrue(receipts[0].metadata["visibility_only"])

    def test_subagent_stop_routes_contract_event_by_cwd_when_session_unknown(self) -> None:
        self.lock_parent_with_cwd()
        child = json.loads(
            self.server.register_subagent_start(
                session_id="s1",
                task_id="parent-task",
                subagent_type="code-reviewer",
                delegated_scope="review parser changes only",
                delegated_budget={},
                host="claude-code",
                host_child_id="claude-child-1",
            )
        )
        event = {
            "session_id": "host-session",
            "hook_event_name": "SubagentStop",
            "cwd": self.temp_dir.name,
            "agent_runway": {
                "task_id": "parent-task",
                "child_span_id": child["child_span_id"],
                "status": "completed",
            },
        }

        with redirect_stdout(io.StringIO()):
            result = self.hooks.subagent_stop(event)

        span = self.store.get_subagent_span("s1", "parent-task", child["child_span_id"])
        self.assertEqual(result, 0)
        self.assertEqual(span.status, "completed")

    def test_subagent_stop_rejects_duplicate_terminal_update_without_overwriting(self) -> None:
        self.lock_parent()
        child = json.loads(
            self.server.register_subagent_start(
                session_id="s1",
                task_id="parent-task",
                subagent_type="code-reviewer",
                delegated_scope="review parser changes only",
                delegated_budget={},
                host="claude-code",
                host_child_id="claude-child-1",
            )
        )
        self.server.register_subagent_stop(
            session_id="s1",
            task_id="parent-task",
            child_span_id=child["child_span_id"],
            status="failed",
        )
        event = {
            "session_id": "s1",
            "hook_event_name": "SubagentStop",
            "agent_runway": {
                "task_id": "parent-task",
                "child_span_id": child["child_span_id"],
                "status": "completed",
            },
        }

        with self.assertRaisesRegex(ValueError, "already terminal"):
            self.hooks.subagent_stop(event)

        span = self.store.get_subagent_span("s1", "parent-task", child["child_span_id"])
        self.assertEqual(span.status, "failed")

    def test_subagent_stop_rejects_invalid_status_without_closing_span(self) -> None:
        self.lock_parent()
        child = json.loads(
            self.server.register_subagent_start(
                session_id="s1",
                task_id="parent-task",
                subagent_type="code-reviewer",
                delegated_scope="review parser changes only",
                delegated_budget={},
                host="claude-code",
                host_child_id="claude-child-1",
            )
        )
        event = {
            "session_id": "s1",
            "hook_event_name": "SubagentStop",
            "agent_runway": {
                "task_id": "parent-task",
                "child_span_id": child["child_span_id"],
                "status": "done-ish",
            },
        }

        with self.assertRaisesRegex(ValueError, "agent_runway.status"):
            self.hooks.subagent_stop(event)

        span = self.store.get_subagent_span("s1", "parent-task", child["child_span_id"])
        self.assertEqual(span.status, "running")


if __name__ == "__main__":
    unittest.main()
