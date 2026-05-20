from __future__ import annotations

import importlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
for path in (REPO_ROOT / "mcp", REPO_ROOT / "scripts"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


class DebugLoggingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project_dir = Path(self.temp_dir.name) / "project"
        self.project_dir.mkdir()
        self.log_path = self.project_dir / ".agent-runway" / "debug.log"
        self.db_path = self.project_dir / ".agent-runway" / "state.db"
        self.secret_path = self.project_dir / "secret.key"
        os.environ["ILH_DB_PATH"] = str(self.db_path)
        os.environ["ILH_SECRET_PATH"] = str(self.secret_path)
        os.environ.pop("ILH_DEBUG", None)
        os.environ.pop("ILH_DEBUG_LOG_PATH", None)
        self.server = importlib.reload(importlib.import_module("server"))
        self.hooks = importlib.reload(importlib.import_module("claude_hooks"))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()
        os.environ.pop("ILH_DB_PATH", None)
        os.environ.pop("ILH_SECRET_PATH", None)
        os.environ.pop("ILH_DEBUG", None)
        os.environ.pop("ILH_DEBUG_LOG_PATH", None)

    def enable_debug(self) -> None:
        os.environ["ILH_DEBUG"] = "1"
        os.environ["ILH_DEBUG_LOG_PATH"] = str(self.log_path)

    def read_entries(self) -> list[dict[str, object]]:
        return [json.loads(line) for line in self.log_path.read_text(encoding="utf-8").splitlines()]

    def test_generate_host_config_debug_emits_project_log_env(self) -> None:
        script = REPO_ROOT / "scripts" / "generate_host_config.py"

        claude = subprocess.run(
            [sys.executable, str(script), "--host", "claude-code", "--project-dir", str(self.project_dir), "--debug"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        opencode = subprocess.run(
            [sys.executable, str(script), "--host", "opencode", "--project-dir", str(self.project_dir), "--debug"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )

        self.assertEqual(0, claude.returncode, claude.stdout)
        self.assertEqual(0, opencode.returncode, opencode.stdout)
        claude_payload = json.loads(claude.stdout)
        opencode_payload = json.loads(opencode.stdout)
        expected_log = str(self.project_dir / ".agent-runway" / "debug.log")
        self.assertEqual("1", claude_payload["env"]["ILH_DEBUG"])
        self.assertEqual(expected_log, claude_payload["env"]["ILH_DEBUG_LOG_PATH"])
        environment = opencode_payload["mcp"]["agent-runway"]["environment"]
        self.assertEqual("1", environment["ILH_DEBUG"])
        self.assertEqual(expected_log, environment["ILH_DEBUG_LOG_PATH"])

    def test_generate_host_config_debug_emits_generic_mcp_env(self) -> None:
        script = REPO_ROOT / "scripts" / "generate_host_config.py"

        proc = subprocess.run(
            [sys.executable, str(script), "--host", "codex", "--project-dir", str(self.project_dir), "--debug"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )

        self.assertEqual(0, proc.returncode, proc.stdout)
        payload = json.loads(proc.stdout)
        expected_log = str(self.project_dir / ".agent-runway" / "debug.log")
        self.assertEqual("1", payload["env"]["ILH_DEBUG"])
        self.assertEqual(expected_log, payload["env"]["ILH_DEBUG_LOG_PATH"])

    def test_generate_host_config_omits_debug_env_by_default(self) -> None:
        script = REPO_ROOT / "scripts" / "generate_host_config.py"
        proc = subprocess.run(
            [sys.executable, str(script), "--host", "claude-code", "--project-dir", str(self.project_dir)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )

        self.assertEqual(0, proc.returncode, proc.stdout)
        payload = json.loads(proc.stdout)
        self.assertNotIn("ILH_DEBUG", payload["env"])
        self.assertNotIn("ILH_DEBUG_LOG_PATH", payload["env"])

    def test_hook_debug_writes_redacted_jsonl_when_enabled(self) -> None:
        self.enable_debug()
        output = io.StringIO()
        event = {
            "session_id": "debug-session",
            "tool_name": "Read",
            "tool_input": {"file_path": str(self.secret_path)},
        }

        with redirect_stdout(output):
            result = self.hooks.pre_tool_use(event)

        self.assertEqual(0, result)
        entries = self.read_entries()
        self.assertTrue(any(entry["event"] == "pre_tool_use" for entry in entries))
        log_text = self.log_path.read_text(encoding="utf-8")
        self.assertNotIn(str(self.secret_path), log_text)
        self.assertIn("[REDACTED_PATH]", log_text)

    def test_hook_debug_redacts_protected_path_inside_command_text(self) -> None:
        self.enable_debug()
        output = io.StringIO()

        with redirect_stdout(output):
            result = self.hooks.pre_tool_use(
                {
                    "session_id": "debug-command",
                    "tool_name": "Bash",
                    "tool_input": {"command": f"cat {self.secret_path}"},
                }
            )

        self.assertEqual(0, result)
        log_text = self.log_path.read_text(encoding="utf-8")
        self.assertNotIn(str(self.secret_path), log_text)
        self.assertIn("[REDACTED_PATH]", log_text)

    def test_hook_debug_redacts_protected_path_slash_variant_inside_command_text(self) -> None:
        self.enable_debug()
        output = io.StringIO()
        secret_variant = str(self.secret_path).replace("\\", "/")

        with redirect_stdout(output):
            result = self.hooks.pre_tool_use(
                {
                    "session_id": "debug-command-slash",
                    "tool_name": "Bash",
                    "tool_input": {"command": f"cat {secret_variant}"},
                }
            )

        self.assertEqual(0, result)
        log_text = self.log_path.read_text(encoding="utf-8")
        self.assertNotIn(secret_variant, log_text)
        self.assertIn("[REDACTED_PATH]", log_text)

    def test_hook_debug_redacts_secret_path_field_value(self) -> None:
        self.enable_debug()
        output = io.StringIO()

        with redirect_stdout(output):
            result = self.hooks.pre_tool_use(
                {
                    "session_id": "debug-secret-path",
                    "tool_name": "Read",
                    "tool_input": {"secret_path": str(self.secret_path)},
                }
            )

        self.assertEqual(0, result)
        log_text = self.log_path.read_text(encoding="utf-8")
        self.assertNotIn(str(self.secret_path), log_text)
        self.assertIn("[REDACTED_PATH]", log_text)

    def test_opencode_bridge_debug_logs_pre_and_post_events(self) -> None:
        self.enable_debug()
        bridge = importlib.reload(importlib.import_module("opencode_plugin_bridge"))
        self.server.mission_lock("s1", "t1", "goal", ["criterion"])

        decision = bridge.pre_tool_use(
            {"session_id": "s1", "cwd": str(self.project_dir), "tool_name": "bash", "tool_input": {"command": "pytest -q"}}
        )
        result = bridge.post_tool_use(
            {
                "session_id": "s1",
                "cwd": str(self.project_dir),
                "tool_name": "bash",
                "tool_input": {"command": "pytest -q"},
                "tool_response": {"output": "ok", "metadata": {"exitCode": 0}},
            }
        )

        self.assertEqual("allow", decision["decision"])
        self.assertTrue(result["recorded"])
        events = [entry["event"] for entry in self.read_entries()]
        self.assertIn("opencode_bridge.pre_tool_use", events)
        self.assertIn("opencode_bridge.post_tool_use", events)

    def test_hook_debug_is_disabled_by_default(self) -> None:
        output = io.StringIO()

        with redirect_stdout(output):
            result = self.hooks.pre_tool_use(
                {"session_id": "debug-off", "tool_name": "Bash", "tool_input": {"command": "git push origin main"}}
            )

        self.assertEqual(0, result)
        self.assertFalse(self.log_path.exists())

    def test_runtime_debug_logs_no_valid_receipt_context(self) -> None:
        self.enable_debug()
        self.server.mission_lock("s1", "t1", "debug missing receipt", ["tests pass"])

        with self.assertRaisesRegex(ValueError, "receipt_id 'missing-receipt' was not found"):
            self.server.turn_end_gate(
                session_id="s1",
                task_id="t1",
                stop_condition="slice_verified",
                work_summary="Attempted to stop with a missing receipt to capture debug context.",
                receipt_ids=["missing-receipt"],
            )

        entries = self.read_entries()
        matching = [entry for entry in entries if entry["event"] == "turn_end_gate.no_receipts"]
        self.assertEqual(1, len(matching))
        details = matching[0]["details"]
        self.assertEqual("s1", details["session_id"])
        self.assertEqual("t1", details["task_id"])
        self.assertEqual(["missing-receipt"], details["receipt_ids"])

    def test_runtime_debug_logs_completion_missing_receipts_context(self) -> None:
        self.enable_debug()
        self.server.mission_lock("s1", "t1", "debug missing completion receipt", ["tests pass"])

        with self.assertRaisesRegex(ValueError, "receipt_id 'missing-receipt' was not found"):
            self.server.completion_gate(
                session_id="s1",
                task_id="t1",
                criterion_receipt_map=[{"criterion": "tests pass", "receipt_ids": ["missing-receipt"]}],
                completion_summary="Attempted completion with a missing receipt to capture debug context.",
            )

        entries = self.read_entries()
        matching = [entry for entry in entries if entry["event"] == "completion_gate.missing_receipts"]
        self.assertEqual(1, len(matching))
        details = matching[0]["details"]
        self.assertEqual("s1", details["session_id"])
        self.assertEqual("t1", details["task_id"])
        self.assertEqual(["missing-receipt"], details["receipt_ids"])


if __name__ == "__main__":
    unittest.main()
