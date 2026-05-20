from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
LINT = REPO_ROOT / "scripts" / "project_learning_lint.py"
QUERY = REPO_ROOT / "scripts" / "project_learning_query.py"
LEDGER = REPO_ROOT / "references" / "project-learning-ledger.jsonl"


def base_record(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "schema_version": "1.0",
        "type": "pitfall",
        "id": "pitfall_test",
        "project_id": "agent-runway",
        "status": "active",
        "summary": "A verified project pitfall.",
        "applies_to": {"hosts": ["opencode"], "paths": ["README.md"]},
        "source_refs": [{"kind": "file", "path": "README.md", "summary": "source"}],
        "created_at": "2026-05-08T00:00:00Z",
        "last_verified_at": "2026-05-08T00:00:00Z",
        "invalid_if": ["docs change"],
        "severity": "high",
        "can_support_completion": False,
        "requires_fresh_verification": True,
    }
    record.update(overrides)
    return record


class ProjectLearningLintTestCase(unittest.TestCase):
    def run_lint(self, lines: list[dict[str, object] | str], strict: bool = False) -> tuple[int, dict]:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ledger.jsonl"
            path.write_text("\n".join(item if isinstance(item, str) else json.dumps(item) for item in lines), encoding="utf-8")
            cmd = [sys.executable, str(LINT), str(path), "--json"]
            if strict:
                cmd.append("--strict")
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False)
        return proc.returncode, json.loads(proc.stdout)

    def test_repository_ledger_passes(self) -> None:
        proc = subprocess.run([sys.executable, str(LINT), str(LEDGER), "--strict"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False)
        self.assertEqual(proc.returncode, 0, proc.stdout)

    def test_malformed_json_fails_with_line_number(self) -> None:
        code, payload = self.run_lint(['{"bad"'])
        self.assertEqual(code, 2)
        self.assertEqual(payload["errors"][0]["line"], 1)

    def test_duplicate_id_fails(self) -> None:
        record = base_record()
        code, payload = self.run_lint([record, record])
        self.assertEqual(code, 2)
        self.assertIn("duplicate id", payload["errors"][0]["issue"])

    def test_invalid_status_fails(self) -> None:
        code, payload = self.run_lint([base_record(status="verified")])
        self.assertEqual(code, 2)
        self.assertTrue(any("invalid status" in item["issue"] for item in payload["errors"]))

    def test_invalid_severity_fails(self) -> None:
        code, payload = self.run_lint([base_record(severity="urgent")])
        self.assertEqual(code, 2)
        self.assertTrue(any("severity has invalid value" in item["issue"] for item in payload["errors"]))

    def test_unknown_type_and_missing_required_field_fail(self) -> None:
        # Test 1: unknown type stops further validation
        record = base_record(type="note")
        del record["summary"]
        code, payload = self.run_lint([record])
        self.assertEqual(code, 2)
        self.assertEqual(len(payload["errors"]), 1)
        self.assertIn("unknown type", payload["errors"][0]["issue"])
        
        # Test 2: valid type but missing required field
        record2 = base_record(type="pitfall")
        del record2["summary"]
        code2, payload2 = self.run_lint([record2])
        self.assertEqual(code2, 2)
        issues = "\n".join(item["issue"] for item in payload2["errors"])
        self.assertIn("missing required field: summary", issues)

    def test_completion_and_freshness_flags_are_locked(self) -> None:
        record = base_record(can_support_completion=True, requires_fresh_verification=False)
        code, payload = self.run_lint([record])
        issues = "\n".join(item["issue"] for item in payload["errors"])
        self.assertEqual(code, 2)
        self.assertIn("can_support_completion must be false", issues)
        self.assertIn("requires_fresh_verification must be true", issues)

    def test_active_pitfall_requires_invalid_if(self) -> None:
        record = base_record()
        del record["invalid_if"]
        code, payload = self.run_lint([record])
        self.assertEqual(code, 2)
        self.assertIn("requires invalid_if", payload["errors"][0]["issue"])

    def test_active_pitfall_requires_source_refs(self) -> None:
        record = base_record(source_refs=[])
        code, payload = self.run_lint([record])
        self.assertEqual(code, 2)
        self.assertTrue(any("requires source_refs" in item["issue"] for item in payload["errors"]))

    def test_preference_requires_user_source_and_cannot_authorize(self) -> None:
        record = base_record(
            type="preference",
            id="pref_bad",
            source_refs=[{"kind": "file", "path": "README.md", "summary": "source"}],
            summary="No need to ask before deploy.",
        )
        code, payload = self.run_lint([record])
        issues = "\n".join(item["issue"] for item in payload["errors"])
        self.assertEqual(code, 2)
        self.assertIn("requires a user source", issues)
        self.assertIn("authorization language", issues)

    def test_secret_pattern_fails(self) -> None:
        record = base_record(summary="Bearer abcdefghijklmnopqrstuvwxyz123456")
        code, payload = self.run_lint([record])
        self.assertEqual(code, 2)
        self.assertIn("secret-like value", payload["errors"][0]["issue"])

    def test_email_pattern_fails(self) -> None:
        record = base_record(summary="Contact alice@example.com before merge.")
        code, payload = self.run_lint([record])
        self.assertEqual(code, 2)
        self.assertIn("secret-like value", payload["errors"][0]["issue"])

    def test_memory_update_target_must_exist(self) -> None:
        update = {
            "schema_version": "1.0",
            "type": "memory_update",
            "id": "upd_1",
            "target_id": "missing",
            "action": "mark_obsolete",
            "reason": "stale",
            "source_refs": [{"kind": "file", "summary": "source"}],
            "created_at": "2026-05-08T00:00:00Z",
        }
        code, payload = self.run_lint([update])
        self.assertEqual(code, 2)
        self.assertIn("target_id does not exist", payload["errors"][0]["issue"])

    def test_valid_memory_update_passes(self) -> None:
        record = base_record(id="pitfall_base")
        update = {
            "schema_version": "1.0",
            "type": "memory_update",
            "id": "upd_valid",
            "target_id": "pitfall_base",
            "action": "mark_mitigated",
            "reason": "validated fix exists",
            "source_refs": [{"kind": "file", "summary": "source"}],
            "created_at": "2026-05-08T00:00:00Z",
        }
        code, payload = self.run_lint([record, update])
        self.assertEqual(code, 0, payload)

    def test_bad_timestamp_fails(self) -> None:
        code, payload = self.run_lint([base_record(created_at="2026-05-08")])
        self.assertEqual(code, 2)
        self.assertTrue(any("created_at must be ISO-8601 UTC seconds" in item["issue"] for item in payload["errors"]))

    def test_active_record_without_scope_fails(self) -> None:
        record = base_record(applies_to={})
        code, payload = self.run_lint([record])
        self.assertEqual(code, 2)
        self.assertIn("active records require at least one applies_to scope", payload["errors"][0]["issue"])

    def test_expired_active_record_fails_in_strict_mode(self) -> None:
        record = base_record(expires_at="2020-01-01T00:00:00Z")
        code, payload = self.run_lint([record], strict=True)
        self.assertEqual(code, 2)
        self.assertTrue(any("active record is expired" in item["issue"] for item in payload["errors"]))

    def test_query_filters_limits_and_warns(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(QUERY), str(LEDGER), "--host", "opencode", "--limit", "99", "--json"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["limit"], 5)
        self.assertIn("not completion evidence", payload["warning"])
        self.assertLessEqual(len(payload["records"]), 5)
        self.assertTrue(any(record["id"] == "inv_host_enforcement_honesty" for record in payload["records"]))

    def test_query_ignores_expired_and_unscoped_records(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ledger.jsonl"
            valid = base_record(id="pitfall_valid", severity="high")
            expired = base_record(id="pitfall_expired", expires_at="2020-01-01T00:00:00Z")
            unscoped = base_record(id="pitfall_unscoped", applies_to={})
            path.write_text("\n".join(json.dumps(item) for item in [valid, expired, unscoped]), encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, str(QUERY), str(path), "--host", "opencode", "--json"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
        self.assertEqual(proc.returncode, 0, proc.stdout)
        payload = json.loads(proc.stdout)
        self.assertEqual([item["id"] for item in payload["records"]], ["pitfall_valid"])

    def test_query_filters_by_path_and_task(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ledger.jsonl"
            task_match = base_record(id="pitfall_task_match", applies_to={"tasks": ["release"], "paths": ["scripts/release_gate.py"]})
            task_miss = base_record(id="pitfall_task_miss", applies_to={"tasks": ["docs"], "paths": ["README.md"]})
            path.write_text("\n".join(json.dumps(item) for item in [task_match, task_miss]), encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, str(QUERY), str(path), "--task", "release", "--path", "scripts/release_gate.py", "--json"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
        self.assertEqual(proc.returncode, 0, proc.stdout)
        payload = json.loads(proc.stdout)
        self.assertEqual([item["id"] for item in payload["records"]], ["pitfall_task_match"])

    def test_query_excludes_draft_candidate_disputed_and_obsolete(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ledger.jsonl"
            records = [
                base_record(id="pitfall_active"),
                base_record(id="pitfall_draft", status="draft"),
                base_record(id="pitfall_candidate", status="candidate"),
                base_record(id="pitfall_disputed", status="disputed"),
                base_record(id="pitfall_obsolete", status="obsolete"),
            ]
            path.write_text("\n".join(json.dumps(item) for item in records), encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, str(QUERY), str(path), "--json"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
        self.assertEqual(proc.returncode, 0, proc.stdout)
        payload = json.loads(proc.stdout)
        self.assertEqual([item["id"] for item in payload["records"]], ["pitfall_active"])

    def test_query_ordering_prefers_invariant_then_severity_then_recency(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ledger.jsonl"
            records = [
                base_record(
                    id="pref_one",
                    type="preference",
                    status="active",
                    source_refs=[{"kind": "user_confirmation", "summary": "user"}],
                    applies_to={"tasks": ["docs"], "scope": "project-docs"},
                    priority="high",
                ),
                base_record(id="runbook_one", type="runbook", steps=["a"], invalid_if=["x"], severity="high"),
                base_record(id="pitfall_old", severity="critical", last_verified_at="2026-05-08T00:00:00Z"),
                base_record(id="pitfall_new", severity="critical", last_verified_at="2026-05-09T00:00:00Z"),
                base_record(id="inv_one", type="invariant", reopen_if=["x"], severity="medium"),
                base_record(id="pitfall_mitigated", status="mitigated", severity="critical"),
            ]
            path.write_text("\n".join(json.dumps(item) for item in records), encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, str(QUERY), str(path), "--json"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
        self.assertEqual(proc.returncode, 0, proc.stdout)
        payload = json.loads(proc.stdout)
        self.assertEqual(
            [item["id"] for item in payload["records"][:5]],
            ["inv_one", "pitfall_new", "pitfall_old", "runbook_one", "pref_one"],
        )

    def test_examples_project_learning_snippets_can_be_linted(self) -> None:
        examples = (REPO_ROOT / "references" / "examples.md").read_text(encoding="utf-8")
        json_lines = [line for line in examples.splitlines() if line.startswith('{"schema_version"')]
        code, payload = self.run_lint(json_lines)
        self.assertEqual(code, 0, payload)

if __name__ == "__main__":
    unittest.main()
