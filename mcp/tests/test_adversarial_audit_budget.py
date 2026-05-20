"""Test adversarial audit budget counting and stop-gate behavior."""

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MCP_ROOT = REPO_ROOT / "mcp"
if str(MCP_ROOT) not in sys.path:
    sys.path.insert(0, str(MCP_ROOT))

from agent_runway_runtime.adversarial_audit import (
    audit_stop_gate,
    budget_usage,
)


class TestAdversarialAuditBudget(unittest.TestCase):
    def test_budget_usage_counts_hypotheses(self):
        """budget_usage() should count hypotheses from audit_attempt records."""
        records = [
            audit_plan(),
            audit_attempt("attempt-1", "hypothesis-1", "2026-05-10T10:00:00Z"),
            audit_attempt("attempt-2", "hypothesis-2", "2026-05-10T10:01:00Z"),
        ]
        usage = budget_usage(records, budget())
        self.assertEqual(usage["hypotheses_used"], 2)
        self.assertEqual(usage["hypotheses_remaining"], 3)

    def test_budget_usage_counts_attacks(self):
        """budget_usage() should count executable attacks from audit_attempt records."""
        records = [
            audit_plan(),
            audit_attempt("attempt-1", "hypothesis-1", "2026-05-10T10:00:00Z", "attack_succeeded"),
            audit_attempt("attempt-2", "hypothesis-2", "2026-05-10T10:01:00Z"),
        ]
        usage = budget_usage(records, budget())
        self.assertEqual(usage["attacks_used"], 2)
        self.assertEqual(usage["attacks_remaining"], 1)

    def test_budget_usage_counts_runtime_seconds(self):
        """budget_usage() should count runtime seconds from audit_attempt timestamps."""
        records = [
            audit_plan("2026-05-10T09:00:00Z"),
            audit_attempt("attempt-1", "hypothesis-1", "2026-05-10T09:02:00Z"),
            audit_attempt("attempt-2", "hypothesis-2", "2026-05-10T09:05:00Z"),
        ]
        usage = budget_usage(records, budget())
        self.assertEqual(usage["runtime_seconds_used"], 300)
        self.assertEqual(usage["runtime_seconds_remaining"], 0)

    def test_budget_usage_ignores_invalid_attempt_timestamps(self):
        records = [
            audit_plan("2026-05-10T09:00:00Z"),
            audit_attempt("attempt-1", "hypothesis-1", "not-a-timestamp"),
            audit_attempt("attempt-2", "hypothesis-2", "2026-05-10T09:05:00Z"),
        ]

        usage = budget_usage(records, budget())

        self.assertEqual(usage["runtime_seconds_used"], 300)

    def test_budget_usage_ignores_naive_attempt_timestamps(self):
        records = [
            audit_plan("2026-05-10T09:00:00Z"),
            audit_attempt("attempt-1", "hypothesis-1", "2026-05-10T09:02:00"),
            audit_attempt("attempt-2", "hypothesis-2", "2026-05-10T09:05:00Z"),
        ]

        usage = budget_usage(records, budget())

        self.assertEqual(usage["runtime_seconds_used"], 300)

    def test_budget_usage_does_not_count_naive_attempt_as_billable(self):
        records = [
            audit_plan("2026-05-10T09:00:00Z"),
            audit_attempt("attempt-1", "hypothesis-1", "2026-05-10T09:02:00"),
        ]

        usage = budget_usage(records, budget())

        self.assertEqual(usage["hypotheses_used"], 0)
        self.assertEqual(usage["attacks_used"], 0)

    def test_budget_usage_does_not_count_non_string_receipt_as_billable(self):
        attempt = audit_attempt("attempt-1", "hypothesis-1", "2026-05-10T09:02:00Z")
        attempt["execution_receipts"] = [0]
        records = [audit_plan("2026-05-10T09:00:00Z"), attempt]

        usage = budget_usage(records, budget())

        self.assertEqual(usage["hypotheses_used"], 0)
        self.assertEqual(usage["attacks_used"], 0)
        self.assertEqual(usage["runtime_seconds_used"], 0)

    def test_budget_usage_does_not_count_untimed_attempt_as_billable(self):
        records = [
            audit_plan("2026-05-10T09:00:00Z"),
            audit_attempt("attempt-1", "hypothesis-1", "not-a-timestamp"),
        ]

        usage = budget_usage(records, budget())

        self.assertEqual(usage["hypotheses_used"], 0)
        self.assertEqual(usage["attacks_used"], 0)

    def test_budget_usage_does_not_count_plan_only_timestamps(self):
        records = [audit_plan("2026-05-10T09:00:00Z")]

        usage = budget_usage(records, budget())

        self.assertEqual(usage["runtime_seconds_used"], 0)

    def test_audit_stop_gate_allows_frontier_exhausted_when_budget_exhausted(self):
        """audit_stop_gate() should allow frontier_exhausted as wrap-up when budget exhausted."""
        audit_budget = budget(max_hypotheses=2, max_executable_attacks=2)
        usage = {
            "hypotheses_used": 2,
            "hypotheses_remaining": 0,
            "attacks_used": 2,
            "attacks_remaining": 0,
            "runtime_seconds_used": 300,
            "runtime_seconds_remaining": 0,
        }
        result = audit_stop_gate(usage, audit_budget, stop_condition="frontier_exhausted")
        self.assertTrue(result["allowed"])
        self.assertIn("wrap-up", result.get("reason", "").lower())

    def test_audit_stop_gate_blocks_slice_verified_when_budget_exhausted(self):
        """audit_stop_gate() should block slice_verified when budget exhausted."""
        audit_budget = budget(max_hypotheses=2, max_executable_attacks=2)
        usage = {
            "hypotheses_used": 2,
            "hypotheses_remaining": 0,
            "attacks_used": 2,
            "attacks_remaining": 0,
            "runtime_seconds_used": 300,
            "runtime_seconds_remaining": 0,
        }
        result = audit_stop_gate(usage, audit_budget, stop_condition="slice_verified")
        self.assertFalse(result["allowed"])
        self.assertIn("budget exhausted", result.get("reason", "").lower())


