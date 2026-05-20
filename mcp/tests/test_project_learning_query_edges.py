from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
QUERY = REPO_ROOT / "scripts" / "project_learning_query.py"


def base_record(record_id: str, tasks: list[str]) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "type": "pitfall",
        "id": record_id,
        "project_id": "agent-runway",
        "status": "active",
        "summary": "A verified project pitfall.",
        "applies_to": {"tasks": tasks},
        "source_refs": [{"kind": "file", "path": "README.md", "summary": "source"}],
        "created_at": "2026-05-08T00:00:00Z",
        "last_verified_at": "2026-05-08T00:00:00Z",
        "invalid_if": ["docs change"],
        "severity": "high",
        "can_support_completion": False,
        "requires_fresh_verification": True,
    }


class ProjectLearningQueryEdgeTests(unittest.TestCase):
    def test_missing_default_ledger_is_non_fatal_advisory_context(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            proc = subprocess.run(
                [sys.executable, str(QUERY), "--json"],
                cwd=Path(td),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )

        self.assertEqual(proc.returncode, 0, proc.stdout)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["records"], [])
        self.assertIn("not completion evidence", payload["warning"])
        self.assertIn("file does not exist", payload["warnings"][0])

    def test_malformed_ledger_remains_fatal(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ledger.jsonl"
            path.write_text('{"bad"', encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, str(QUERY), str(path), "--json"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )

        self.assertEqual(proc.returncode, 2, proc.stdout)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["records"], [])
        self.assertIn("malformed JSON", payload["errors"][0])

    def test_query_defaults_to_project_local_ledger_without_cross_project_mix(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td)
            abc = workspace / "abc"
            abc_ledger = abc / ".agent-runway" / "project-learning-ledger.jsonl"
            shared_ledger = abc / "references" / "project-learning-ledger.jsonl"
            abc_ledger.parent.mkdir(parents=True)
            shared_ledger.parent.mkdir(parents=True)
            abc_ledger.write_text(json.dumps(base_record("pitfall_abc", ["abc-task"])), encoding="utf-8")
            shared_ledger.write_text(json.dumps(base_record("pitfall_shared", ["abc-task"])), encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, str(QUERY), "--task", "abc-task", "--json"],
                cwd=abc,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )

        self.assertEqual(proc.returncode, 0, proc.stdout)
        payload = json.loads(proc.stdout)
        self.assertEqual([item["id"] for item in payload["records"]], ["pitfall_abc"])

    def test_query_matches_hyphenated_task_to_spaced_ledger_task(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ledger.jsonl"
            records = [
                base_record("pitfall_prompt", ["prompt intake"]),
                base_record("pitfall_release", ["release"]),
            ]
            path.write_text("\n".join(json.dumps(item) for item in records), encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, str(QUERY), str(path), "--task", "prompt-intake", "--json"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
        self.assertEqual(proc.returncode, 0, proc.stdout)
        payload = json.loads(proc.stdout)
        self.assertEqual([item["id"] for item in payload["records"]], ["pitfall_prompt"])

    def test_json_output_is_ascii_safe_for_non_utf8_terminals(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ledger.jsonl"
            record = base_record("pitfall_unicode", ["prompt intake"])
            record["summary"] = "계속해줘 prompt intake pitfall"
            path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, str(QUERY), str(path), "--json"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=False,
                check=False,
            )

        self.assertEqual(proc.returncode, 0, proc.stdout.decode("utf-8", errors="replace"))
        proc.stdout.decode("ascii")
        payload = json.loads(proc.stdout.decode("ascii"))
        self.assertEqual(payload["records"][0]["id"], "pitfall_unicode")


if __name__ == "__main__":
    unittest.main()
