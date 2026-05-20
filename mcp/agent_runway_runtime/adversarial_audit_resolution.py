from __future__ import annotations

from typing import Any

from .adversarial_audit_common import (
    nonempty_string_list,
    parse_aware_time,
    parse_time,
    record_claims,
    scope_tokens,
)
from .adversarial_audit_schema import DISPOSITIONS


def unresolved_blockers(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return blocking_finding_resolution_status(records)["unresolved"]


def has_acceptance(
    finding: dict[str, Any],
    records: list[dict[str, Any]],
    after_timestamp: Any | None = None,
) -> bool:
    finding_id = _string_id(finding.get("finding_id"))
    finding_claims = record_claims(finding)
    if not finding_id or not finding_claims:
        return False
    freshness = after_timestamp or finding.get("timestamp")
    for record in _object_records(records):
        if record.get("record_type") != "audit_acceptance":
            continue
        accepted_scope = record.get("accepted_scope", "")
        if _string_id(record.get("linked_finding_id")) != finding_id or not accepted_scope:
            continue
        if not record.get("reason"):
            continue
        if not _newer_than(record.get("timestamp"), freshness):
            continue
        if finding_claims.intersection(scope_tokens(accepted_scope)):
            return True
    return False


def blocking_finding_resolution_status(records: list[dict[str, Any]]) -> dict[str, Any]:
    object_records = _object_records(records)
    findings = [r for r in object_records if r.get("record_type") == "audit_finding"]
    findings_by_id = _unique_records_by_id(findings, "finding_id")
    attempts_by_id = _unique_records_by_id(
        [r for r in object_records if r.get("record_type") == "audit_attempt"], "attempt_id"
    )
    superseded_ids = _valid_superseded_ids(findings, findings_by_id, attempts_by_id)
    updates_by_target = _updates_by_target(object_records)
    return _resolution_payload(findings, superseded_ids, updates_by_target, object_records)


def _valid_superseded_ids(
    findings: list[dict[str, Any]],
    findings_by_id: dict[str, dict[str, Any]],
    attempts_by_id: dict[str, dict[str, Any]],
) -> set[str]:
    superseded_ids: set[str] = set()
    for finding in findings:
        supersedes_id = _string_id(finding.get("supersedes_finding_id"))
        superseded = findings_by_id.get(supersedes_id)
        if supersedes_id and _valid_supersede(finding, superseded, attempts_by_id):
            superseded_ids.add(supersedes_id)
    return superseded_ids


def _updates_by_target(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    updates: dict[str, dict[str, Any]] = {}
    for record in records:
        if record.get("record_type") != "audit_update":
            continue
        target_id = _string_id(record.get("target_id"))
        if target_id and _is_newer_update(record, updates.get(target_id)):
            updates[target_id] = record
    return updates


def _resolution_payload(
    findings: list[dict[str, Any]],
    superseded_ids: set[str],
    updates_by_target: dict[str, dict[str, Any]],
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    unresolved: list[dict[str, Any]] = []
    resolved_by_acceptance: list[dict[str, Any]] = []
    resolved_by_supersede: list[dict[str, Any]] = []
    for finding in findings:
        status = _finding_status(finding, superseded_ids, updates_by_target, records)
        if status == "resolved_by_supersede":
            resolved_by_supersede.append(finding)
        elif status == "resolved_by_acceptance":
            resolved_by_acceptance.append(finding)
        elif status == "unresolved":
            unresolved.append(finding)
    return {
        "unresolved": unresolved,
        "resolved_by_acceptance": resolved_by_acceptance,
        "resolved_by_supersede": resolved_by_supersede,
    }


def _finding_status(
    finding: dict[str, Any],
    superseded_ids: set[str],
    updates_by_target: dict[str, dict[str, Any]],
    records: list[dict[str, Any]],
) -> str:
    finding_id = _string_id(finding.get("finding_id"))
    if finding_id in superseded_ids:
        return "resolved_by_supersede"
    disposition = finding.get("disposition")
    raw_update = updates_by_target.get(finding_id)
    update = _effective_update(finding, raw_update)
    has_any_update = raw_update is not None
    new_disposition = update.get("new_disposition") if update else None
    has_effective_update = new_disposition in DISPOSITIONS
    effective = new_disposition if new_disposition in DISPOSITIONS else disposition
    freshness = update.get("timestamp") if update else finding.get("timestamp")
    if effective == "accepted_residual_risk" and has_acceptance(finding, records, freshness):
        return "resolved_by_acceptance"
    if (
        disposition == "blocking"
        and not has_any_update
        and not has_effective_update
        and has_acceptance(finding, records, freshness)
    ):
        return "resolved_by_acceptance"
    return "unresolved" if disposition == "blocking" or effective == "blocking" else "resolved"


def _effective_update(
    finding: dict[str, Any], update: dict[str, Any] | None
) -> dict[str, Any] | None:
    if update is None:
        return None
    if not _newer_than(update.get("timestamp"), finding.get("timestamp")):
        return None
    return update


def _is_newer_update(candidate: dict[str, Any], current: dict[str, Any] | None) -> bool:
    if current is None:
        return True
    candidate_time = parse_aware_time(candidate.get("timestamp"))
    current_time = parse_aware_time(current.get("timestamp"))
    if candidate_time is None:
        return current_time is None
    if current_time is None:
        return True
    if candidate_time == current_time:
        return candidate.get("new_disposition") == "blocking"
    return candidate_time > current_time


def _valid_supersede(
    superseding: dict[str, Any],
    superseded: dict[str, Any] | None,
    attempts_by_id: dict[str, dict[str, Any]],
) -> bool:
    if superseded is None:
        return False
    if superseding.get("disposition") not in {"accepted_residual_risk", "false_positive", "non_blocking"}:
        return False
    claims = record_claims(superseded)
    superseding_claims = record_claims(superseding)
    shared_claims = claims.intersection(superseding_claims)
    if not claims or not shared_claims:
        return False
    if not _newer_than(superseding.get("timestamp"), superseded.get("timestamp")):
        return False
    return _has_supersede_attempt_evidence(superseding, superseded, shared_claims, attempts_by_id)


def _newer_than(new_value: Any, old_value: Any) -> bool:
    new_time = parse_aware_time(new_value)
    old_time = parse_aware_time(old_value)
    return new_time is not None and old_time is not None and new_time > old_time


def _has_supersede_attempt_evidence(
    superseding: dict[str, Any],
    superseded: dict[str, Any],
    claims: set[str],
    attempts_by_id: dict[str, dict[str, Any]],
) -> bool:
    linked_attempt_ids = superseding.get("linked_attempt_ids")
    if not isinstance(linked_attempt_ids, list):
        return False
    for attempt_id in linked_attempt_ids:
        attempt = attempts_by_id.get(_string_id(attempt_id))
        if not attempt or attempt.get("outcome") != "attack_failed":
            continue
        if not _newer_than(attempt.get("timestamp"), superseded.get("timestamp")):
            continue
        if nonempty_string_list(attempt.get("execution_receipts")) and claims.intersection(record_claims(attempt)):
            return True
    return False


def _unique_records_by_id(records: list[dict[str, Any]], id_field: str) -> dict[str, dict[str, Any]]:
    counts: dict[str, int] = {}
    for record in records:
        record_id = _string_id(record.get(id_field))
        if record_id:
            counts[record_id] = counts.get(record_id, 0) + 1
    return {
        _string_id(record.get(id_field)): record
        for record in records
        if counts.get(_string_id(record.get(id_field))) == 1
    }


def _string_id(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _object_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [record for record in records if isinstance(record, dict)]
