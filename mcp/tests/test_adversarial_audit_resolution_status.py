from __future__ import annotations

import sys
import unittest
from pathlib import Path

MCP_ROOT = Path(__file__).resolve().parents[1]
if str(MCP_ROOT) not in sys.path:
    sys.path.insert(0, str(MCP_ROOT))

from agent_runway_runtime.adversarial_audit import (
    blocking_finding_resolution_status,
    lint_records,
)


class AdversarialAuditResolutionStatusTestCase(unittest.TestCase):
    def test_blocking_finding_resolution_status_unresolved(self):
        records = [finding("finding-1", "blocking", "critical")]
        status = blocking_finding_resolution_status(records)
        self.assertEqual(len(status["unresolved"]), 1)
        self.assertEqual(status["unresolved"][0]["finding_id"], "finding-1")

    def test_blocking_finding_resolution_status_resolved_by_acceptance(self):
        records = [
            finding("finding-1", "accepted_residual_risk", "critical"),
            acceptance("finding-1", "claim-1", "risk accepted due to low likelihood"),
        ]
        status = blocking_finding_resolution_status(records)
        self.assertEqual(len(status["unresolved"]), 0)
        self.assertEqual(len(status["resolved_by_acceptance"]), 1)

    def test_blocking_finding_resolution_status_acceptance_can_resolve_blocker(self):
        records = [
            finding("finding-1", "blocking", "critical"),
            acceptance("finding-1", "claim-1", "user explicitly accepts residual risk"),
        ]
        status = blocking_finding_resolution_status(records)
        self.assertEqual(len(status["unresolved"]), 0)
        self.assertEqual(len(status["resolved_by_acceptance"]), 1)

    def test_acceptance_scope_must_overlap_finding_claims(self):
        records = [
            finding("finding-1", "blocking", "critical", claims_key="affected_claims"),
            acceptance("finding-1", "unrelated-claim", "different risk must not close this finding"),
        ]
        status = blocking_finding_resolution_status(records)
        self.assertEqual(len(status["unresolved"]), 1)

    def test_audit_update_with_acceptance_can_resolve_blocking_finding(self):
        records = [
            finding("finding-1", "blocking", "critical"),
            {
                "record_type": "audit_update",
                "update_id": "update-1",
                "target_id": "finding-1",
                "reason": "finding was reclassified after fix and rerun",
                "new_disposition": "accepted_residual_risk",
                "timestamp": "2026-05-10T10:10:00Z",
            },
            acceptance("finding-1", "claim-1", "residual risk documented after re-audit"),
        ]
        status = blocking_finding_resolution_status(records)
        self.assertEqual(len(status["unresolved"]), 0)

    def test_audit_update_older_than_finding_does_not_resolve_blocking_finding(self):
        records = [
            finding("finding-1", "blocking", "critical"),
            {
                "record_type": "audit_update",
                "update_id": "update-1",
                "target_id": "finding-1",
                "reason": "older reclassification must not override the finding",
                "new_disposition": "accepted_residual_risk",
                "timestamp": "2026-05-10T09:50:00Z",
            },
            acceptance("finding-1", "claim-1", "residual risk documented on stale update"),
        ]
        status = blocking_finding_resolution_status(records)
        self.assertEqual(len(status["unresolved"]), 1)
        self.assertEqual(status["unresolved"][0]["finding_id"], "finding-1")

    def test_audit_update_without_timestamp_does_not_resolve_blocking_finding(self):
        records = [
            finding("finding-1", "blocking", "critical"),
            {
                "record_type": "audit_update",
                "update_id": "update-1",
                "target_id": "finding-1",
                "reason": "untimed reclassification must not override the finding",
                "new_disposition": "accepted_residual_risk",
            },
            acceptance("finding-1", "claim-1", "residual risk documented without update freshness"),
        ]
        status = blocking_finding_resolution_status(records)
        self.assertEqual(len(status["unresolved"]), 1)
        self.assertEqual(status["unresolved"][0]["finding_id"], "finding-1")

    def test_audit_update_with_same_timestamp_as_finding_does_not_resolve_blocking_finding(self):
        records = [
            finding("finding-1", "blocking", "critical"),
            {
                "record_type": "audit_update",
                "update_id": "update-1",
                "target_id": "finding-1",
                "reason": "equal timestamp must not count as fresher reclassification",
                "new_disposition": "accepted_residual_risk",
                "timestamp": "2026-05-10T10:00:00Z",
            },
            acceptance("finding-1", "claim-1", "residual risk documented without fresher update"),
        ]
        status = blocking_finding_resolution_status(records)
        self.assertEqual(len(status["unresolved"]), 1)
        self.assertEqual(status["unresolved"][0]["finding_id"], "finding-1")

    def test_audit_update_rejects_unknown_new_disposition(self):
        records = [
            attempt("attempt-1", "attack_succeeded"),
            finding("finding-1", "blocking", "critical"),
            {
                "record_type": "audit_update",
                "update_id": "update-1",
                "target_id": "finding-1",
                "reason": "invalid laundering attempt",
                "new_disposition": "resolved",
            },
        ]
        issues = "\n".join(lint_records(records))
        self.assertIn("unknown new_disposition", issues)
        self.assertEqual(len(blocking_finding_resolution_status(records)["unresolved"]), 1)

    def test_audit_update_without_acceptance_does_not_resolve_blocking_finding(self):
        records = [
            finding("finding-1", "blocking", "critical"),
            {
                "record_type": "audit_update",
                "update_id": "update-1",
                "target_id": "finding-1",
                "reason": "claiming reclassification without acceptance or superseding audit",
                "new_disposition": "non_blocking",
            },
        ]
        status = blocking_finding_resolution_status(records)
        self.assertEqual(len(status["unresolved"]), 1)

    def test_newer_acceptance_update_wins_over_older_blocking_update_even_if_listed_first(self):
        records = [
            finding("finding-1", "blocking", "critical"),
            {
                "record_type": "audit_update",
                "update_id": "update-new",
                "target_id": "finding-1",
                "reason": "newer re-audit downgraded the finding",
                "new_disposition": "accepted_residual_risk",
                "timestamp": "2026-05-10T10:10:00Z",
            },
            acceptance("finding-1", "claim-1", "newer residual risk acceptance"),
            {
                "record_type": "audit_update",
                "update_id": "update-old",
                "target_id": "finding-1",
                "reason": "older status should not override newer update by list order",
                "new_disposition": "blocking",
                "timestamp": "2026-05-10T10:05:00Z",
            },
        ]
        status = blocking_finding_resolution_status(records)
        self.assertEqual(len(status["unresolved"]), 0)
        self.assertEqual(len(status["resolved_by_acceptance"]), 1)

    def test_newer_blocking_update_wins_over_older_acceptance_update_even_if_listed_last(self):
        records = [
            finding("finding-1", "blocking", "critical"),
            {
                "record_type": "audit_update",
                "update_id": "update-old",
                "target_id": "finding-1",
                "reason": "older acceptance state should not override newer blocker",
                "new_disposition": "accepted_residual_risk",
                "timestamp": "2026-05-10T10:05:00Z",
            },
            acceptance("finding-1", "claim-1", "older residual risk acceptance"),
            {
                "record_type": "audit_update",
                "update_id": "update-new",
                "target_id": "finding-1",
                "reason": "newer re-audit restored the blocking disposition",
                "new_disposition": "blocking",
                "timestamp": "2026-05-10T10:10:00Z",
            },
        ]
        status = blocking_finding_resolution_status(records)
        self.assertEqual(len(status["unresolved"]), 1)
        self.assertEqual(status["unresolved"][0]["finding_id"], "finding-1")

    def test_blocking_finding_resolution_status_resolved_by_supersede(self):
        records = [
            attempt("attempt-2", "attack_failed"),
            finding("finding-1", "blocking", "critical", timestamp="2026-05-10T10:00:00Z"),
            {
                **finding("finding-2", "non_blocking", "low", timestamp="2026-05-10T10:10:00Z"),
                "linked_attempt_ids": ["attempt-2"],
                "required_action": "none",
                "supersedes_finding_id": "finding-1",
            },
        ]
        status = blocking_finding_resolution_status(records)
        self.assertEqual(len(status["unresolved"]), 0)
        self.assertEqual(len(status["resolved_by_supersede"]), 1)


