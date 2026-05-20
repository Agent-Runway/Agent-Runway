from __future__ import annotations

import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path


MCP_ROOT = Path(__file__).resolve().parents[1]
if str(MCP_ROOT) not in sys.path:
    sys.path.insert(0, str(MCP_ROOT))


class RuntimeInputValidationEdgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        os.environ["ILH_DB_PATH"] = str(Path(self.temp_dir.name) / "state.db")
        os.environ["ILH_SECRET_PATH"] = str(Path(self.temp_dir.name) / "secret.key")
        os.environ["ILH_HARNESS_SECRET"] = "a" * 64
        self.server = importlib.reload(importlib.import_module("server"))
        self.store = self.server.store

    def tearDown(self) -> None:
        self.temp_dir.cleanup()
        os.environ.pop("ILH_DB_PATH", None)
        os.environ.pop("ILH_SECRET_PATH", None)
        os.environ.pop("ILH_HARNESS_SECRET", None)

    def bash_receipt(self, task_id: str):
        return self.store.record_receipt(
            session_id="s1",
            task_id=task_id,
            source="test",
            tool_name="Bash",
            command_text="pytest -q",
            exit_code=0,
            metadata={"stdout_sha256": "abc"},
        )

    def test_mission_lock_rejects_invisible_controls_in_goal_and_criteria(self) -> None:
        cases = [
            ("goal", lambda: self.server.mission_lock("s1", "goal-gap", "\x00fix bug", ["criterion"])),
            (
                "completion_criteria",
                lambda: self.server.mission_lock(
                    "s1", "criterion-gap", "goal", ["tests\x00 pass"]
                ),
            ),
        ]
        for field_name, call in cases:
            with self.subTest(field_name=field_name):
                with self.assertRaisesRegex(ValueError, "invisible/control"):
                    call()

    def test_mission_lock_rejects_empty_non_string_goal_without_type_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "goal must not be empty"):
            self.server.mission_lock("s1", "empty-goal-gap", None, ["criterion"])

    def test_mission_lock_rejects_invisible_controls_in_required_audit_claims(self) -> None:
        with self.assertRaisesRegex(ValueError, "invisible/control"):
            self.server.mission_lock(
                "s1",
                "audit-claim-gap",
                "goal",
                ["criterion"],
                adversarial_audit_required=True,
                adversarial_audit_profiles=["runtime_gate_adversary"],
                adversarial_audit_claims=["claim\x00 one"],
                adversarial_audit_budget={
                    "max_hypotheses": 1,
                    "max_executable_attacks": 1,
                    "max_runtime_seconds": 1,
                },
            )

    def test_mission_lock_rejects_non_object_audit_budget(self) -> None:
        with self.assertRaisesRegex(ValueError, "adversarial_audit_budget must be an object"):
            self.server.mission_lock(
                "s1",
                "audit-budget-type-gap",
                "goal",
                ["criterion"],
                adversarial_audit_budget=[],
            )

    def test_record_user_authorization_rejects_invisible_controls_in_scope_fields(self) -> None:
        self.server.mission_lock("s1", "auth-gap", "goal", ["criterion"])
        cases = [
            {
                "action_scope": "\x00git push",
                "approval_scope": "single push",
                "user_statement_excerpt": "ok",
            },
            {
                "action_scope": "git push",
                "approval_scope": "single\x00 push",
                "user_statement_excerpt": "ok",
            },
            {
                "action_scope": "git push",
                "approval_scope": "single push",
                "user_statement_excerpt": "ok\x00",
            },
        ]
        for kwargs in cases:
            with self.subTest(kwargs=kwargs):
                with self.assertRaisesRegex(ValueError, "invisible/control"):
                    self.server.record_user_authorization("s1", "auth-gap", **kwargs)

    def test_record_stuck_attempt_rejects_invisible_strategy_fingerprint(self) -> None:
        self.server.mission_lock("s1", "stuck-gap", "goal", ["criterion"], retry_budget=3)
        receipt = self.bash_receipt("stuck-gap")

        with self.assertRaisesRegex(ValueError, "invisible/control"):
            self.server.record_stuck_attempt(
                "s1",
                "stuck-gap",
                "\x00strategy-a",
                "Recorded one concrete failed strategy.",
                [receipt.receipt_id],
            )

    def test_record_stuck_attempt_rejects_invisible_summary(self) -> None:
        self.server.mission_lock("s1", "stuck-summary-gap", "goal", ["criterion"])
        receipt = self.bash_receipt("stuck-summary-gap")

        with self.assertRaisesRegex(ValueError, "invisible/control"):
            self.server.record_stuck_attempt(
                "s1",
                "stuck-summary-gap",
                "strategy-a",
                "Recorded one failed strategy.\x00",
                [receipt.receipt_id],
            )

    def test_record_stuck_attempt_rejects_empty_non_string_summary_without_type_error(self) -> None:
        self.server.mission_lock("s1", "stuck-empty-summary-gap", "goal", ["criterion"])
        receipt = self.bash_receipt("stuck-empty-summary-gap")

        with self.assertRaisesRegex(ValueError, "summary must not be empty"):
            self.server.record_stuck_attempt(
                "s1",
                "stuck-empty-summary-gap",
                "strategy-a",
                None,
                [receipt.receipt_id],
            )

    def test_invisible_strategy_fingerprint_cannot_create_distinct_retry_attempt(self) -> None:
        self.server.mission_lock("s1", "retry-gap", "goal", ["criterion"], retry_budget=2)
        receipt = self.bash_receipt("retry-gap")
        self.server.record_stuck_attempt(
            "s1",
            "retry-gap",
            "strategy-a",
            "Recorded one concrete failed strategy.",
            [receipt.receipt_id],
        )

        with self.assertRaisesRegex(ValueError, "invisible/control"):
            self.server.record_stuck_attempt(
                "s1",
                "retry-gap",
                "\x00strategy-a",
                "Recorded the same failed strategy with an invisible prefix.",
                [receipt.receipt_id],
            )

        attempts = self.store.list_stuck_attempts("s1", "retry-gap")
        self.assertEqual({"strategy-a"}, {attempt.strategy_fingerprint for attempt in attempts})


if __name__ == "__main__":
    unittest.main()
