from __future__ import annotations

import sys
import unittest
from pathlib import Path

MCP_ROOT = Path(__file__).resolve().parents[1]
if str(MCP_ROOT) not in sys.path:
    sys.path.insert(0, str(MCP_ROOT))

from agent_runway_runtime.adversarial_audit import blocking_finding_resolution_status


def attempt(attempt_id: str, claim: str, outcome: str = "attack_failed") -> dict[str, object]:
    return {
        "record_type": "audit_attempt",
        "attempt_id": attempt_id,
        "profile": "runtime_gate_adversary",
        "attack_type": "stale_evidence",
        "hypothesis": f"probe {claim}",
        "outcome": outcome,
        "execution_receipts": [f"receipt-{attempt_id}"],
        "target_claims": [claim],
        "timestamp": "2026-05-10T10:05:00Z",
    }


def finding(
    finding_id: str,
    claim: str,
    disposition: str,
    severity: str,
    timestamp: str,
    supersedes: str = "",
    linked_attempt_ids: list[str] | None = None,
) -> dict[str, object]:
    record: dict[str, object] = {
        "record_type": "audit_finding",
        "finding_id": finding_id,
        "severity": severity,
        "disposition": disposition,
        "linked_attempt_ids": linked_attempt_ids or [],
        "target_claims": [claim],
        "required_action": "fix or document the risk",
        "timestamp": timestamp,
    }
    if supersedes:
        record["supersedes_finding_id"] = supersedes
    return record


