from __future__ import annotations

import importlib
import os
import tempfile
import unittest
from pathlib import Path


class MutationEvidenceEdgesTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
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

    def make_receipt(
        self,
        task_id: str,
        tool_name: str,
        command_text: str,
        source: str = "mutation-evidence-test",
    ):
        return self.store.record_receipt(
            session_id="s1",
            task_id=task_id,
            source=source,
            tool_name=tool_name,
            command_text=command_text,
            exit_code=0,
            metadata={"stdout_sha256": "abc"},
        )

    def approve_verified_slice(self, task_id: str, receipt_id: str) -> None:
        approved = self.server.turn_end_gate(
            session_id="s1",
            task_id=task_id,
            stop_condition="slice_verified",
            work_summary="Mapped the current receipt before attempting completion.",
            receipt_ids=[receipt_id],
        )
        self.assertIn("APPROVED", approved)

    def assert_bash_command_rejected(self, task_id: str, command_text: str) -> None:
        self.server.mission_lock("s1", task_id, "goal", ["update the report"])
        receipt = self.make_receipt(task_id, "Bash", command_text)
        self.approve_verified_slice(task_id, receipt.receipt_id)

        rejected = self.server.completion_gate(
            session_id="s1",
            task_id=task_id,
            criterion_receipt_map=[
                {"criterion": "update the report", "receipt_ids": [receipt.receipt_id]}
            ],
            completion_summary="Mapped shell command text to a mutation criterion to enforce tool taxonomy boundaries.",
        )

        self.assertIn("REJECTED", rejected)
        self.assertIn("semantic", rejected.lower())

    def test_bash_write_flag_commands_are_not_mutation_evidence(self) -> None:
        cases = [
            ("fake-write-true", "true --write"),
            ("fake-write-echo", "echo --write ok"),
            ("fake-write-substring", "python tool.py --write-report"),
        ]
        for task_id, command_text in cases:
            with self.subTest(command_text=command_text):
                self.assert_bash_command_rejected(task_id, command_text)

    def test_shell_mutation_syntax_is_not_silent_mutation_evidence(self) -> None:
        cases = [
            ("shell-sed", "sed -i s/old/new/g file.py"),
            ("shell-redirect", "echo content > file.py"),
            ("shell-perl", "perl -pi -e s/old/new/g file.py"),
            ("shell-cp", "cp src.py dst.py"),
            ("shell-mv", "mv old.py new.py"),
        ]
        for task_id, command_text in cases:
            with self.subTest(command_text=command_text):
                self.assert_bash_command_rejected(task_id, command_text)

    def test_mutation_tools_are_mutation_evidence(self) -> None:
        cases = [
            ("edit-tool", "Edit", "file.py"),
            ("write-tool", "Write", "file.py"),
            ("multi-edit-tool", "MultiEdit", "file.py"),
            ("apply-patch-tool", "apply_patch", "*** Begin Patch"),
        ]
        for task_id, tool_name, command_text in cases:
            with self.subTest(tool_name=tool_name):
                self.server.mission_lock("s1", task_id, "goal", ["update the report"])
                receipt = self.make_receipt(
                    task_id, tool_name, command_text, source="claude-hook"
                )
                self.approve_verified_slice(task_id, receipt.receipt_id)

                approved = self.server.completion_gate(
                    session_id="s1",
                    task_id=task_id,
                    criterion_receipt_map=[
                        {"criterion": "update the report", "receipt_ids": [receipt.receipt_id]}
                    ],
                    completion_summary="Mapped a host mutation tool receipt to a mutation criterion.",
                )

                self.assertIn("APPROVED", approved)

    def test_untrusted_source_write_receipts_are_not_mutation_evidence(self) -> None:
        cases = [
            ("fake-source-write", "fake"),
            ("agent-source-write", "agent"),
            ("missing-source-write", ""),
        ]
        for task_id, source in cases:
            with self.subTest(source=source):
                self.server.mission_lock("s1", task_id, "goal", ["update the report"])
                receipt = self.make_receipt(task_id, "Write", "file.py", source=source)
                self.approve_verified_slice(task_id, receipt.receipt_id)

                rejected = self.server.completion_gate(
                    session_id="s1",
                    task_id=task_id,
                    criterion_receipt_map=[
                        {"criterion": "update the report", "receipt_ids": [receipt.receipt_id]}
                    ],
                    completion_summary="Mapped an untrusted-source Write receipt to a mutation criterion.",
                )

                self.assertIn("REJECTED", rejected)
                self.assertIn("semantic", rejected.lower())

    def test_untrusted_source_edit_does_not_make_prior_tests_stale(self) -> None:
        self.server.mission_lock("s1", "fake-source-stale", "goal", ["tests pass"])
        test_receipt = self.make_receipt(
            "fake-source-stale", "Bash", "pytest -q", source="mutation-evidence-test"
        )
        self.make_receipt("fake-source-stale", "Edit", "file.py", source="fake")
        self.approve_verified_slice("fake-source-stale", test_receipt.receipt_id)

        approved = self.server.completion_gate(
            session_id="s1",
            task_id="fake-source-stale",
            criterion_receipt_map=[
                {"criterion": "tests pass", "receipt_ids": [test_receipt.receipt_id]}
            ],
            completion_summary="Mapped a test receipt after ignoring an untrusted-source edit receipt.",
        )

        self.assertIn("APPROVED", approved)
        self.assertNotIn("stale evidence", approved)

    def test_trusted_hook_and_bridge_sources_are_mutation_evidence(self) -> None:
        cases = [
            ("claude-source-edit", "claude-hook", "Edit"),
            ("opencode-source-patch", "opencode-plugin", "apply_patch"),
        ]
        for task_id, source, tool_name in cases:
            with self.subTest(source=source, tool_name=tool_name):
                self.server.mission_lock("s1", task_id, "goal", ["update the report"])
                receipt = self.make_receipt(task_id, tool_name, "file.py", source=source)
                self.approve_verified_slice(task_id, receipt.receipt_id)

                approved = self.server.completion_gate(
                    session_id="s1",
                    task_id=task_id,
                    criterion_receipt_map=[
                        {"criterion": "update the report", "receipt_ids": [receipt.receipt_id]}
                    ],
                    completion_summary="Mapped a trusted host mutation receipt to a mutation criterion.",
                )

                self.assertIn("APPROVED", approved)


if __name__ == "__main__":
    unittest.main()