def audit_plan(freshness_timestamp: str = "") -> dict[str, object]:
    record = {
        "record_type": "audit_plan",
        "plan_id": "plan-1",
        "audit_scope": {
            "target_claims": ["claim-1"],
            "target_files": ["file.py"],
            "allowed_attack_types": ["stale_evidence"],
            "excluded_actions": ["none"],
        },
        "audit_budget": full_budget(),
        "profiles_required": ["runtime_gate_adversary"],
    }
    if freshness_timestamp:
        record["freshness_baseline"] = {
            "latest_receipt_seq": 0,
            "timestamp": freshness_timestamp,
        }
    return record


def audit_attempt(
    attempt_id: str,
    hypothesis: str,
    timestamp: str,
    outcome: str = "attack_failed",
) -> dict[str, object]:
    return {
        "record_type": "audit_attempt",
        "attempt_id": attempt_id,
        "profile": "runtime_gate_adversary",
        "attack_type": "stale_evidence",
        "hypothesis": hypothesis,
        "outcome": outcome,
        "execution_receipts": [f"receipt-{attempt_id}"],
        "timestamp": timestamp,
    }


def budget(
    max_hypotheses: int = 5,
    max_executable_attacks: int = 3,
) -> dict[str, int]:
    return {
        "max_hypotheses": max_hypotheses,
        "max_executable_attacks": max_executable_attacks,
        "max_runtime_seconds": 300,
    }


def full_budget() -> dict[str, int]:
    return {
        **budget(),
        "max_retries_per_attack": 2,
        "max_output_bytes": 10000,
        "max_generated_artifacts": 5,
    }


if __name__ == "__main__":
    unittest.main()
