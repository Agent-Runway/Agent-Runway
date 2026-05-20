from __future__ import annotations

import importlib
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


class StopGatingAdversarialTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "state.db"
        self.secret_path = Path(self.temp_dir.name) / "secret.key"
        self.cwd = Path(self.temp_dir.name) / "repo"
        self.cwd.mkdir()
        os.environ["ILH_DB_PATH"] = str(self.db_path)
        os.environ["ILH_SECRET_PATH"] = str(self.secret_path)

        import sys

        mcp_root = str(REPO_ROOT / "mcp")
        if mcp_root not in sys.path:
            sys.path.insert(0, mcp_root)
        self.server = importlib.import_module("server")
        self.server = importlib.reload(self.server)
        self.store = self.server.store

    def tearDown(self) -> None:
        self.temp_dir.cleanup()
        os.environ.pop("ILH_DB_PATH", None)
        os.environ.pop("ILH_SECRET_PATH", None)

    def make_receipt(self, task_id: str = "t1"):
        return self.store.record_receipt(
            session_id="s1",
            task_id=task_id,
            source="test",
            tool_name="Bash",
            command_text="pytest -q",
            exit_code=0,
            metadata={"stdout_sha256": "abc"},
        )

    def intake(self, message: str, **kwargs) -> dict:
        payload = self.server.prompt_intake_gate(
            session_id=kwargs.pop("session_id", "s1"),
            user_message=message,
            cwd=kwargs.pop("cwd", str(self.cwd)),
            **kwargs,
        )
        return json.loads(payload)

    def test_todo_list_prompt_requires_mission_backed_mcp_intake(self) -> None:
        payload = self.intake("# Todos\n[•] 审计停工点\n[ ] 补齐 host adapter 测试\n[ ] 输出根因矩阵")

        self.assertEqual("new_agent_runway_mission", payload["classification"])
        self.assertTrue(payload["should_activate_agent_runway"])
        self.assertIn("todo_task_list", payload["evidence_sources"])
        actions = " ".join(payload["required_first_actions"])
        self.assertIn("lock mission", actions)
        self.assertIn("record TODO", actions)

    def test_markdown_bullet_todo_list_prompt_requires_mission_backed_mcp_intake(self) -> None:
        payload = self.intake("# TODO\n- [ ] 审计停工点\n* [x] 已读 bug 报告\n1. [ ] 补齐回归测试")

        self.assertEqual("new_agent_runway_mission", payload["classification"])
        self.assertTrue(payload["should_activate_agent_runway"])
        self.assertIn("todo_task_list", payload["evidence_sources"])

    def test_todo_list_prompt_continues_active_mission_before_work(self) -> None:
        self.server.mission_lock("s1", "t1", "audit stop gating", ["matrix produced"], cwd=str(self.cwd))

        payload = self.intake("# Todos\n[•] 当前审计\n[ ] 下一步测试")

        self.assertEqual("continue_current_mission", payload["classification"])
        self.assertEqual("t1", payload["mission"]["task_id"])
        actions = " ".join(payload["required_first_actions"])
        self.assertIn("read mission_status", actions)
        self.assertIn("record TODO", actions)

    def test_compacted_context_with_todo_frontier_requires_recovery_not_silent_stop(self) -> None:
        payload = self.intake(
            "continue",
            session_id="fresh-session",
            workspace_state={"todo_items": ["补齐 gate 绕过测试"]},
        )

        self.assertEqual("recover_context_before_continuing", payload["classification"])
        self.assertTrue(payload["should_activate_agent_runway"])
        self.assertIn("todo_items", payload["evidence_sources"])

    def test_time_budget_uses_wall_clock_when_tool_duration_is_absent(self) -> None:
        self.server.mission_lock(
            "s1",
            "time-window",
            "prevent time-window bypass",
            ["slice verified"],
            time_budget_minutes=1,
        )
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute(
                "UPDATE missions SET created_at=? WHERE session_id=? AND task_id=?",
                ("2000-01-01T00:00:00Z", "s1", "time-window"),
            )
        receipt = self.make_receipt("time-window")

        result = self.server.turn_end_gate(
            session_id="s1",
            task_id="time-window",
            stop_condition="slice_verified",
            work_summary="Attempted to claim a verified slice after the wall-clock time budget expired.",
            receipt_ids=[receipt.receipt_id],
        )

        self.assertIn("REJECTED", result)
        self.assertIn("time budget is exhausted", result)

    def test_turn_end_gate_rejects_verified_stop_with_running_subagent(self) -> None:
        self.server.mission_lock("s1", "parent", "supervise child", ["parent slice verified"])
        self.server.register_subagent_start(
            session_id="s1",
            task_id="parent",
            subagent_type="code-reviewer",
            delegated_scope="review stop gating changes",
            delegated_budget={"max_tool_calls": 3},
        )
        receipt = self.make_receipt("parent")

        result = self.server.turn_end_gate(
            session_id="s1",
            task_id="parent",
            stop_condition="slice_verified",
            work_summary="Attempted to stop the parent slice while the delegated child span is still running.",
            receipt_ids=[receipt.receipt_id],
        )

        self.assertIn("REJECTED", result)
        self.assertIn("running child span", result)

    def test_completion_gate_rejects_invisible_control_hedging(self) -> None:
        self.server.mission_lock("s1", "hedge", "reject hidden hedging", ["tests pass"])
        receipt = self.make_receipt("hedge")

        result = self.server.completion_gate(
            session_id="s1",
            task_id="hedge",
            completion_summary="The change sh\u200bould pass now after the recent edits.",
            criterion_receipt_map=[{"criterion": "tests pass", "receipt_ids": [receipt.receipt_id]}],
        )

        self.assertIn("REJECTED", result)
        self.assertIn("assertion language", result)

    def test_host_stop_weakness_matrix_is_explicit(self) -> None:
        host_adapters = importlib.import_module("agent_runway_runtime.host_adapters")
        host_adapters = importlib.reload(host_adapters)

        matrix = {
            key: host_adapters.get_host_adapter(key).stop_blocking_supported
            for key in ("claude-code", "opencode", "pi-cli")
        }

        self.assertEqual({"claude-code": True, "opencode": False, "pi-cli": False}, matrix)

    def test_opencode_plugin_has_tool_events_but_no_stop_event_surface(self) -> None:
        plugin_text = (REPO_ROOT / ".opencode" / "plugins" / "agent-runway.js").read_text(encoding="utf-8")

        self.assertIn("tool.execute.before", plugin_text)
        self.assertIn("tool.execute.after", plugin_text)
        self.assertIn("session.created", plugin_text)
        self.assertNotIn("assistant.stop", plugin_text)
        self.assertNotIn("message.completed", plugin_text)

    def test_pi_fixture_blocks_tool_calls_without_claiming_stop_parity(self) -> None:
        fixture = (REPO_ROOT / "scripts" / "fixtures" / "pi_block_extension.js").read_text(encoding="utf-8")

        self.assertIn('pi.on("tool_call"', fixture)
        self.assertIn('return { block: true', fixture)
        self.assertNotIn('pi.on("stop"', fixture)


if __name__ == "__main__":
    unittest.main()
