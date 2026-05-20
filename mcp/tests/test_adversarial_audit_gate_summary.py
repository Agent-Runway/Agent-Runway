from __future__ import annotations

import sys
import unittest
from pathlib import Path

MCP_ROOT = Path(__file__).resolve().parents[1]
if str(MCP_ROOT) not in sys.path:
    sys.path.insert(0, str(MCP_ROOT))

from agent_runway_runtime.adversarial_audit import gate_violations, summarize


class AdversarialAuditGateSummaryTestCase(unittest.TestCase):
    def test_gate_violations_uses_blocking_finding_resolution(self):
        records = [audit_plan(), attempt("attempt-1", "attack_succeeded"), blocking_finding()]
        violations = gate_violations(records, ["runtime_gate_adversary"], ["claim-1"], 10)
        self.assertTrue(
            any("unresolved blocking" in item.lower() and "finding-1" in item for item in violations)
        )

    def test_summarize_excludes_superseded_blocking_findings(self):
        records = [
            audit_plan(),
            attempt("attempt-1", "attack_succeeded", timestamp="2026-05-10T10:00:00Z"),
            attempt("attempt-2", "attack_failed", timestamp="2026-05-10T10:10:00Z"),
            blocking_finding(),
            {
                "record_type": "audit_finding",
                "finding_id": "finding-2",
                "severity": "low",
                "disposition": "non_blocking",
                "linked_attempt_ids": ["attempt-2"],
                "target_claims": ["claim-1"],
                "required_action": "none",
                "timestamp": "2026-05-10T10:10:00Z",
                "supersedes_finding_id": "finding-1",
            },
        ]

        summary = summarize(records)

        self.assertEqual([], summary["unresolved_blockers"])
        self.assertTrue(summary["passed"])


def audit_plan() -> dict[str, object]:
    return {
        "record_type": "audit_plan",
        "plan_id": "plan-1",
        "audit_scope": {
            "target_claims": ["claim-1"],
            "target_files": ["file.py"],
            "allowed_attack_types": ["stale_evidence"],
            "excluded_actions": ["none"],
        },
        "audit_budget": {
            "max_hypotheses": 2,
            "max_executable_attacks": 2,
            "max_runtime_seconds": 300,
            "max_retries_per_attack": 2,
            "max_output_bytes": 10000,
            "max_generated_artifacts": 5,
        },
        "profiles_required": ["runtime_gate_adversary"],
        "freshness_baseline": {
            "latest_receipt_seq": 10,
            "timestamp": "2026-05-10T09:59:00Z",
        },
    }


def attempt(
    attempt_id: str,
    outcome: str,
    timestamp: str = "2026-05-10T10:00:00Z",
) -> dict[str, object]:
    return {
        "record_type": "audit_attempt",
        "attempt_id": attempt_id,
        "plan_id": "plan-1",
        "profile": "runtime_gate_adversary",
        "attack_type": "stale_evidence",
        "hypothesis": f"hypothesis-{attempt_id}",
        "outcome": outcome,
        "execution_receipts": [f"receipt-{attempt_id}"],
        "target_claims": ["claim-1"],
        "timestamp": timestamp,
    }


def blocking_finding() -> dict[str, object]:
    return {
        "record_type": "audit_finding",
        "finding_id": "finding-1",
        "severity": "critical",
        "disposition": "blocking",
        "linked_attempt_ids": ["attempt-1"],
        "target_claims": ["claim-1"],
        "required_action": "fix the bug",
        "timestamp": "2026-05-10T10:00:00Z",
    }


if __name__ == "__main__":
    unittest.main()
