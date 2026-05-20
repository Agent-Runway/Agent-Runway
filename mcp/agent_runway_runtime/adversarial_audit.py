from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .adversarial_audit_budgeting import _fresh_billable_attempts, audit_stop_gate, budget_usage
from .adversarial_audit_common import nonempty_list, nonempty_string_list, parse_time, record_claims
from .adversarial_audit_resolution import (
    blocking_finding_resolution_status,
    has_acceptance,
    unresolved_blockers,
)
from .adversarial_audit_plan_edges import (
    has_parseable_baseline_timestamp,
    latest_receipt_seq_baselines,
    lint_attempt_plan_id,
    lint_freshness_baseline,
    lint_record_ids,
    lint_timestamp_timezone,
    records_for_known_plans,
)
from .adversarial_audit_reading import read_records
from .adversarial_audit_schema import (
    ATTACK_TYPES,
    BANNED_PHRASES,
    BLOCKING_SEVERITIES,
    BUDGET_FIELDS,
    DESTRUCTIVE_PATTERNS,
    DISPOSITIONS,
    PROFILES,
    RECORD_TYPES,
    SECRET_PATTERNS,
    SEVERITIES,
)
from .detection_text import strip_invisible_controls_deep


def lint_records(records: list[dict[str, Any]]) -> list[str]:
    issues: list[str] = []
    ids = _index(records, issues)
    for record in records:
        if not isinstance(record, dict):
            continue
        _lint_record(record, records, ids, issues)
    return issues


def gate_violations(
    records: list[dict[str, Any]],
    required_profiles: list[str],
    required_claims: list[str],
    latest_receipt_seq: int,
) -> list[str]:
    issues = lint_records(records)
    plans = [r for r in _object_records(records) if r.get("record_type") == "audit_plan"]
    if not plans:
        issues.append("adversarial audit required but no audit_plan was provided")
        return issues
    fresh_attempts = _fresh_billable_attempts(records_for_known_plans(records, plans), plans)
    _check_required_profiles(fresh_attempts, required_profiles, issues)
    _check_required_claims(fresh_attempts, required_claims, issues)
    _check_freshness(plans, latest_receipt_seq, issues)
    if issues:
        return issues
    resolution_status = blocking_finding_resolution_status(records)
    for item in resolution_status["unresolved"]:
        issues.append(
            f"unresolved blocking adversarial finding {item.get('finding_id')}: {item.get('required_action', '')}"
        )
    return issues


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    blockers = unresolved_blockers(records)
    for record in records:
        key = "malformed_record" if not isinstance(record, dict) else str(record.get("disposition") or record.get("record_type"))
        counts[key] = counts.get(key, 0) + 1
    return {
        "record_count": len(records),
        "counts": counts,
        "unresolved_blockers": [item.get("finding_id") for item in blockers],
        "passed": not blockers and not lint_records(records),
    }


def _index(records: list[dict[str, Any]], issues: list[str]) -> dict[str, dict[str, Any]]:
    ids: dict[str, dict[str, Any]] = {}
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            issues.append(f"record {index} must be an object")
            continue
        record_id = _record_id(record)
        if record_id:
            if record_id in ids:
                issues.append(f"duplicate audit record id: {record_id}")
            ids[record_id] = record
    return ids


def _object_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [record for record in records if isinstance(record, dict)]


def _record_id(record: dict[str, Any]) -> str:
    record_type = record.get("record_type")
    id_key = {
        "audit_plan": "plan_id",
        "audit_attempt": "attempt_id",
        "audit_finding": "finding_id",
        "audit_disposition": "disposition_id",
        "audit_acceptance": "acceptance_id",
        "audit_update": "update_id",
    }.get(str(record_type))
    value = record.get(id_key or "")
    if isinstance(value, str) and value.strip():
        return value
    return ""


