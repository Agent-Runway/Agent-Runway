from __future__ import annotations

import sys
import unittest
from pathlib import Path

MCP_ROOT = Path(__file__).resolve().parents[1]
if str(MCP_ROOT) not in sys.path:
    sys.path.insert(0, str(MCP_ROOT))

from agent_runway_runtime.adversarial_audit import (  # noqa: E402
    blocking_finding_resolution_status,
    budget_usage,
    has_acceptance,
    summarize,
)


class AdversarialAuditDirectHelperEdgesTestCase(unittest.TestCase):
    def test_has_acceptance_ignores_non_object_records(self) -> None:
        self.assertFalse(has_acceptance(finding(), [["not", "an", "object"]]))  # type: ignore[list-item]

    def test_direct_supersede_requires_list_linked_attempt_ids(self) -> None:
        status = blocking_finding_resolution_status(
            [
                attempt("a"),
                finding("finding-1"),
                finding("finding-2", disposition="non_blocking", supersedes="finding-1", linked_attempt_ids="a"),
            ]
        )

        self.assertEqual(["finding-1"], [item["finding_id"] for item in status["unresolved"]])

    def test_direct_supersede_rejects_unknown_disposition(self) -> None:
        status = blocking_finding_resolution_status(
            [
                attempt("attempt-2"),
                finding("finding-1"),
                finding(
                    "finding-2",
                    disposition="unknown_disposition",
                    supersedes="finding-1",
                    linked_attempt_ids=["attempt-2"],
                ),
            ]
        )

        self.assertEqual(["finding-1"], [item["finding_id"] for item in status["unresolved"]])

    def test_direct_supersede_rejects_needs_reproduction_disposition(self) -> None:
        status = blocking_finding_resolution_status(
            [
                attempt("attempt-2"),
                finding("finding-1"),
                finding(
                    "finding-2",
                    disposition="needs_reproduction",
                    supersedes="finding-1",
                    linked_attempt_ids=["attempt-2"],
                ),
            ]
        )

        self.assertEqual(["finding-1"], [item["finding_id"] for item in status["unresolved"]])

    def test_budget_usage_ignores_non_object_records(self) -> None:
        usage = budget_usage([audit_plan(), ["not", "an", "object"], attempt("attempt-1")], budget())  # type: ignore[list-item]

        self.assertEqual(1, usage["hypotheses_used"])
        self.assertEqual(1, usage["attacks_used"])

    def test_budget_usage_non_string_attempt_id_uses_payload_key(self) -> None:
        first = attempt(0)
        duplicate_payload = attempt(False)
        duplicate_payload["hypothesis"] = first["hypothesis"]
        duplicate_payload["execution_receipts"] = first["execution_receipts"]

        usage = budget_usage([audit_plan(), first, duplicate_payload], budget())

        self.assertEqual(1, usage["hypotheses_used"])
        self.assertEqual(1, usage["attacks_used"])

    def test_summarize_counts_non_object_records_as_malformed(self) -> None:
        summary = summarize([finding("finding-1"), ["not", "an", "object"]])  # type: ignore[list-item]

        self.assertEqual(1, summary["counts"]["malformed_record"])
        self.assertFalse(summary["passed"])


def audit_plan() -> dict[str, object]:
    return {
        "record_type": "audit_plan",
        "plan_id": "plan-1",
        "freshness_baseline": {"latest_receipt_seq": 0, "timestamp": "2026-05-10T10:00:00Z"},
    }


def attempt(attempt_id: object, claim: str = "claim-1") -> dict[str, object]:
    return {
        "record_type": "audit_attempt",
        "attempt_id": attempt_id,
        "profile": "runtime_gate_adversary",
        "attack_type": "stale_evidence",
        "hypothesis": "same hypothesis",
        "outcome": "attack_failed",
        "execution_receipts": ["receipt-1"],
        "target_claims": [claim],
        "timestamp": "2026-05-10T10:12:00Z",
    }


def finding(
    finding_id: object = "finding-1",
    disposition: str = "blocking",
    supersedes: object = "",
    linked_attempt_ids: object | None = None,
) -> dict[str, object]:
    record = {
        "record_type": "audit_finding",
        "finding_id": finding_id,
        "severity": "critical",
        "disposition": disposition,
        "linked_attempt_ids": linked_attempt_ids if linked_attempt_ids is not None else [],
        "target_claims": ["claim-1"],
        "required_action": "fix or document the risk",
        "timestamp": "2026-05-10T10:00:00Z" if disposition == "blocking" else "2026-05-10T10:10:00Z",
    }
    if supersedes != "":
        record["supersedes_finding_id"] = supersedes
    return record


def budget() -> dict[str, int]:
    return {
        "max_hypotheses": 5,
        "max_executable_attacks": 5,
        "max_runtime_seconds": 300,
    }
