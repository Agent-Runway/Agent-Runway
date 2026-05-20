from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
MCP_ROOT = REPO_ROOT / "mcp"
if str(MCP_ROOT) not in sys.path:
    sys.path.insert(0, str(MCP_ROOT))

from agent_runway_runtime.adversarial_audit import read_records
from agent_runway_runtime.adversarial_audit_reading import AuditRecordReadError, read_one


class AdversarialAuditReadErrorsTestCase(unittest.TestCase):
    def test_lint_cli_reports_jsonl_parse_error_with_path_and_line(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            bad = Path(td) / "bad.jsonl"
            bad.write_text('{"record_type":"audit_plan"}\n{"record_type":', encoding="utf-8")

            proc = run_lint(bad)

        self.assertEqual(2, proc.returncode, proc.stdout)
        issue = first_issue(proc)
        self.assertIn(str(bad), issue)
        self.assertIn("line 2", issue)
        self.assertIn("invalid adversarial audit JSON", issue)

    def test_lint_cli_reports_markdown_json_block_parse_error_with_path_and_block(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            bad = Path(td) / "bad.md"
            bad.write_text("# bad\n\n```json\n{\"record_type\":\n```\n", encoding="utf-8")

            proc = run_lint(bad)

        self.assertEqual(2, proc.returncode, proc.stdout)
        issue = first_issue(proc)
        self.assertIn(str(bad), issue)
        self.assertIn("json block 1", issue)
        self.assertIn("invalid adversarial audit JSON", issue)

    def test_lint_cli_reports_json_document_parse_error_with_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            bad = Path(td) / "bad.json"
            bad.write_text('[{"record_type":"audit_plan"}', encoding="utf-8")

            proc = run_lint(bad)

        self.assertEqual(2, proc.returncode, proc.stdout)
        issue = first_issue(proc)
        self.assertIn(str(bad), issue)
        self.assertIn("document", issue)

    def test_read_records_raises_typed_error_for_bad_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            bad = Path(td) / "bad.jsonl"
            bad.write_text('{"record_type":', encoding="utf-8")

            with self.assertRaises(AuditRecordReadError) as context:
                read_records([bad])

        self.assertIn("line 1", context.exception.issue)

    def test_jsonl_reader_streams_without_reading_entire_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            records = Path(td) / "records.jsonl"
            records.write_text(
                '{"record_type":"audit_plan"}\n{"record_type":"audit_attempt"}\n',
                encoding="utf-8",
            )

            with patch.object(Path, "read_text", side_effect=AssertionError("jsonl must stream")):
                loaded = read_one(records)

        self.assertEqual(["audit_plan", "audit_attempt"], [record["record_type"] for record in loaded])


def run_lint(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "adversarial_audit_lint.py"), str(path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )


def first_issue(proc: subprocess.CompletedProcess[str]) -> str:
    payload = json.loads(proc.stdout)
    return payload["issues"][0]


if __name__ == "__main__":
    unittest.main()
