from __future__ import annotations

import sys
import unittest
from pathlib import Path

MCP_ROOT = Path(__file__).resolve().parents[1]
if str(MCP_ROOT) not in sys.path:
    sys.path.insert(0, str(MCP_ROOT))

from agent_runway_runtime.adversarial_audit import blocking_finding_resolution_status


class AdversarialAuditAcceptanceFreshnessEdgesTestCase(unittest.TestCase):
    def test_acceptance_older_than_finding_does_not_resolve_blocking_finding(self) -> None:
        records = [
            finding("finding-1", "claim-1", "blocking", "critical", "2026-05-10T10:00:00Z"),
            acceptance(
                "finding-1",
                "claim-1",
                "stale acceptance predates the finding",
                timestamp="2026-05-10T09:00:00Z",
            ),
        ]

        status = blocking_finding_resolution_status(records)

        self.assertEqual(["finding-1"], [item["finding_id"] for item in status["unresolved"]])

    def test_acceptance_older_than_effective_update_does_not_resolve(self) -> None:
        records = [
            finding("finding-1", "claim-1", "blocking", "critical", "2026-05-10T10:00:00Z"),
            {
                "record_type": "audit_update",
                "update_id": "update-1",
                "target_id": "finding-1",
                "reason": "fresh reclassification requires fresh acceptance",
                "new_disposition": "accepted_residual_risk",
                "timestamp": "2026-05-10T10:10:00Z",
            },
            acceptance(
                "finding-1",
                "claim-1",
                "acceptance predates the reclassification",
                timestamp="2026-05-10T10:05:00Z",
            ),
        ]

        status = blocking_finding_resolution_status(records)

        self.assertEqual(["finding-1"], [item["finding_id"] for item in status["unresolved"]])

    def test_equal_timestamp_conflicting_updates_fail_closed(self) -> None:
        records = [
            finding("finding-1", "claim-1", "blocking", "critical", "2026-05-10T10:00:00Z"),
            {
                "record_type": "audit_update",
                "update_id": "update-accepted",
                "target_id": "finding-1",
                "reason": "same-time accepted state",
                "new_disposition": "accepted_residual_risk",
                "timestamp": "2026-05-10T10:10:00Z",
            },
            acceptance("finding-1", "claim-1", "fresh acceptance"),
            {
                "record_type": "audit_update",
                "update_id": "update-blocking",
                "target_id": "finding-1",
                "reason": "same-time blocking state",
                "new_disposition": "blocking",
                "timestamp": "2026-05-10T10:10:00Z",
            },
        ]

        status = blocking_finding_resolution_status(records)

        self.assertEqual(["finding-1"], [item["finding_id"] for item in status["unresolved"]])

    def test_mixed_timezone_acceptance_does_not_resolve_or_crash(self) -> None:
        records = [
            finding("finding-1", "claim-1", "blocking", "critical", "2026-05-10T10:00:00Z"),
            acceptance("finding-1", "claim-1", "naive timestamp", timestamp="2026-05-10T10:12:00"),
        ]

        status = blocking_finding_resolution_status(records)

        self.assertEqual(["finding-1"], [item["finding_id"] for item in status["unresolved"]])

    def test_mixed_timezone_update_does_not_resolve_or_crash(self) -> None:
        records = [
            finding("finding-1", "claim-1", "blocking", "critical", "2026-05-10T10:00:00Z"),
            {
                "record_type": "audit_update",
                "update_id": "update-1",
                "target_id": "finding-1",
                "reason": "naive timestamp must not override aware finding timestamp",
                "new_disposition": "accepted_residual_risk",
                "timestamp": "2026-05-10T10:10:00",
            },
            acceptance("finding-1", "claim-1", "acceptance after naive update"),
        ]

        status = blocking_finding_resolution_status(records)

        self.assertEqual(["finding-1"], [item["finding_id"] for item in status["unresolved"]])

    def test_naive_update_does_not_replace_aware_update_by_list_order(self) -> None:
        records = [
            finding("finding-1", "claim-1", "blocking", "critical", "2026-05-10T10:00:00Z"),
            {
                "record_type": "audit_update",
                "update_id": "update-aware",
                "target_id": "finding-1",
                "reason": "aware blocking update should remain authoritative",
                "new_disposition": "blocking",
                "timestamp": "2026-05-10T10:10:00Z",
            },
            {
                "record_type": "audit_update",
                "update_id": "update-naive",
                "target_id": "finding-1",
                "reason": "naive accepted update must not replace aware update",
                "new_disposition": "accepted_residual_risk",
                "timestamp": "2026-05-10T10:12:00",
            },
            acceptance("finding-1", "claim-1", "acceptance after naive update"),
        ]

        status = blocking_finding_resolution_status(records)

        self.assertEqual(["finding-1"], [item["finding_id"] for item in status["unresolved"]])

    def test_non_string_claim_does_not_match_acceptance_scope(self) -> None:
        blocker = finding("finding-1", "claim-1", "blocking", "critical", "2026-05-10T10:00:00Z")
        blocker["target_claims"] = [0]

        status = blocking_finding_resolution_status(
            [blocker, acceptance("finding-1", "0", "numeric claim value must not be stringified")]
        )

        self.assertEqual(["finding-1"], [item["finding_id"] for item in status["unresolved"]])

    def test_non_string_acceptance_scope_does_not_match_claim(self) -> None:
        acceptance_record = acceptance("finding-1", "0", "numeric scope must not be stringified")
        acceptance_record["accepted_scope"] = 0

        status = blocking_finding_resolution_status(
            [finding("finding-1", "0", "blocking", "critical", "2026-05-10T10:00:00Z"), acceptance_record]
        )

        self.assertEqual(["finding-1"], [item["finding_id"] for item in status["unresolved"]])


def finding(
    finding_id: str,
    claim: str,
    disposition: str,
    severity: str,
    timestamp: str,
) -> dict[str, object]:
    return {
        "record_type": "audit_finding",
        "finding_id": finding_id,
        "severity": severity,
        "disposition": disposition,
        "linked_attempt_ids": ["attempt-1"],
        "target_claims": [claim],
        "required_action": "fix or document the risk",
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
