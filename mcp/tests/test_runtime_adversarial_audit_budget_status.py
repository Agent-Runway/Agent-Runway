from __future__ import annotations

import importlib
import json
import os
import tempfile
import unittest
from pathlib import Path


class RuntimeAdversarialAuditBudgetStatusTestCase(unittest.TestCase):
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
        self.store = self.server.store

    def tearDown(self) -> None:
        self.temp_dir.cleanup()
        os.environ.pop("ILH_DB_PATH", None)
        os.environ.pop("ILH_SECRET_PATH", None)

    def make_bash_receipt(self, session_id: str, task_id: str, command: str):
        return self.store.record_receipt(
            session_id=session_id,
            task_id=task_id,
            source="test",
            tool_name="Bash",
            command_text=command,
            exit_code=0,
            metadata={"stdout_sha256": "abc"},
        )

    def audit_plan(self, max_attacks: int = 1) -> dict[str, object]:
        return {
            "record_type": "audit_plan",
            "plan_id": "plan-1",
            "audit_scope": {
                "target_claims": ["claim-1"],
                "target_files": ["mcp/server.py"],
                "allowed_attack_types": ["stale_evidence"],
                "excluded_actions": ["network"],
            },
            "audit_budget": {
                "max_hypotheses": 3,
                "max_executable_attacks": max_attacks,
                "max_runtime_seconds": 300,
                "max_retries_per_attack": 1,
                "max_output_bytes": 10000,
                "max_generated_artifacts": 2,
            },
            "profiles_required": ["runtime_gate_adversary"],
        }

    def audit_attempt(self) -> dict[str, object]:
        return {
            "record_type": "audit_attempt",
            "attempt_id": "attempt-1",
            "profile": "runtime_gate_adversary",
            "attack_type": "stale_evidence",
            "hypothesis": "h1",
            "outcome": "attack_failed",
            "execution_receipts": ["receipt-1"],
            "timestamp": "2026-05-10T10:00:00Z",
        }

    def test_adversarial_audit_budget_exhaustion_blocks_verified_slice(self) -> None:
        plan = self.audit_plan()
        self.server.mission_lock(
            "s1",
            "audit-stop-task",
            "goal",
            ["criterion"],
            adversarial_audit_required=True,
            adversarial_audit_profiles=["runtime_gate_adversary"],
            adversarial_audit_budget=plan["audit_budget"],
            adversarial_audit_records=[plan, self.audit_attempt()],
        )
        receipt = self.make_bash_receipt("s1", "audit-stop-task", "python verify.py")

        rejected = self.server.turn_end_gate(
            session_id="s1",
            task_id="audit-stop-task",
            stop_condition="slice_verified",
            work_summary="Attempted to claim a verified slice after exhausting the adversarial audit attack budget.",
            receipt_ids=[receipt.receipt_id],
        )

        self.assertIn("REJECTED", rejected)
        self.assertIn("adversarial audit budget is exhausted", rejected)

    def test_adversarial_audit_budget_exhaustion_allows_frontier_exhausted(self) -> None:
        plan = self.audit_plan()
        self.server.mission_lock(
            "s1",
            "audit-wrap-task",
            "goal",
            ["criterion"],
            adversarial_audit_required=True,
            adversarial_audit_profiles=["runtime_gate_adversary"],
            adversarial_audit_budget=plan["audit_budget"],
            adversarial_audit_records=[plan, self.audit_attempt()],
        )
        receipt = self.make_bash_receipt("s1", "audit-wrap-task", "python inspect.py")

        approved = self.server.turn_end_gate(
            session_id="s1",
            task_id="audit-wrap-task",
            stop_condition="frontier_exhausted",
            work_summary="Inspected the remaining frontier after exhausting the adversarial audit attack budget and found no further in-scope action.",
            receipt_ids=[receipt.receipt_id],
        )

        self.assertIn("APPROVED", approved)
        self.assertIn("stop_condition: frontier_exhausted", approved)

    def test_budget_status_reports_adversarial_audit_usage(self) -> None:
        plan = self.audit_plan(max_attacks=3)
        plan["audit_budget"] = {**plan["audit_budget"], "max_hypotheses": 2}
        plan["freshness_baseline"] = {"timestamp": "2026-05-10T09:00:00Z"}
        attempts = [
            self.audit_attempt(),
            {**self.audit_attempt(), "attempt_id": "attempt-2", "hypothesis": "h2", "execution_receipts": ["receipt-2"], "timestamp": "2026-05-10T09:05:00Z"},
        ]
        attempts[0]["timestamp"] = "2026-05-10T09:02:00Z"
        self.server.mission_lock(
            "s1",
            "audit-budget-status-task",
            "goal",
            ["criterion"],
            adversarial_audit_required=True,
            adversarial_audit_profiles=["runtime_gate_adversary"],
            adversarial_audit_budget=plan["audit_budget"],
            adversarial_audit_records=[plan, *attempts],
        )

        status = json.loads(self.server.budget_status("s1", "audit-budget-status-task"))

        self.assertEqual(status["adversarial_audit_usage"]["hypotheses_used"], 2)
        self.assertEqual(status["adversarial_audit_usage"]["hypotheses_remaining"], 0)
        self.assertEqual(status["adversarial_audit_usage"]["attacks_used"], 2)
        self.assertEqual(status["adversarial_audit_usage"]["attacks_remaining"], 1)
        self.assertEqual(status["adversarial_audit_usage"]["runtime_seconds_used"], 300)


if __name__ == "__main__":
    unittest.main()
