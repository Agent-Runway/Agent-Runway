from __future__ import annotations

import importlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


class IntegrationWorkflowTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        os.environ["ILH_DB_PATH"] = str(Path(self.temp_dir.name) / "state.db")
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

    def receipt(self, task_id: str, tool: str, text: str, exit_code: int = 0):
        return self.store.record_receipt(
            session_id="integration",
            task_id=task_id,
            source="integration-test",
            tool_name=tool,
            command_text=text,
            exit_code=exit_code,
            metadata={"stdout_sha256": "integration"},
        )

    def run_opencode_plugin_e2e(self) -> tuple:
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is required for OpenCode plugin behavior test")
        plugin_path = REPO_ROOT / ".opencode" / "plugins" / "agent-runway.js"
        command = "python -m unittest discover -s mcp/tests -p test_hooks.py"
        script = textwrap.dedent(f"""
            import {{ spawnSync }} from "node:child_process";
            import {{ pathToFileURL }} from "node:url";
            const env = {{...process.env, PYTHONPATH: {json.dumps(str(REPO_ROOT / 'mcp'))}}};
            const py = process.env.ILH_PYTHON || "python3";
            const lock = spawnSync(py, ["-c", "import server; server.mission_lock('node-after','opencode-e2e','verify bridge',['tests pass'])"], {{cwd: {json.dumps(str(REPO_ROOT))}, env, stdio: "inherit"}});
            if (lock.status !== 0) process.exit(lock.status || 1);
            const {{ default: plugin }} = await import(pathToFileURL({json.dumps(str(plugin_path))}).href);
            const server = await plugin.server();
            await server.event({{event: {{type: "session.created", sessionID: "node-after", info: {{cwd: {json.dumps(str(REPO_ROOT))}}}}}}});
            await server["tool.execute.after"]({{sessionID: "node-after", tool: "bash", args: {{command: {json.dumps(command)}}}}}, {{output: "OK", metadata: {{exitCode: 0}}}});
            const gate = spawnSync(py, ["-c", "import server; r=server.store.list_recent_receipts('node-after','opencode-e2e',1)[0]; print(server.completion_gate('node-after','opencode-e2e',[{{'criterion':'tests pass','receipt_ids':[r.receipt_id]}}],'Mapped the OpenCode plugin receipt to the tests criterion.'))"], {{cwd: {json.dumps(str(REPO_ROOT))}, env, stdio: "inherit"}});
            if (gate.status !== 0) process.exit(gate.status || 1);
        """)
        env = os.environ.copy()
        env["ILH_PYTHON"] = sys.executable
        env["ILH_OPENCODE_BRIDGE"] = "1"
        proc = subprocess.run(
            [node, "--input-type=module", "-e", script], cwd=str(REPO_ROOT), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False, timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout)
        with sqlite3.connect(os.environ["ILH_DB_PATH"]) as conn:
            row = conn.execute("SELECT source, tool_name, command_text, exit_code FROM receipts ORDER BY seq DESC LIMIT 1").fetchone()
            status = conn.execute("SELECT status FROM missions WHERE session_id=? AND task_id=?", ("node-after", "opencode-e2e")).fetchone()
        return row, status

    def test_bugfix_flow_requires_post_edit_test_receipt(self) -> None:
        self.server.mission_lock("integration", "bugfix", "fix parsing bug", ["tests pass"])
        old_test = self.receipt("bugfix", "Bash", "python -m unittest", 0)
        self.receipt("bugfix", "Edit", "src/parser.py", 0)

        rejected = self.server.completion_gate(
            "integration",
            "bugfix",
            [{"criterion": "tests pass", "receipt_ids": [old_test.receipt_id]}],
            "Mapped an old test receipt to the required test criterion after an edit.",
        )
        self.assertIn("stale evidence", rejected)

        fresh_test = self.receipt("bugfix", "Bash", "python -m unittest", 0)
        approved = self.server.completion_gate(
            "integration",
            "bugfix",
            [{"criterion": "tests pass", "receipt_ids": [fresh_test.receipt_id]}],
            "Mapped the post-edit test receipt to the required test criterion.",
        )
        self.assertIn("APPROVED", approved)

    def test_failed_retry_flow_requires_distinct_stuck_attempts(self) -> None:
        self.server.mission_lock("integration", "debug", "debug failing job", ["tests pass"], retry_budget=2)
        first = self.receipt("debug", "Bash", "pytest failing_test", 1)
        self.server.record_stuck_attempt("integration", "debug", "strategy-a", "first direct repro failed", [first.receipt_id])

        early = self.server.turn_end_gate(
            session_id="integration",
            task_id="debug",
            stop_condition="stuck_escalation",
            work_summary="Recorded one failed strategy with concrete failing command output.",
            receipt_ids=[first.receipt_id],
            reason_for_stopping="Only one strategy has direct evidence so escalation is premature.",
        )
        self.assertIn("REJECTED", early)

        second = self.receipt("debug", "Bash", "python isolated_repro.py", 1)
        self.server.record_stuck_attempt("integration", "debug", "strategy-b", "isolated repro failed", [second.receipt_id])
        approved = self.server.turn_end_gate(
            session_id="integration",
            task_id="debug",
            stop_condition="stuck_escalation",
            work_summary="Recorded two distinct failing strategies with direct command evidence.",
            receipt_ids=[second.receipt_id],
            reason_for_stopping="Two materially different strategies failed and further retries repeat the same evidence path.",
        )
        self.assertIn("APPROVED", approved)

    def test_authorized_publish_flow_expires_after_new_receipt(self) -> None:
        self.server.mission_lock("integration", "publish", "publish release", ["authorization checked"])
        self.server.record_user_authorization(
            "integration",
            "publish",
            "push Gitea release",
            "current release branch only",
            "User said continue and finish the TODO list.",
            irreversible=True,
        )
        fresh = json.loads(self.server.authorization_status("integration", "publish"))
        self.assertTrue(fresh["authorization"]["fresh"])

        self.receipt("publish", "Bash", "git status --short", 0)
        stale = json.loads(self.server.authorization_status("integration", "publish"))
        self.assertFalse(stale["authorization"]["fresh"])

    def test_opencode_plugin_flow_records_receipt_and_completes_gate(self) -> None:
        row, status = self.run_opencode_plugin_e2e()
        self.assertEqual(row[0], "opencode-plugin")
        self.assertEqual(row[1], "Bash")
        self.assertIn("test_hooks.py", row[2])
        self.assertEqual(row[3], 0)
        self.assertEqual(status[0], "completed")

    def test_opencode_after_hook_records_to_latest_active_task_in_shared_session(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is required for OpenCode plugin behavior test")
        plugin_path = REPO_ROOT / ".opencode" / "plugins" / "agent-runway.js"
        script = textwrap.dedent(f"""
            import {{ spawnSync }} from "node:child_process";
            import {{ pathToFileURL }} from "node:url";
            const env = {{...process.env, PYTHONPATH: {json.dumps(str(REPO_ROOT / 'mcp'))}}};
            const py = process.env.ILH_PYTHON || "python3";
            const lockParent = spawnSync(py, ["-c", "import server; server.mission_lock('shared-after','parent-task','goal',['criterion'])"], {{cwd: {json.dumps(str(REPO_ROOT))}, env, stdio: "inherit"}});
            if (lockParent.status !== 0) process.exit(lockParent.status || 1);
            const lockChild = spawnSync(py, ["-c", "import server; server.mission_lock('shared-after','child-task','goal',['criterion'])"], {{cwd: {json.dumps(str(REPO_ROOT))}, env, stdio: "inherit"}});
            if (lockChild.status !== 0) process.exit(lockChild.status || 1);
            const {{ default: plugin }} = await import(pathToFileURL({json.dumps(str(plugin_path))}).href);
            const server = await plugin.server();
            await server["tool.execute.after"]({{sessionID: "shared-after", tool: "bash", args: {{command: "pytest -q"}}}}, {{output: "OK", metadata: {{exitCode: 0}}}});
        """)
        env = os.environ.copy()
        env["ILH_PYTHON"] = sys.executable
        env["ILH_OPENCODE_BRIDGE"] = "1"
        proc = subprocess.run(
            [node, "--input-type=module", "-e", script],
            cwd=str(REPO_ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout)
        parent_rows = self.store.list_recent_receipts("shared-after", "parent-task", limit=10)
        child_rows = self.store.list_recent_receipts("shared-after", "child-task", limit=10)
        self.assertEqual(parent_rows, [])
        self.assertEqual(len(child_rows), 1)
        self.assertEqual(child_rows[0].source, "opencode-plugin")
        self.assertEqual(child_rows[0].task_id, "child-task")


if __name__ == "__main__":
    unittest.main()
