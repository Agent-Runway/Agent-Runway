from __future__ import annotations

import sys
import unittest
from pathlib import Path

MCP_ROOT = Path(__file__).resolve().parents[1]
if str(MCP_ROOT) not in sys.path:
    sys.path.insert(0, str(MCP_ROOT))

from agent_runway_runtime.adversarial_audit import (
    blocking_finding_resolution_status,
    gate_violations,
    lint_records,
    summarize,
)


class AdversarialAuditPlanEdgesTestCase(unittest.TestCase):
    def test_malformed_latest_receipt_seq_reports_lint_instead_of_crashing(self) -> None:
        records = [audit_plan(latest_receipt_seq="not-an-int"), audit_attempt()]

        issues = gate_violations(records, ["runtime_gate_adversary"], ["claim-1"], 3)

        self.assertIn("audit_plan requires integer freshness_baseline.latest_receipt_seq", issues)

    def test_attempt_with_unknown_plan_id_does_not_satisfy_required_coverage(self) -> None:
        records = [audit_plan(), audit_attempt(plan_id="unknown-plan")]

        issues = gate_violations(records, ["runtime_gate_adversary"], ["claim-1"], 3)

        self.assertTrue(any("unknown audit plan_id" in issue for issue in issues))
        self.assertTrue(any("missing required adversarial profiles" in issue for issue in issues))
        self.assertTrue(any("missing adversarial coverage for claims" in issue for issue in issues))

    def test_attempt_without_plan_id_does_not_satisfy_required_coverage(self) -> None:
        attempt = audit_attempt()
        attempt.pop("plan_id")

        issues = gate_violations([audit_plan(), attempt], ["runtime_gate_adversary"], ["claim-1"], 3)

        self.assertTrue(any("audit_attempt requires plan_id" in issue for issue in issues))
        self.assertTrue(any("missing required adversarial profiles" in issue for issue in issues))
        self.assertTrue(any("missing adversarial coverage for claims" in issue for issue in issues))

    def test_non_string_plan_id_does_not_satisfy_required_coverage(self) -> None:
        plan = audit_plan()
        plan["plan_id"] = 0
        attempt = audit_attempt(plan_id=0)

        issues = gate_violations([plan, attempt], ["runtime_gate_adversary"], ["claim-1"], 3)

        self.assertIn("audit_plan requires string plan_id", issues)
        self.assertIn("audit_attempt requires string plan_id", issues)
        self.assertTrue(any("missing required adversarial profiles" in issue for issue in issues))
        self.assertTrue(any("missing adversarial coverage for claims" in issue for issue in issues))

    def test_lint_reports_malformed_latest_receipt_seq_precisely(self) -> None:
        issues = lint_records([audit_plan(latest_receipt_seq="3")])

        self.assertIn("audit_plan requires integer freshness_baseline.latest_receipt_seq", issues)

    def test_lint_rejects_bool_latest_receipt_seq(self) -> None:
        issues = lint_records([audit_plan(latest_receipt_seq=True)])

        self.assertIn("audit_plan requires integer freshness_baseline.latest_receipt_seq", issues)

    def test_lint_rejects_negative_latest_receipt_seq(self) -> None:
        issues = lint_records([audit_plan(latest_receipt_seq=-1)])

        self.assertIn("audit_plan requires freshness_baseline.latest_receipt_seq >= 0", issues)

    def test_non_object_record_reports_index_without_crashing_gate(self) -> None:
        issues = gate_violations([audit_plan(), ["not", "an", "object"]], [], [], 3)  # type: ignore[list-item]

        self.assertIn("record 1 must be an object", issues)

    def test_direct_resolution_status_ignores_non_object_records(self) -> None:
        status = blocking_finding_resolution_status(
            [audit_finding(), ["not", "an", "object"]]  # type: ignore[list-item]
        )

        self.assertEqual(["finding-1"], [item["finding_id"] for item in status["unresolved"]])

    def test_summarize_reports_malformed_records_without_crashing(self) -> None:
        summary = summarize([audit_finding(), ["not", "an", "object"]])  # type: ignore[list-item]

        self.assertEqual(2, summary["record_count"])
        self.assertEqual(["finding-1"], summary["unresolved_blockers"])
        self.assertFalse(summary["passed"])

    def test_mixed_timezone_timestamps_report_lint_instead_of_crashing_gate(self) -> None:
        plan = audit_plan()
        plan["freshness_baseline"] = {
            "latest_receipt_seq": 3,
            "timestamp": "2026-05-10T10:00:00",
        }

        issues = gate_violations([plan, audit_attempt()], ["runtime_gate_adversary"], ["claim-1"], 3)

        self.assertIn("audit timestamp values must include timezone offsets", issues)

    def test_lint_rejects_naive_timestamp_on_optional_resolution_records(self) -> None:
        issues = lint_records(
            [
                {"record_type": "audit_finding", "timestamp": "2026-05-10T10:00:00"},
                {"record_type": "audit_update", "timestamp": "2026-05-10T10:01:00"},
                {"record_type": "audit_acceptance", "timestamp": "2026-05-10T10:02:00"},
            ]
        )

        self.assertEqual(3, issues.count("audit timestamp values must include timezone offsets"))

    def test_lint_reports_naive_attempt_timestamp_once(self) -> None:
        attempt = audit_attempt()
        attempt["timestamp"] = "2026-05-10T10:00:01"

        issues = lint_records([audit_plan(), attempt])

        self.assertEqual(1, issues.count("audit timestamp values must include timezone offsets"))


def audit_plan(latest_receipt_seq: object = 3) -> dict[str, object]:
    return {
        "record_type": "audit_plan",
        "plan_id": "plan-1",
        "audit_scope": {
            "target_claims": ["claim-1"],
            "target_files": ["file.py"],
            "allowed_attack_types": ["stale_evidence"],
            "excluded_actions": ["network"],
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
            "latest_receipt_seq": latest_receipt_seq,
            "timestamp": "2026-05-10T10:00:00Z",
        },
    }


def audit_attempt(plan_id: object = "plan-1") -> dict[str, object]:
    return {
        "record_type": "audit_attempt",
        "attempt_id": "attempt-1",
        "plan_id": plan_id,
        "profile": "runtime_gate_adversary",
        "target_claims": ["claim-1"],
        "hypothesis": "old or unscoped evidence might satisfy coverage",
        "attack_type": "stale_evidence",
        "execution_receipts": ["receipt-1"],
        "outcome": "attack_failed",
        "timestamp": "2026-05-10T10:00:01Z",
    }


def audit_finding() -> dict[str, object]:
    return {
        "record_type": "audit_finding",
        "finding_id": "finding-1",
        "severity": "critical",
        "disposition": "blocking",
        "linked_attempt_ids": [],
        "target_claims": ["claim-1"],
        "required_action": "fix the blocker",
        "timestamp": "2026-05-10T10:00:00Z",
    }


if __name__ == "__main__":
    unittest.main()