class AdversarialAuditResolutionEdgesTestCase(unittest.TestCase):
    def test_claimless_blocking_finding_does_not_accept_unrelated_scope(self) -> None:
        records = [
            {
                "record_type": "audit_finding",
                "finding_id": "finding-1",
                "severity": "critical",
                "disposition": "blocking",
                "linked_attempt_ids": ["attempt-1"],
                "target_claims": [],
                "affected_claims": [],
                "required_action": "fix the bug",
            },
            {
                "record_type": "audit_acceptance",
                "acceptance_id": "acceptance-1",
                "linked_finding_id": "finding-1",
                "accepted_scope": "unrelated-claim",
                "reason": "claimless findings must not accept arbitrary scopes",
            },
        ]

        status = blocking_finding_resolution_status(records)

        self.assertEqual(["finding-1"], [item["finding_id"] for item in status["unresolved"]])

    def test_acceptance_uses_affected_claims_when_target_claims_is_empty(self) -> None:
        records = [
            {
                "record_type": "audit_finding",
                "finding_id": "finding-1",
                "severity": "critical",
                "disposition": "blocking",
                "linked_attempt_ids": ["attempt-1"],
                "target_claims": [],
                "affected_claims": ["claim-1"],
                "required_action": "fix the bug",
            },
            {
                "record_type": "audit_acceptance",
                "acceptance_id": "acceptance-1",
                "linked_finding_id": "finding-1",
                "accepted_scope": "unrelated-claim",
                "reason": "accepting a different risk must not close this finding",
            },
        ]

        status = blocking_finding_resolution_status(records)

        self.assertEqual(["finding-1"], [item["finding_id"] for item in status["unresolved"]])

    def test_supersede_requires_evidence_from_superseding_attempt(self) -> None:
        records = [
            finding("finding-1", "claim-1", "blocking", "critical", "2026-05-10T10:00:00Z"),
            finding(
                "finding-2",
                "claim-1",
                "non_blocking",
                "low",
                "2026-05-10T10:10:00Z",
                supersedes="finding-1",
                linked_attempt_ids=["missing-attempt"],
            ),
        ]

        status = blocking_finding_resolution_status(records)

        self.assertEqual(["finding-1"], [item["finding_id"] for item in status["unresolved"]])
        self.assertEqual([], status["resolved_by_supersede"])

    def test_supersede_requires_claim_overlap_with_superseded_finding(self) -> None:
        records = [
            attempt("attempt-2", "unrelated-claim"),
            finding("finding-1", "claim-1", "blocking", "critical", "2026-05-10T10:00:00Z"),
            finding(
                "finding-2",
                "unrelated-claim",
                "non_blocking",
                "low",
                "2026-05-10T10:10:00Z",
                supersedes="finding-1",
                linked_attempt_ids=["attempt-2"],
            ),
        ]

        status = blocking_finding_resolution_status(records)

        self.assertEqual(["finding-1"], [item["finding_id"] for item in status["unresolved"]])
        self.assertEqual([], status["resolved_by_supersede"])

    def test_supersede_requires_newer_finding_timestamp(self) -> None:
        records = [
            attempt("attempt-2", "claim-1"),
            finding("finding-1", "claim-1", "blocking", "critical", "2026-05-10T10:00:00Z"),
            finding(
                "finding-2",
                "claim-1",
                "non_blocking",
                "low",
                "2026-05-10T09:59:00Z",
                supersedes="finding-1",
                linked_attempt_ids=["attempt-2"],
            ),
        ]

        status = blocking_finding_resolution_status(records)

        self.assertEqual(["finding-1"], [item["finding_id"] for item in status["unresolved"]])
        self.assertEqual([], status["resolved_by_supersede"])

    def test_mixed_timezone_superseding_finding_does_not_resolve_or_crash(self) -> None:
        records = [
            {**attempt("attempt-2", "claim-1"), "timestamp": "2026-05-10T10:12:00Z"},
            finding("finding-1", "claim-1", "blocking", "critical", "2026-05-10T10:00:00Z"),
            finding(
                "finding-2",
                "claim-1",
                "non_blocking",
                "low",
                "2026-05-10T10:10:00",
                supersedes="finding-1",
                linked_attempt_ids=["attempt-2"],
            ),
        ]

        status = blocking_finding_resolution_status(records)

        self.assertEqual(["finding-1"], [item["finding_id"] for item in status["unresolved"]])
        self.assertEqual([], status["resolved_by_supersede"])

    def test_valid_supersede_with_fresh_evidence_resolves_blocking_finding(self) -> None:
        records = [
            attempt("attempt-2", "claim-1"),
            finding("finding-1", "claim-1", "blocking", "critical", "2026-05-10T10:00:00Z"),
            finding(
                "finding-2",
                "claim-1",
                "non_blocking",
                "low",
                "2026-05-10T10:10:00Z",
                supersedes="finding-1",
                linked_attempt_ids=["attempt-2"],
            ),
        ]

        status = blocking_finding_resolution_status(records)

        self.assertEqual([], status["unresolved"])
        self.assertEqual(["finding-1"], [item["finding_id"] for item in status["resolved_by_supersede"]])

    def test_supersede_requires_attempt_newer_than_superseded_finding(self) -> None:
        records = [
            {**attempt("attempt-2", "claim-1"), "timestamp": "2026-05-10T09:00:00Z"},
            finding("finding-1", "claim-1", "blocking", "critical", "2026-05-10T10:00:00Z"),
            finding(
                "finding-2",
                "claim-1",
                "non_blocking",
                "low",
                "2026-05-10T10:10:00Z",
                supersedes="finding-1",
                linked_attempt_ids=["attempt-2"],
            ),
        ]

        status = blocking_finding_resolution_status(records)

        self.assertEqual(["finding-1"], [item["finding_id"] for item in status["unresolved"]])

    def test_mixed_timezone_supersede_attempt_does_not_resolve_or_crash(self) -> None:
        records = [
            {**attempt("attempt-2", "claim-1"), "timestamp": "2026-05-10T10:12:00"},
            finding("finding-1", "claim-1", "blocking", "critical", "2026-05-10T10:00:00Z"),
            finding(
                "finding-2",
                "claim-1",
                "non_blocking",
                "low",
                "2026-05-10T10:10:00Z",
                supersedes="finding-1",
                linked_attempt_ids=["attempt-2"],
            ),
        ]

        status = blocking_finding_resolution_status(records)

        self.assertEqual(["finding-1"], [item["finding_id"] for item in status["unresolved"]])
        self.assertEqual([], status["resolved_by_supersede"])

    def test_non_string_receipt_cannot_support_supersede_attempt_evidence(self) -> None:
        records = [
            {**attempt("attempt-2", "claim-1"), "execution_receipts": [0]},
            finding("finding-1", "claim-1", "blocking", "critical", "2026-05-10T10:00:00Z"),
            finding(
                "finding-2",
                "claim-1",
                "non_blocking",
                "low",
                "2026-05-10T10:10:00Z",
                supersedes="finding-1",
                linked_attempt_ids=["attempt-2"],
            ),
        ]

        status = blocking_finding_resolution_status(records)

        self.assertEqual(["finding-1"], [item["finding_id"] for item in status["unresolved"]])
        self.assertEqual([], status["resolved_by_supersede"])

    def test_supersede_requires_attempt_claim_overlap_with_superseding_finding(self) -> None:
        records = [
            attempt("attempt-2", "claim-b"),
            {
                **finding("finding-1", "claim-a", "blocking", "critical", "2026-05-10T10:00:00Z"),
                "target_claims": ["claim-a", "claim-b"],
            },
            finding(
                "finding-2",
                "claim-a",
                "non_blocking",
                "low",
                "2026-05-10T10:10:00Z",
                supersedes="finding-1",
                linked_attempt_ids=["attempt-2"],
            ),
        ]

        status = blocking_finding_resolution_status(records)

        self.assertEqual(["finding-1"], [item["finding_id"] for item in status["unresolved"]])

if __name__ == "__main__":
    unittest.main()
