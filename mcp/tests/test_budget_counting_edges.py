from __future__ import annotations

import importlib
import json
import os
import tempfile
import unittest
from pathlib import Path


class BudgetCountingEdgesTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "state.db"
        self.secret_path = Path(self.temp_dir.name) / "secret.key"
        os.environ["ILH_DB_PATH"] = str(self.db_path)
        os.environ["ILH_SECRET_PATH"] = str(self.secret_path)

        import sys

        mcp_root = str(Path(__file__).resolve().parents[1])
        if mcp_root not in sys.path:
            sys.path.insert(0, mcp_root)
        self.server = importlib.import_module("server")
        self.server = importlib.reload(self.server)
        self.audit = importlib.import_module("agent_runway_runtime.adversarial_audit")
        self.store = self.server.store

    def tearDown(self) -> None:
        self.temp_dir.cleanup()
        os.environ.pop("ILH_DB_PATH", None)
        os.environ.pop("ILH_SECRET_PATH", None)

    def make_bash_receipt(
        self, session_id: str, task_id: str, command: str, exit_code: int = 0
    ):
        return self.store.record_receipt(
            session_id=session_id,
            task_id=task_id,
            source="test",
            tool_name="Bash",
            command_text=command,
            exit_code=exit_code,
            metadata={"stdout_sha256": "abc"},
        )

    def audit_plan(self) -> dict[str, object]:
        return {
            "record_type": "audit_plan",
            "plan_id": "plan-1",
            "audit_scope": {
                "target_claims": ["claim-1"],
                "target_files": ["mcp/server.py"],
                "allowed_attack_types": ["stale_evidence"],
                "excluded_actions": ["network"],
            },
            "audit_budget": self.audit_budget(),
            "profiles_required": ["runtime_gate_adversary"],
        }

    def audit_attempt(self, attempt_id: str = "attempt-1") -> dict[str, object]:
        return {
            "record_type": "audit_attempt",
            "attempt_id": attempt_id,
            "profile": "runtime_gate_adversary",
            "attack_type": "stale_evidence",
            "hypothesis": "same reproducible hypothesis",
            "outcome": "attack_failed",
            "execution_receipts": ["receipt-1"],
            "timestamp": "2026-05-10T10:00:00Z",
        }

    def audit_budget(self) -> dict[str, int]:
        return {
            "max_hypotheses": 2,
            "max_executable_attacks": 2,
            "max_runtime_seconds": 300,
            "max_retries_per_attack": 1,
            "max_output_bytes": 10000,
            "max_generated_artifacts": 2,
        }

    def test_duplicate_audit_attempt_records_do_not_double_spend_attack_budget(self) -> None:
        attempt = self.audit_attempt()
        records = [self.audit_plan(), attempt, dict(attempt)]

        usage = self.audit.budget_usage(records, self.audit_budget())

        self.assertEqual(usage["hypotheses_used"], 1)
        self.assertEqual(usage["attacks_used"], 1)
        self.assertEqual(usage["attacks_remaining"], 1)

    def test_duplicate_audit_attempt_records_do_not_block_turn_gate(self) -> None:
        attempt = self.audit_attempt()
        self.server.mission_lock(
            "s1",
            "duplicate-audit-budget-task",
            "goal",
            ["criterion"],
            adversarial_audit_required=True,
            adversarial_audit_profiles=["runtime_gate_adversary"],
            adversarial_audit_claims=["claim-1"],
            adversarial_audit_budget=self.audit_budget(),
            adversarial_audit_records=[self.audit_plan(), attempt, dict(attempt)],
        )
        receipt = self.make_bash_receipt(
            "s1", "duplicate-audit-budget-task", "python verify.py"
        )

        result = self.server.turn_end_gate(
            session_id="s1",
            task_id="duplicate-audit-budget-task",
            stop_condition="slice_verified",
            work_summary="Ran a verified implementation slice with concrete command output evidence.",
            receipt_ids=[receipt.receipt_id],
        )

        self.assertIn("APPROVED", result)
        status = json.loads(self.server.budget_status("s1", "duplicate-audit-budget-task"))
        self.assertEqual(status["adversarial_audit_usage"]["attacks_used"], 1)

    def test_no_receipt_attack_outcomes_do_not_spend_audit_budget(self) -> None:
        invalid_attempt = self.audit_attempt("attempt-without-evidence")
        invalid_attempt["hypothesis"] = "invalid no-receipt hypothesis"
        invalid_attempt["execution_receipts"] = []
        records = [self.audit_plan(), invalid_attempt]

        usage = self.audit.budget_usage(records, self.audit_budget())

        self.assertEqual(usage["hypotheses_used"], 0)
        self.assertEqual(usage["attacks_used"], 0)

    def test_rejected_turn_end_gate_does_not_increment_slice_count(self) -> None:
        self.server.mission_lock("s1", "rejected-slice-task", "goal", ["criterion"])
        receipt = self.make_bash_receipt("s1", "rejected-slice-task", "python verify.py")

        result = self.server.turn_end_gate(
            session_id="s1",
            task_id="rejected-slice-task",
            stop_condition="slice_verified",
            work_summary="This probably works after the command output was inspected.",
            receipt_ids=[receipt.receipt_id],
        )

        self.assertIn("REJECTED", result)
        mission = self.store.get_mission("s1", "rejected-slice-task")
        self.assertEqual(mission.slice_count, 0)

    def test_duplicate_stuck_strategy_does_not_spend_retry_budget_twice(self) -> None:
        self.server.mission_lock("s1", "retry-count-task", "goal", ["criterion"], retry_budget=2)
        receipt = self.make_bash_receipt(
            "s1", "retry-count-task", "pytest failing_test.py", exit_code=1
        )

        self.server.record_stuck_attempt(
            "s1", "retry-count-task", "same-strategy", "first failure", [receipt.receipt_id]
        )
        self.server.record_stuck_attempt(
            "s1", "retry-count-task", "same-strategy", "same failure repeated", [receipt.receipt_id]
        )

        status = json.loads(self.server.budget_status("s1", "retry-count-task"))
        self.assertEqual(status["retries_used"], 1)
        self.assertEqual(status["retries_remaining"], 1)

    def test_missing_receipt_stuck_attempt_does_not_spend_retry_budget(self) -> None:
        self.server.mission_lock("s1", "missing-retry-task", "goal", ["criterion"], retry_budget=1)

        with self.assertRaises(ValueError):
            self.server.record_stuck_attempt(
                "s1", "missing-retry-task", "missing-receipt", "no evidence", ["missing"]
            )

        status = json.loads(self.server.budget_status("s1", "missing-retry-task"))
        self.assertEqual(status["retries_used"], 0)
        self.assertEqual(status["retries_remaining"], 1)


if __name__ == "__main__":
    unittest.main()
