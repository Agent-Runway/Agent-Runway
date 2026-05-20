from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[2]
LINT = REPO_ROOT / "scripts" / "project_learning_lint.py"


def load_lint_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("project_learning_lint", LINT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


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
    def test_lint_defaults_to_project_local_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td)
            local_ledger = workspace / ".agent-runway" / "project-learning-ledger.jsonl"
            shared_ledger = workspace / "references" / "project-learning-ledger.jsonl"
            local_ledger.parent.mkdir(parents=True)
            shared_ledger.parent.mkdir(parents=True)
            local_ledger.write_text(json.dumps(active_pitfall()), encoding="utf-8")
            shared_ledger.write_text('{"bad"', encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, str(LINT), "--json"],
                cwd=workspace,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )

        self.assertEqual(proc.returncode, 0, proc.stdout)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["record_count"], 1)
        self.assertTrue(payload["path"].endswith(".agent-runway\\project-learning-ledger.jsonl") or payload["path"].endswith(".agent-runway/project-learning-ledger.jsonl"))

    def test_allow_missing_default_ledger_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            proc = subprocess.run(
                [sys.executable, str(LINT), "--strict", "--allow-missing", "--json"],
                cwd=Path(td),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
        self.assertEqual(proc.returncode, 0, proc.stdout)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["skipped"])
        self.assertIn("file does not exist", payload["warnings"][0]["issue"])

    def test_parse_jsonl_streams_without_reading_entire_file(self) -> None:
        module = load_lint_module()
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ledger.jsonl"
            path.write_text(json.dumps(active_pitfall()), encoding="utf-8")

            with patch.object(Path, "read_text", side_effect=AssertionError("ledger must stream")):
                records, errors = module.parse_jsonl(path)

        self.assertEqual([], errors)
        self.assertEqual(1, len(records))

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