def _lint_record(
    record: dict[str, Any], records: list[dict[str, Any]], ids: dict[str, dict[str, Any]], issues: list[str]
) -> None:
    record_type = record.get("record_type")
    if record_type not in RECORD_TYPES:
        issues.append(f"unknown audit record_type: {record_type!r}")
        return
    _lint_text(record, issues)
    _lint_record_timestamp(record, issues)
    lint_record_ids(record, issues)
    _lint_claim_fields(record, issues)
    if record_type == "audit_plan":
        _lint_plan(record, issues)
    if record_type == "audit_attempt":
        _lint_attempt(record, ids, issues)
    if record_type == "audit_finding":
        _lint_finding(record, records, ids, issues)
    if record_type == "audit_acceptance":
        _lint_acceptance(record, issues)
    if record_type == "audit_update":
        _lint_update(record, ids, issues)


def _lint_plan(record: dict[str, Any], issues: list[str]) -> None:
    scope = record.get("audit_scope") if isinstance(record.get("audit_scope"), dict) else {}
    budget = record.get("audit_budget") if isinstance(record.get("audit_budget"), dict) else {}
    baseline = record.get("freshness_baseline") or {}
    for field in ("target_claims", "target_files", "allowed_attack_types", "excluded_actions"):
        if not _nonempty_list(scope.get(field)):
            issues.append(f"audit_plan requires audit_scope.{field}")
    for field in _budget_fields():
        if not isinstance(budget.get(field), int) or budget.get(field) < 1:
            issues.append(f"audit_plan requires audit_budget.{field} >= 1")
    lint_freshness_baseline(baseline, issues)
    if not has_parseable_baseline_timestamp(baseline):
        issues.append("audit_plan requires parseable freshness_baseline.timestamp")
    elif isinstance(baseline, dict):
        lint_timestamp_timezone(baseline.get("timestamp"), issues)
    for profile in record.get("profiles_required", []):
        if profile not in PROFILES:
            issues.append(f"unknown adversarial profile: {profile}")
    for attack in scope.get("allowed_attack_types", []):
        if attack not in ATTACK_TYPES:
            issues.append(f"unknown attack_type in audit_scope: {attack}")


def _lint_record_timestamp(record: dict[str, Any], issues: list[str]) -> None:
    if "timestamp" in record:
        lint_timestamp_timezone(record.get("timestamp"), issues)


def _lint_claim_fields(record: dict[str, Any], issues: list[str]) -> None:
    for field in ("target_claims", "affected_claims"):
        if field in record and not _string_list(record.get(field)):
            issues.append(f"{field} entries must be non-empty strings")


def _lint_attempt(record: dict[str, Any], ids: dict[str, dict[str, Any]], issues: list[str]) -> None:
    attack_type = record.get("attack_type")
    outcome = record.get("outcome")
    receipts = record.get("execution_receipts") or []
    if attack_type not in ATTACK_TYPES:
        issues.append(f"unknown attack_type: {attack_type}")
    if record.get("profile") not in PROFILES:
        issues.append(f"unknown adversarial profile: {record.get('profile')}")
    lint_attempt_plan_id(record, ids, issues)
    if outcome in {"attack_succeeded", "attack_failed"} and not _nonempty_receipts(receipts):
        issues.append("audit_attempt with attack outcome requires execution_receipts")
    if outcome in {"attack_succeeded", "attack_failed"} and parse_time(record.get("timestamp")) is None:
        issues.append("audit_attempt with attack outcome requires parseable timestamp")
    if _uses_project_learning(record) and not _nonempty_receipts(receipts):
        issues.append("Project Learning Ledger cannot satisfy adversarial evidence")


def _lint_finding(
    record: dict[str, Any], records: list[dict[str, Any]], ids: dict[str, dict[str, Any]], issues: list[str]
) -> None:
    severity = str(record.get("severity", ""))
    disposition = str(record.get("disposition", ""))
    if severity not in SEVERITIES:
        issues.append(f"unknown severity: {severity}")
    if disposition not in DISPOSITIONS:
        issues.append(f"unknown disposition: {disposition}")
    if disposition == "blocking":
        _lint_blocking(record, ids, severity, issues)
    if disposition == "accepted_residual_risk" and not _has_acceptance(record, records):
        issues.append("accepted_residual_risk requires scoped audit_acceptance record")


