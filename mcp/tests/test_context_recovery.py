from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CONTEXT_RECOVERY = REPO_ROOT / "scripts" / "context_recovery.py"
MCP_ROOT = REPO_ROOT / "mcp"


class ContextRecoveryCliTestCase(unittest.TestCase):
    def run_cli(self, workspace: Path, args: list[str] | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CONTEXT_RECOVERY), "--cwd", str(workspace), "--json", *(args or [])],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )

    def test_project_sqlite_active_mission_wins_over_dynamic_context(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td) / "repo"
            workspace.mkdir()
            self.write_sqlite_mission(workspace, "sqlite-session", "sqlite-task")
            self.write_dynamic_context(workspace, "json-session", "json-task")

            proc = self.run_cli(workspace, ["--session-id", "new-session"])

        self.assertEqual(proc.returncode, 0, proc.stdout)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["classification"], "continue_current_mission")
        self.assertEqual(payload["source"], "project_sqlite_workspace")
        self.assertEqual(payload["mission"]["session_id"], "sqlite-session")
        self.assertEqual(payload["mission"]["task_id"], "sqlite-task")
        self.assertEqual(payload["checked_sources"][0], "project_sqlite")

    def test_dynamic_context_is_candidate_when_sqlite_has_no_mission(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td) / "repo"
            workspace.mkdir()
            self.write_dynamic_context(workspace, "json-session", "json-task")

            proc = self.run_cli(workspace)

        self.assertEqual(proc.returncode, 0, proc.stdout)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["classification"], "recover_from_dynamic_context")
        self.assertEqual(payload["source"], ".agent-runway/dynamic-context.jsonl")
        self.assertTrue(payload["advisory_only"])
        self.assertEqual(payload["mission"]["session_id"], "json-session")
        self.assertIn("verify mission_status", " ".join(payload["required_first_actions"]))

    def test_recovery_does_not_read_sibling_project_state_or_context(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            active = root / "active"
            sibling = root / "sibling"
            active.mkdir()
            sibling.mkdir()
            self.write_sqlite_mission(sibling, "sibling-session", "sibling-task")
            self.write_dynamic_context(sibling, "json-session", "json-task")

            proc = self.run_cli(active)

        self.assertEqual(proc.returncode, 0, proc.stdout)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["classification"], "clarification_required")
        self.assertNotIn("sibling-session", proc.stdout)
        self.assertEqual(payload["checked_sources"], ["project_sqlite", ".agent-runway/dynamic-context.jsonl"])

    def test_recovery_uses_project_sqlite_created_by_default_store_under_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td) / "repo"
            workspace.mkdir()
            self.write_default_store_mission(workspace, "default-session", "default-task")

            proc = self.run_cli(workspace, ["--session-id", "default-session"])
            state_exists = (workspace / ".agent-runway" / "state.db").exists()

        self.assertEqual(proc.returncode, 0, proc.stdout)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["classification"], "continue_current_mission")
        self.assertEqual(payload["mission"]["session_id"], "default-session")
        self.assertTrue(state_exists)

    def test_no_sqlite_or_dynamic_context_requires_clarification(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td) / "repo"
            workspace.mkdir()

            proc = self.run_cli(workspace)

        self.assertEqual(proc.returncode, 0, proc.stdout)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["classification"], "clarification_required")
        self.assertFalse(payload["should_activate_agent_runway"])
        self.assertIn("No active Agent-Runway mission", payload["required_user_question"])

    def write_sqlite_mission(self, workspace: Path, session_id: str, task_id: str) -> None:
        sys.path.insert(0, str(MCP_ROOT))
        try:
            from agent_runway_runtime.store import RuntimeStore

            secret_path = workspace / ".agent-runway" / "secret.key"
            old_secret = os.environ.get("ILH_SECRET_PATH")
            os.environ["ILH_SECRET_PATH"] = str(secret_path)
            store = RuntimeStore(db_path=str(workspace / ".agent-runway" / "state.db"))
            store.ensure_session(session_id, host="opencode", cwd=str(workspace))
            store.create_mission(session_id, task_id, "sqlite goal", ["sqlite criterion"], "", [], 5, 3)
            if old_secret is None:
                os.environ.pop("ILH_SECRET_PATH", None)
            else:
                os.environ["ILH_SECRET_PATH"] = old_secret
        finally:
            sys.path.remove(str(MCP_ROOT))

    def write_dynamic_context(self, workspace: Path, session_id: str, task_id: str) -> None:
        path = workspace / ".agent-runway" / "dynamic-context.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "schema_version": "1.0",
            "type": "dynamic_context",
            "mission_id": f"{session_id}/{task_id}",
            "session_id": session_id,
            "task_id": task_id,
            "kind": "next_action",
            "summary": "Continue recovered task",
            "content": "Continue from the last verified local slice.",
            "created_at": "2026-05-15T00:00:00Z",
            "can_support_completion": False,
            "requires_fresh_verification": True,
        }
        path.write_text(json.dumps(record) + "\n", encoding="utf-8")

    def write_default_store_mission(self, workspace: Path, session_id: str, task_id: str) -> None:
        code = (
            "import os, sys; "
            f"sys.path.insert(0, {str(MCP_ROOT)!r}); "
            "from agent_runway_runtime.store import RuntimeStore; "
            "store = RuntimeStore(); "
            f"store.ensure_session({session_id!r}, host='opencode', cwd={str(workspace)!r}); "
            f"store.create_mission({session_id!r}, {task_id!r}, 'default store goal', ['criterion'], '', [], 5, 3); "
            "print(store.db_path)"
        )
        env = os.environ.copy()
        env.pop("ILH_DB_PATH", None)
        env["ILH_SECRET_PATH"] = str(workspace / ".agent-runway" / "secret.key")
        proc = subprocess.run(
            [sys.executable, "-c", code],
            cwd=workspace,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            raise AssertionError(proc.stdout)


if __name__ == "__main__":
    unittest.main()
