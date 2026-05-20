from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path

MCP_ROOT = Path(__file__).resolve().parents[1]
if str(MCP_ROOT) not in sys.path:
    sys.path.insert(0, str(MCP_ROOT))

from agent_runway_runtime.adversarial_audit import blocking_finding_resolution_status
from test_adversarial_audit import audit_attempt, audit_plan, finding


class AdversarialAuditTypeEdgesTestCase(unittest.TestCase):
    def test_non_string_receipts_do_not_satisfy_attempt_evidence(self) -> None:
        audit = importlib.import_module("agent_runway_runtime.adversarial_audit")
        attempt = audit_attempt("attack_failed")
        attempt["execution_receipts"] = [0]

        issues = "\n".join(audit.lint_records([audit_plan(), attempt]))

        self.assertIn("audit_attempt with attack outcome requires execution_receipts", issues)

    def test_required_claim_is_not_satisfied_by_non_string_receipt(self) -> None:
        audit = importlib.import_module("agent_runway_runtime.adversarial_audit")
        attempt = audit_attempt("attack_failed")
        attempt["execution_receipts"] = [0]

        issues = audit.gate_violations(
            [audit_plan(), attempt, finding("non_blocking")],
            ["runtime_gate_adversary"],
            ["completion gate rejects stale receipts"],
            3,
        )

        self.assertTrue(any("missing required adversarial profiles" in issue for issue in issues))
        self.assertTrue(any("missing adversarial coverage for claims" in issue for issue in issues))

    def test_non_string_receipt_cannot_support_blocking_finding(self) -> None:
        audit = importlib.import_module("agent_runway_runtime.adversarial_audit")
        attempt = audit_attempt("attack_succeeded")
        attempt["execution_receipts"] = [0]

        issues = "\n".join(audit.lint_records([audit_plan(), attempt, finding("blocking", "high")]))

        self.assertIn("blocking finding requires executable evidence", issues)

    def test_required_claim_is_not_satisfied_by_non_string_claim_value(self) -> None:
        audit = importlib.import_module("agent_runway_runtime.adversarial_audit")
        attempt = audit_attempt("attack_failed")
        attempt["target_claims"] = [0]

        issues = audit.gate_violations([audit_plan(), attempt, finding("non_blocking")], [], ["0"], 3)

        self.assertTrue(any("missing adversarial coverage for claims" in issue for issue in issues))

    def test_lint_reports_non_string_claim_values_precisely(self) -> None:
        audit = importlib.import_module("agent_runway_runtime.adversarial_audit")
        attempt = audit_attempt("attack_failed")
        attempt["target_claims"] = [0]
        blocker = finding("blocking", "high")
        blocker["affected_claims"] = [False]

        issues = audit.lint_records([audit_plan(), attempt, blocker])

        self.assertIn("target_claims entries must be non-empty strings", issues)
        self.assertIn("affected_claims entries must be non-empty strings", issues)

    def test_lint_reports_non_string_acceptance_scope_precisely(self) -> None:
        audit = importlib.import_module("agent_runway_runtime.adversarial_audit")
        acceptance = {
            "record_type": "audit_acceptance",
            "acceptance_id": "acceptance-1",
            "linked_finding_id": "finding-blocking",
            "accepted_scope": 0,
            "reason": "numeric scope must be rejected",
            "timestamp": "2026-05-09T00:00:03Z",
        }

        issues = audit.lint_records([audit_plan(), audit_attempt("attack_succeeded"), finding("blocking", "high"), acceptance])

        self.assertIn("audit_acceptance requires accepted_scope", issues)

    def test_project_learning_with_non_string_receipt_still_cannot_satisfy_evidence(self) -> None:
        audit = importlib.import_module("agent_runway_runtime.adversarial_audit")
        seeded_attempt = audit_attempt("attack_succeeded")
        seeded_attempt["execution_receipts"] = [0]
        seeded_attempt["source_refs"] = [{"kind": "project_learning", "use": "seed_only"}]

        issues = "\n".join(audit.lint_records([audit_plan(), seeded_attempt, finding("blocking", "high")]))

        self.assertIn("Project Learning Ledger cannot satisfy adversarial evidence", issues)

    def test_non_string_supersedes_id_does_not_resolve_string_finding(self) -> None:
        status = blocking_finding_resolution_status(
            [
                resolution_attempt("attempt-2"),
                resolution_finding("123", "claim-1", "blocking", "critical"),
                resolution_finding(
                    "finding-2",
                    "claim-1",
                    "non_blocking",
                    "low",
                    supersedes=123,
                    linked_attempt_ids=["attempt-2"],
                ),
            ]
        )

        self.assertEqual(["123"], [item["finding_id"] for item in status["unresolved"]])

    def test_non_string_update_target_id_does_not_resolve_string_finding(self) -> None:
        status = blocking_finding_resolution_status(
            [
                resolution_finding("123", "claim-1", "blocking", "critical"),
                {
                    "record_type": "audit_update",
                    "update_id": "update-1",
                    "target_id": 123,
                    "new_disposition": "non_blocking",
                    "reason": "numeric target id must not resolve string finding",
                    "timestamp": "2026-05-10T10:11:00Z",
                },
            ]
        )

        self.assertEqual(["123"], [item["finding_id"] for item in status["unresolved"]])

    def test_non_string_linked_attempt_id_does_not_support_supersede_evidence(self) -> None:
        status = blocking_finding_resolution_status(
            [
                resolution_attempt("0"),
                resolution_finding("finding-1", "claim-1", "blocking", "critical"),
                resolution_finding(
                    "finding-2",
                    "claim-1",
                    "non_blocking",
                    "low",
                    supersedes="finding-1",
                    linked_attempt_ids=[0],
                ),
            ]
        )

        self.assertEqual(["finding-1"], [item["finding_id"] for item in status["unresolved"]])

    def test_non_string_finding_id_does_not_resolve_by_acceptance(self) -> None:
        blocker = resolution_finding(0, "claim-1", "blocking", "critical")
        acceptance = {
            "record_type": "audit_acceptance",
            "acceptance_id": "acceptance-1",
            "linked_finding_id": 0,
            "accepted_scope": "claim-1",
            "reason": "numeric finding id must not resolve",
            "timestamp": "2026-05-10T10:12:00Z",
        }

        status = blocking_finding_resolution_status([blocker, acceptance])

        self.assertEqual([0], [item["finding_id"] for item in status["unresolved"]])

    def test_duplicate_attempt_ids_do_not_support_supersede_evidence(self) -> None:
        status = blocking_finding_resolution_status(
            [
                resolution_attempt("attempt-2", claim="unrelated-claim"),
                resolution_attempt("attempt-2", claim="claim-1"),
                resolution_finding("finding-1", "claim-1", "blocking", "critical"),
                resolution_finding(
                    "finding-2",
                    "claim-1",
                    "non_blocking",
                    "low",
                    supersedes="finding-1",
                    linked_attempt_ids=["attempt-2"],
                ),
            ]
        )

        self.assertEqual(["finding-1"], [item["finding_id"] for item in status["unresolved"]])

    def test_duplicate_finding_ids_do_not_get_superseded_together(self) -> None:
        status = blocking_finding_resolution_status(
            [
                resolution_attempt("attempt-2"),
                resolution_finding("finding-1", "claim-1", "blocking", "critical"),
                resolution_finding("finding-1", "claim-1", "blocking", "critical"),
                resolution_finding(
                    "finding-2",
                    "claim-1",
                    "non_blocking",
                    "low",
                    supersedes="finding-1",
                    linked_attempt_ids=["attempt-2"],
                ),
            ]
        )

        self.assertEqual(["finding-1", "finding-1"], [item["finding_id"] for item in status["unresolved"]])

    def test_lint_reports_non_string_id_and_link_fields_precisely(self) -> None:
        audit = importlib.import_module("agent_runway_runtime.adversarial_audit")
        attempt = audit_attempt("attack_failed")
        attempt["attempt_id"] = 0
        blocker = finding("blocking", "high")
        blocker["linked_attempt_ids"] = [0]
        acceptance = {
            "record_type": "audit_acceptance",
            "acceptance_id": "acceptance-1",
            "linked_finding_id": 0,
            "accepted_scope": "completion gate rejects stale receipts",
            "reason": "numeric linked finding id must be rejected",
            "timestamp": "2026-05-09T00:00:03Z",
        }

        issues = audit.lint_records([audit_plan(), attempt, blocker, acceptance])

        self.assertIn("audit_attempt requires string attempt_id", issues)
        self.assertIn("audit_finding linked_attempt_ids entries must be non-empty strings", issues)
        self.assertIn("audit_acceptance requires string linked_finding_id", issues)

    def test_lint_reports_non_string_resolution_links_precisely(self) -> None:
        audit = importlib.import_module("agent_runway_runtime.adversarial_audit")
        blocker = finding("blocking", "high")
        blocker["finding_id"] = 0
        superseding = finding("non_blocking", "low")
        superseding["supersedes_finding_id"] = 0
        update = {
            "record_type": "audit_update",
            "update_id": "update-1",
            "target_id": 0,
            "reason": "numeric target id must be rejected",
            "timestamp": "2026-05-09T00:00:03Z",
        }
        disposition = {
            "record_type": "audit_disposition",
            "disposition_id": 0,
        }

        issues = audit.lint_records(
            [audit_plan(), audit_attempt("attack_succeeded"), blocker, superseding, update, disposition]
        )

        self.assertIn("audit_finding requires string finding_id", issues)
        self.assertIn("audit_finding requires string supersedes_finding_id", issues)
        self.assertIn("audit_update requires string target_id", issues)
        self.assertIn("audit_disposition requires string disposition_id", issues)


def resolution_attempt(attempt_id: object, claim: str = "claim-1") -> dict[str, object]:
    return {
        "record_type": "audit_attempt",
        "attempt_id": attempt_id,
        "outcome": "attack_failed",
        "execution_receipts": [f"receipt-{attempt_id}"],
        "target_claims": [claim],
        "timestamp": "2026-05-10T10:12:00Z",
    }


def resolution_finding(
    finding_id: object,
    claim: str,
    disposition: str,
    severity: str,
    supersedes: object = "",
    linked_attempt_ids: list[object] | None = None,
) -> dict[str, object]:
    record: dict[str, object] = {
        "record_type": "audit_finding",
        "finding_id": finding_id,
        "severity": severity,
        "disposition": disposition,
        "linked_attempt_ids": linked_attempt_ids or [],
        "target_claims": [claim],
        "required_action": "fix or document the risk",
        "timestamp": "2026-05-10T10:00:00Z" if disposition == "blocking" else "2026-05-10T10:10:00Z",
    }
    if supersedes != "":
        record["supersedes_finding_id"] = supersedes
    return record


if __name__ == "__main__":
    unittest.main()
