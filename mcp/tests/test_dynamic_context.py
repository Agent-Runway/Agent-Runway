from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DYNAMIC_CONTEXT = REPO_ROOT / "scripts" / "dynamic_context.py"


class DynamicContextCliTestCase(unittest.TestCase):
    def run_cli(self, args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(DYNAMIC_CONTEXT), *args],
            cwd=cwd or REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )

    def test_append_records_mission_identity_and_non_evidence_flags(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "dynamic-context.jsonl"
            proc = self.run_cli([
                "append", "--path", str(path), "--session-id", "s1", "--task-id", "t1",
                "--kind", "finding", "--summary", "Found context gap", "--content", "Need next slice.",
            ])

            self.assertEqual(proc.returncode, 0, proc.stdout)
            record = json.loads(path.read_text(encoding="utf-8").strip())
            self.assertEqual("s1/t1", record["mission_id"])
            self.assertEqual("s1", record["session_id"])
            self.assertEqual("t1", record["task_id"])
            self.assertIs(record["can_support_completion"], False)
            self.assertIs(record["requires_fresh_verification"], True)

    def test_append_default_path_is_project_local_agent_runway_directory(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td)
            proc = self.run_cli([
                "append", "--session-id", "s1", "--task-id", "t1", "--kind", "note",
                "--summary", "Project local context", "--content", "Continue from project-local context.",
            ], cwd=workspace)

            context_path = workspace / ".agent-runway" / "dynamic-context.jsonl"
            self.assertEqual(proc.returncode, 0, proc.stdout)
            self.assertTrue(context_path.exists())
            payload = json.loads(context_path.read_text(encoding="utf-8").strip())
            self.assertEqual("s1/t1", payload["mission_id"])

    def test_lint_rejects_missing_mission_identity(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "dynamic-context.jsonl"
            path.write_text(json.dumps({
                "schema_version": "1.0",
                "type": "dynamic_context",
                "session_id": "s1",
                "task_id": "t1",
                "kind": "finding",
                "summary": "Missing mission id.",
                "content": "bad",
                "created_at": "2026-05-15T00:00:00Z",
                "can_support_completion": False,
                "requires_fresh_verification": True,
            }), encoding="utf-8")

            proc = self.run_cli(["lint", "--path", str(path), "--json"])

        self.assertEqual(proc.returncode, 2, proc.stdout)
        payload = json.loads(proc.stdout)
        issues = "\n".join(item["issue"] for item in payload["errors"])
        self.assertIn("missing required field: mission_id", issues)

    def test_append_rejects_content_over_100k_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "dynamic-context.jsonl"
            content = Path(td) / "large.txt"
            content.write_text("x" * 100_001, encoding="utf-8")
            proc = self.run_cli([
                "append", "--path", str(path), "--session-id", "s1", "--task-id", "t1",
                "--kind", "note", "--summary", "Too large", "--content-file", str(content),
            ])

            self.assertEqual(proc.returncode, 2, proc.stdout)
            self.assertFalse(path.exists())
            self.assertIn("content exceeds 100000 bytes", proc.stdout)

    def test_query_filters_mission_and_respects_output_budget(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "dynamic-context.jsonl"
            for task_id, content in [("t1", "a" * 80), ("t1", "b" * 80), ("t2", "wrong")]:
                proc = self.run_cli([
                    "append", "--path", str(path), "--session-id", "s1", "--task-id", task_id,
                    "--kind", "note", "--summary", f"summary {task_id}", "--content", content,
                ])
                self.assertEqual(proc.returncode, 0, proc.stdout)

            proc = self.run_cli([
                "query", "--path", str(path), "--session-id", "s1", "--task-id", "t1",
                "--max-output-bytes", "220", "--json",
            ])

        self.assertEqual(proc.returncode, 0, proc.stdout)
        payload = json.loads(proc.stdout)
        self.assertEqual("s1/t1", payload["mission_id"])
        self.assertTrue(payload["truncated"])
        self.assertEqual(1, len(payload["records"]))
        self.assertEqual("t1", payload["records"][0]["task_id"])


if __name__ == "__main__":
    unittest.main()
