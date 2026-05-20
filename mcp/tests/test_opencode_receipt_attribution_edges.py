from __future__ import annotations

import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "mcp") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "mcp"))
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))


class OpenCodeReceiptAttributionEdgesTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "state.db"
        self.secret_path = Path(self.temp_dir.name) / "secret.key"
        os.environ["ILH_DB_PATH"] = str(self.db_path)
        os.environ["ILH_SECRET_PATH"] = str(self.secret_path)
        os.environ["ILH_HARNESS_SECRET"] = "a" * 64
        self.server = importlib.reload(importlib.import_module("server"))
        self.bridge = importlib.reload(importlib.import_module("opencode_plugin_bridge"))
        self.store = self.server.store

    def tearDown(self) -> None:
        self.temp_dir.cleanup()
        os.environ.pop("ILH_DB_PATH", None)
        os.environ.pop("ILH_SECRET_PATH", None)
        os.environ.pop("ILH_HARNESS_SECRET", None)

    def record_opencode_receipt(
        self,
        session_id: str,
        cwd: str,
        tool_name: str = "bash",
        tool_input: dict[str, object] | None = None,
        tool_response: dict[str, object] | None = None,
    ) -> dict[str, object]:
        return self.bridge.post_tool_use({
            "session_id": session_id,
            "cwd": cwd,
            "tool_name": tool_name,
            "tool_input": tool_input or {"command": "pytest -q"},
            "tool_response": tool_response or {
                "output": "ok",
                "metadata": {"exitCode": 0},
            },
            "hook_event_name": "OpenCodeToolExecuteAfter",
        })

    def test_maps_receipt_to_latest_active_same_cwd_mission(self) -> None:
        self.server.mission_lock(
            "mission-session",
            "active-task",
            "goal",
            ["criterion"],
            host="opencode",
            cwd=self.temp_dir.name,
        )

        result = self.record_opencode_receipt("host-session", self.temp_dir.name)

        self.assertTrue(result["recorded"])
        self.assertEqual(result["task_id"], "active-task")
        mapped = self.store.list_recent_receipts("mission-session", "active-task", limit=10)
        orphan = self.store.list_recent_receipts("host-session", limit=10)
        self.assertEqual(len(mapped), 1)
        self.assertEqual(mapped[0].source, "opencode-plugin")
        self.assertEqual(mapped[0].task_id, "active-task")
        self.assertEqual(orphan, [])

    def test_opencode_exit_aliases_are_preserved_as_receipt_exit_code(self) -> None:
        cases = [
            ("metadata-exit", {"output": "1 passed", "metadata": {"exit": 0}}, 0),
            ("top-exit", {"output": "1 passed", "exit": "0"}, 0),
            ("top-exit-code", {"output": "1 failed", "exitCode": 1}, 1),
            ("top-exit-code-snake", {"output": "1 failed", "exit_code": "2"}, 2),
            ("bool-exit", {"output": "ambiguous", "exit": False}, None),
        ]
        for task_id, tool_response, expected in cases:
            with self.subTest(task_id=task_id):
                project_dir = Path(self.temp_dir.name) / task_id
                project_dir.mkdir()
                self.server.mission_lock(
                    f"mission-session-{task_id}",
                    task_id,
                    "goal",
                    ["tests pass"],
                    host="opencode",
                    cwd=str(project_dir),
                )

                result = self.record_opencode_receipt(
                    "host-session",
                    str(project_dir),
                    tool_response=tool_response,
                )

                self.assertTrue(result["recorded"])
                self.assertEqual(result["exit_code"], expected)
                receipt = self.store.list_recent_receipts(
                    f"mission-session-{task_id}", task_id, limit=1
                )[0]
                self.assertEqual(receipt.exit_code, expected)

    def test_exact_cwd_match_still_fails_closed_when_duplicate_active_missions_exist(self) -> None:
        self.server.mission_lock(
            "mission-session-a",
            "active-task-a",
            "goal",
            ["criterion"],
            host="opencode",
            cwd=self.temp_dir.name,
        )
        self.server.mission_lock(
            "mission-session-b",
            "active-task-b",
            "goal",
            ["criterion"],
            host="opencode",
            cwd=self.temp_dir.name,
        )

        result = self.record_opencode_receipt("host-session", self.temp_dir.name)

        self.assertTrue(result["recorded"])
        self.assertIsNone(result["task_id"])

    def test_exact_cwd_match_fails_closed_when_equivalent_cwd_mapping_is_ambiguous(self) -> None:
        project_dir = Path(self.temp_dir.name) / "project"
        project_dir.mkdir()
        self.server.mission_lock(
            "mission-session-a",
            "active-task-a",
            "goal",
            ["criterion"],
            host="opencode",
            cwd=str(project_dir),
        )
        self.server.mission_lock(
            "mission-session-b",
            "active-task-b",
            "goal",
            ["criterion"],
            host="opencode",
            cwd=str(project_dir) + os.sep,
        )

        result = self.record_opencode_receipt("host-session", str(project_dir))

        self.assertTrue(result["recorded"])
        self.assertIsNone(result["task_id"])

    def test_maps_same_directory_even_when_cwd_strings_are_not_identical(self) -> None:
        project_dir = Path(self.temp_dir.name) / "project"
        project_dir.mkdir()
        self.server.mission_lock(
            "mission-session",
            "active-task",
            "goal",
            ["criterion"],
            host="opencode",
            cwd=str(project_dir),
        )

        result = self.record_opencode_receipt("host-session", str(project_dir) + os.sep)

        self.assertTrue(result["recorded"])
        self.assertEqual(result["task_id"], "active-task")
        mapped = self.store.list_recent_receipts("mission-session", "active-task", limit=10)
        orphan = self.store.list_recent_receipts("host-session", limit=10)
        self.assertEqual(len(mapped), 1)
        self.assertEqual(orphan, [])

    def test_keeps_receipt_taskless_when_same_cwd_mapping_is_ambiguous(self) -> None:
        self.server.mission_lock(
            "mission-session-a",
            "active-task-a",
            "goal",
            ["criterion"],
            host="opencode",
            cwd=self.temp_dir.name,
        )
        self.server.mission_lock(
            "mission-session-b",
            "active-task-b",
            "goal",
            ["criterion"],
            host="opencode",
            cwd=self.temp_dir.name,
        )

        result = self.record_opencode_receipt("host-session", self.temp_dir.name)

        self.assertTrue(result["recorded"])
        self.assertIsNone(result["task_id"])
        self.assertEqual(self.store.list_recent_receipts("mission-session-a", "active-task-a", limit=10), [])
        self.assertEqual(self.store.list_recent_receipts("mission-session-b", "active-task-b", limit=10), [])
        orphan = self.store.list_recent_receipts("host-session", limit=10)
        self.assertEqual(len(orphan), 1)
        self.assertIsNone(orphan[0].task_id)

    def test_mission_lock_event_binds_host_session_to_explicit_mission(self) -> None:
        self.server.mission_lock(
            "old-session",
            "old-task",
            "old goal",
            ["criterion"],
            host="opencode",
            cwd=self.temp_dir.name,
        )
        self.server.mission_lock(
            "mission-session",
            "active-task",
            "goal",
            ["criterion"],
            host="opencode",
            cwd=self.temp_dir.name,
        )

        bound = self.record_opencode_receipt(
            "host-session",
            self.temp_dir.name,
            tool_name="agent-runway_mission_lock",
            tool_input={"session_id": "mission-session", "task_id": "active-task"},
        )
        followup = self.record_opencode_receipt("host-session", self.temp_dir.name)

        self.assertTrue(bound["recorded"])
        self.assertEqual(bound["task_id"], "active-task")
        self.assertTrue(followup["recorded"])
        self.assertEqual(followup["task_id"], "active-task")
        mapped = self.store.list_recent_receipts("mission-session", "active-task", limit=10)
        orphan = self.store.list_recent_receipts("host-session", limit=10)
        self.assertEqual([record.task_id for record in mapped], ["active-task", "active-task"])
        self.assertEqual(orphan, [])

    def test_mission_lock_event_replaces_stale_host_session_binding(self) -> None:
        self.server.mission_lock(
            "old-session",
            "old-task",
            "old goal",
            ["criterion"],
            host="opencode",
            cwd=self.temp_dir.name,
        )
        self.server.mission_lock(
            "mission-session",
            "active-task",
            "goal",
            ["criterion"],
            host="opencode",
            cwd=self.temp_dir.name,
        )

        first = self.record_opencode_receipt(
            "host-session",
            self.temp_dir.name,
            tool_name="agent-runway_mission_lock",
            tool_input={"session_id": "old-session", "task_id": "old-task"},
        )
        second = self.record_opencode_receipt(
            "host-session",
            self.temp_dir.name,
            tool_name="agent-runway_mission_lock",
            tool_input={"session_id": "mission-session", "task_id": "active-task"},
        )
        followup = self.record_opencode_receipt("host-session", self.temp_dir.name)

        self.assertTrue(first["recorded"])
        self.assertEqual(first["task_id"], "old-task")
        self.assertTrue(second["recorded"])
        self.assertEqual(second["task_id"], "active-task")
        self.assertTrue(followup["recorded"])
        self.assertEqual(followup["task_id"], "active-task")

    def test_mission_lock_event_overrides_host_session_active_mission(self) -> None:
        self.server.mission_lock(
            "host-session",
            "host-local-task",
            "host session local goal",
            ["criterion"],
            host="opencode",
            cwd=self.temp_dir.name,
        )
        self.server.mission_lock(
            "mission-session",
            "active-task",
            "goal",
            ["criterion"],
            host="opencode",
            cwd=self.temp_dir.name,
        )

        bound = self.record_opencode_receipt(
            "host-session",
            self.temp_dir.name,
            tool_name="agent-runway_mission_lock",
            tool_input={"session_id": "mission-session", "task_id": "active-task"},
        )
        followup = self.record_opencode_receipt("host-session", self.temp_dir.name)

        self.assertTrue(bound["recorded"])
        self.assertEqual(bound["task_id"], "active-task")
        self.assertTrue(followup["recorded"])
        self.assertEqual(followup["task_id"], "active-task")
        target_receipts = self.store.list_recent_receipts(
            "mission-session", "active-task", limit=10
        )
        host_receipts = self.store.list_recent_receipts(
            "host-session", "host-local-task", limit=10
        )
        self.assertEqual([record.task_id for record in target_receipts], ["active-task", "active-task"])
        self.assertEqual(host_receipts, [])

    def test_agent_runway_tool_with_unknown_mission_records_unscoped_receipt(self) -> None:
        self.server.mission_lock(
            "host-session",
            "host-local-task",
            "host session local goal",
            ["criterion"],
            host="opencode",
            cwd=self.temp_dir.name,
        )

        result = self.record_opencode_receipt(
            "host-session",
            self.temp_dir.name,
            tool_name="agent-runway_turn_end_gate",
            tool_input={
                "session_id": "missing-session",
                "task_id": "missing-task",
                "stop_condition": "slice_verified",
                "work_summary": "Attempted to record a gate for a missing mission.",
                "receipt_ids": ["receipt_demo"],
            },
        )

        self.assertTrue(result["recorded"])
        self.assertIsNone(result["task_id"])
        orphan = self.store.list_recent_receipts("host-session", limit=10)
        self.assertEqual(len(orphan), 1)
        self.assertIsNone(orphan[0].task_id)
        self.assertEqual(orphan[0].metadata["scope_status"], "unscoped")
        self.assertEqual(orphan[0].metadata["scope_reason"], "unknown_agent_runway_mission")
        self.assertEqual(orphan[0].metadata["gate_type"], "turn_end_gate")
        host_receipts = self.store.list_recent_receipts(
            "host-session", "host-local-task", limit=10
        )
        self.assertEqual(host_receipts, [])

    def test_turn_end_gate_tool_receipt_preserves_gate_metadata(self) -> None:
        self.server.mission_lock(
            "mission-session",
            "gate-metadata-task",
            "goal",
            ["criterion"],
            host="opencode",
            cwd=self.temp_dir.name,
        )

        result = self.record_opencode_receipt(
            "host-session",
            self.temp_dir.name,
            tool_name="agent-runway_turn_end_gate",
            tool_input={
                "session_id": "mission-session",
                "task_id": "gate-metadata-task",
                "stop_condition": "slice_verified",
                "work_summary": "Recorded a verified slice through the MCP gate.",
                "receipt_ids": ["receipt_demo"],
            },
        )

        self.assertTrue(result["recorded"])
        receipt = self.store.list_recent_receipts(
            "mission-session", "gate-metadata-task", limit=1
        )[0]
        self.assertEqual("agent-runway_turn_end_gate", receipt.tool_name)
        self.assertEqual("turn_end_gate", receipt.metadata["gate_type"])
        self.assertEqual("slice_verified", receipt.metadata["stop_condition"])
        self.assertEqual(["receipt_demo"], receipt.metadata["receipt_ids"])

    def test_completion_gate_tool_receipt_preserves_summary_metadata(self) -> None:
        self.server.mission_lock(
            "mission-session",
            "completion-metadata-task",
            "goal",
            ["criterion"],
            host="opencode",
            cwd=self.temp_dir.name,
        )
        summary = (
            "Completed the task with a concrete summary that should survive into "
            "receipt metadata."
        )

        result = self.record_opencode_receipt(
            "host-session",
            self.temp_dir.name,
            tool_name="agent-runway_completion_gate",
            tool_input={
                "session_id": "mission-session",
                "task_id": "completion-metadata-task",
                "completion_summary": summary,
                "criterion_receipt_map": [],
            },
        )

        self.assertTrue(result["recorded"])
        receipt = self.store.list_recent_receipts(
            "mission-session", "completion-metadata-task", limit=1
        )[0]
        self.assertEqual("agent-runway_completion_gate", receipt.tool_name)
        self.assertEqual("completion_gate", receipt.metadata["gate_type"])
        self.assertEqual(summary, receipt.metadata["completion_summary"])
        self.assertEqual([], receipt.metadata["criterion_receipt_map"])
        self.assertEqual(
            self.bridge.claude_hooks.sha256_text(summary),
            receipt.metadata["completion_summary_sha256"],
        )


if __name__ == "__main__":
    unittest.main()