def attempt(attempt_id: str, outcome: str) -> dict[str, object]:
    return {
        "record_type": "audit_attempt",
        "attempt_id": attempt_id,
        "profile": "runtime_gate_adversary",
        "attack_type": "stale_evidence",
        "hypothesis": "h1",
        "outcome": outcome,
        "execution_receipts": ["receipt-1"],
        "target_claims": ["claim-1"],
        "timestamp": "2026-05-10T10:09:00Z",
    }


def finding(
    finding_id: str,
    disposition: str,
    severity: str,
    timestamp: str = "2026-05-10T10:00:00Z",
    claims_key: str = "target_claims",
) -> dict[str, object]:
    return {
        "record_type": "audit_finding",
        "finding_id": finding_id,
        "severity": severity,
        "disposition": disposition,
        "linked_attempt_ids": ["attempt-1"],
        claims_key: ["claim-1"],
        "required_action": "fix the bug",
        "timestamp": timestamp,
    }


def acceptance(
    finding_id: str,
    scope: str,
    reason: str,
    timestamp: str = "2026-05-10T10:12:00Z",
) -> dict[str, object]:
    return {
        "record_type": "audit_acceptance",
        "acceptance_id": "acceptance-1",
        "linked_finding_id": finding_id,
        "accepted_scope": scope,
        "reason": reason,
        "timestamp": timestamp,
    }


if __name__ == "__main__":
    unittest.main()
