from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
LINT = REPO_ROOT / "scripts" / "project_learning_lint.py"
LEDGER = REPO_ROOT / "references" / "project-learning-ledger.jsonl"


def lint_record(record: dict[str, object]) -> tuple[int, dict[str, object]]:
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "ledger.jsonl"
        path.write_text(json.dumps(record), encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(LINT), str(path), "--json"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
    return proc.returncode, json.loads(proc.stdout)


def lint_lines(lines: list[dict[str, object]]) -> tuple[int, dict[str, object]]:
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "ledger.jsonl"
        path.write_text("\n".join(json.dumps(line) for line in lines), encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(LINT), str(path), "--json"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
    return proc.returncode, json.loads(proc.stdout)


def active_pitfall(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "schema_version": "1.0",
        "type": "pitfall",
        "id": "pitfall_active_docs",
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


def active_preference(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "schema_version": "1.0",
        "type": "preference",
        "id": "pref_active_docs",
        "project_id": "agent-runway",
        "status": "active",
        "summary": "Prioritize accurate project documentation.",
        "applies_to": {"tasks": ["documentation"], "scope": "project-docs"},
        "source_refs": [{"kind": "user_confirmation", "summary": "User confirmed docs preference."}],
        "created_at": "2026-05-08T00:00:00Z",
        "last_confirmed_at": "2026-05-08T00:00:00Z",
        "priority": "high",
        "can_support_completion": False,
        "requires_fresh_verification": True,
    }
    record.update(overrides)
    return record


class ProjectLearningLintDeliverableTestCase(unittest.TestCase):
    def test_canonical_ledger_passes_strict_lint(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(LINT), str(LEDGER), "--strict"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout)

    def test_confirmed_status_is_not_part_of_v035_state_machine(self) -> None:
        code, payload = lint_record(active_preference(status="confirmed"))
        self.assertEqual(code, 2)
        issues = "\n".join(item["issue"] for item in payload["errors"])
        self.assertIn("invalid status", issues)

    def test_active_preference_requires_user_source(self) -> None:
        code, payload = lint_record(active_preference(source_refs=[{"kind": "file", "summary": "docs"}]))
        self.assertEqual(code, 2)
        issues = "\n".join(item["issue"] for item in payload["errors"])
        self.assertIn("active preference requires a user source", issues)

    def test_active_invariant_requires_invalid_if_or_reopen_if(self) -> None:
        code, payload = lint_record(active_pitfall(type="invariant", invalid_if=[], reopen_if=[]))
        self.assertEqual(code, 2)
        issues = "\n".join(item["issue"] for item in payload["errors"])
        self.assertIn("requires invalid_if or reopen_if", issues)

    def test_active_runbook_requires_non_empty_steps(self) -> None:
        code, payload = lint_record(active_pitfall(type="runbook", steps=[]))
        self.assertEqual(code, 2)
        issues = "\n".join(item["issue"] for item in payload["errors"])
        self.assertIn("requires non-empty steps", issues)

    def test_memory_update_invalid_action_fails(self) -> None:
        record = active_pitfall(id="pitfall_base")
        update = {
            "schema_version": "1.0",
            "type": "memory_update",
            "id": "upd_bad_action",
            "target_id": "pitfall_base",
            "action": "delete_record",
            "reason": "bad action",
            "source_refs": [{"kind": "file", "summary": "source"}],
            "created_at": "2026-05-08T00:00:00Z",
        }
        code, payload = lint_lines([record, update])
        self.assertEqual(code, 2)
        issues = "\n".join(item["issue"] for item in payload["errors"])
        self.assertIn("invalid memory_update action", issues)

    def test_memory_update_missing_required_field_fails(self) -> None:
        record = active_pitfall(id="pitfall_base")
        update = {
            "schema_version": "1.0",
            "type": "memory_update",
            "id": "upd_missing_reason",
            "target_id": "pitfall_base",
            "action": "mark_obsolete",
            "source_refs": [{"kind": "file", "summary": "source"}],
            "created_at": "2026-05-08T00:00:00Z",
        }
        code, payload = lint_lines([record, update])
        self.assertEqual(code, 2)
        issues = "\n".join(item["issue"] for item in payload["errors"])
        self.assertIn("missing required field: reason", issues)


if __name__ == "__main__":
    unittest.main()