def _lint_blocking(record: dict[str, Any], ids: dict[str, dict[str, Any]], severity: str, issues: list[str]) -> None:
    if severity not in BLOCKING_SEVERITIES:
        issues.append("blocking finding requires critical/high severity")
    attempts = [ids.get(item) for item in record.get("linked_attempt_ids", []) if isinstance(item, str)]
    has_evidence = any(
        attempt and attempt.get("outcome") == "attack_succeeded" and nonempty_string_list(attempt.get("execution_receipts"))
        for attempt in attempts
    )
    if not has_evidence:
        issues.append("blocking finding requires executable evidence from a successful attempt")


def _lint_acceptance(record: dict[str, Any], issues: list[str]) -> None:
    if not isinstance(record.get("accepted_scope"), str) or not record.get("accepted_scope", "").strip():
        issues.append("audit_acceptance requires accepted_scope")
    if not str(record.get("reason", "")).strip():
        issues.append("audit_acceptance requires reason")
    normalized_record = strip_invisible_controls_deep(record)
    if "authorize" in json.dumps(normalized_record, ensure_ascii=False).lower():
        issues.append("audit_acceptance must not be used as authorization")


def _lint_update(record: dict[str, Any], ids: dict[str, dict[str, Any]], issues: list[str]) -> None:
    if record.get("target_id") not in ids:
        issues.append(f"audit_update targets unknown record: {record.get('target_id')}")
    if not str(record.get("reason", "")).strip():
        issues.append("audit_update requires reason")
    if "new_disposition" in record and record.get("new_disposition") not in DISPOSITIONS:
        issues.append(f"unknown new_disposition: {record.get('new_disposition')}")


def _lint_text(record: dict[str, Any], issues: list[str]) -> None:
    scan_record = dict(strip_invisible_controls_deep(record))
    if isinstance(scan_record.get("audit_scope"), dict):
        scan_record["audit_scope"] = dict(scan_record["audit_scope"])
        scan_record["audit_scope"].pop("excluded_actions", None)
    text = json.dumps(scan_record, ensure_ascii=False).lower()
    if any(phrase in text for phrase in BANNED_PHRASES):
        issues.append("banned proof-of-safety phrase in audit record")
    if any(pattern.search(text) for pattern in SECRET_PATTERNS):
        issues.append("secret-like material in audit record")
    if any(pattern in text for pattern in DESTRUCTIVE_PATTERNS):
        issues.append("destructive or disallowed command in audit record")


def _check_required_profiles(attempts: list[dict[str, Any]], required: list[str], issues: list[str]) -> None:
    covered = {attempt.get("profile") for attempt in attempts}
    missing = [profile for profile in required if profile not in covered]
    if missing:
        issues.append(f"missing required adversarial profiles: {missing}")


def _check_required_claims(attempts: list[dict[str, Any]], required: list[str], issues: list[str]) -> None:
    covered = {
        claim
        for attempt in attempts
        for claim in record_claims(attempt)
    }
    missing = [claim for claim in required if claim not in covered]
    if missing:
        issues.append(f"missing adversarial coverage for claims: {missing}")


def _check_freshness(plans: list[dict[str, Any]], latest_seq: int, issues: list[str]) -> None:
    baselines = latest_receipt_seq_baselines(plans)
    future = [seq for seq in baselines if seq > latest_seq]
    if future:
        issues.append(
            f"audit_plan freshness_baseline.latest_receipt_seq cannot exceed latest receipt seq {latest_seq}: {future}"
        )
    if baselines and max(baselines) < latest_seq:
        issues.append(f"adversarial audit coverage is stale after receipt seq {latest_seq}")


def _budget_fields() -> tuple[str, ...]:
    return BUDGET_FIELDS


def _nonempty_list(value: Any) -> bool:
    return nonempty_list(value)


def _nonempty_receipts(value: Any) -> bool:
    return nonempty_string_list(value)


def _string_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) and item.strip() for item in value)


def _uses_project_learning(record: dict[str, Any]) -> bool:
    return "project_learning" in json.dumps(record.get("source_refs", []), ensure_ascii=False)


def _has_acceptance(finding: dict[str, Any], records: list[dict[str, Any]]) -> bool:
    return has_acceptance(finding, records)
