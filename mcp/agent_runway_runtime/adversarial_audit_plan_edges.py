from __future__ import annotations

from typing import Any

from .adversarial_audit_common import has_timezone, parse_time


def lint_freshness_baseline(
    baseline: Any, issues: list[str], latest_receipt_seq: int | None = None
) -> None:
    if not isinstance(baseline, dict):
        return
    seq = baseline.get("latest_receipt_seq")
    if not isinstance(seq, int) or isinstance(seq, bool):
        issues.append("audit_plan requires integer freshness_baseline.latest_receipt_seq")
    elif seq < 0:
        issues.append("audit_plan requires freshness_baseline.latest_receipt_seq >= 0")
    elif latest_receipt_seq is not None and seq > latest_receipt_seq:
        issues.append(
            "audit_plan freshness_baseline.latest_receipt_seq cannot exceed "
            f"latest receipt seq {latest_receipt_seq}: {seq}"
        )


def lint_attempt_plan_id(
    record: dict[str, Any], ids: dict[str, dict[str, Any]], issues: list[str]
) -> None:
    plan_value = record.get("plan_id")
    plan_id = plan_value.strip() if isinstance(plan_value, str) else ""
    if not plan_id:
        issue = "audit_attempt requires string plan_id" if "plan_id" in record else "audit_attempt requires plan_id"
        issues.append(issue)
    elif plan_id not in ids or ids[plan_id].get("record_type") != "audit_plan":
        issues.append(f"audit_attempt targets unknown audit plan_id: {plan_id}")


def lint_record_ids(record: dict[str, Any], issues: list[str]) -> None:
    record_type = record.get("record_type")
    id_field = _id_field(record_type)
    if id_field and id_field in record and not _string_value(record.get(id_field)):
        issues.append(f"{record_type} requires string {id_field}")
    _lint_link_fields(record, issues)


def records_for_known_plans(
    records: list[dict[str, Any]], plans: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    plan_ids: set[str] = set()
    for plan in plans:
        plan_id = _string_id(plan.get("plan_id"))
        if plan_id:
            plan_ids.add(plan_id)
    return [record for record in records if _uses_known_plan(record, plan_ids)]


def latest_receipt_seq_baselines(plans: list[dict[str, Any]]) -> list[int]:
    baselines = []
    for plan in plans:
        baseline = plan.get("freshness_baseline") or {}
        seq = baseline.get("latest_receipt_seq") if isinstance(baseline, dict) else None
        if isinstance(seq, int) and not isinstance(seq, bool):
            baselines.append(seq)
    return baselines


def has_parseable_baseline_timestamp(baseline: Any) -> bool:
    return isinstance(baseline, dict) and parse_time(baseline.get("timestamp")) is not None


def lint_timestamp_timezone(value: Any, issues: list[str]) -> None:
    if parse_time(value) is not None and not has_timezone(value):
        issues.append("audit timestamp values must include timezone offsets")


def _uses_known_plan(record: dict[str, Any], plan_ids: set[str]) -> bool:
    if not isinstance(record, dict):
        return False
    if record.get("record_type") != "audit_attempt":
        return True
    plan_id = _string_id(record.get("plan_id"))
    return bool(plan_id) and plan_id in plan_ids


def _id_field(record_type: Any) -> str:
    return {
        "audit_plan": "plan_id",
        "audit_attempt": "attempt_id",
        "audit_finding": "finding_id",
        "audit_disposition": "disposition_id",
        "audit_acceptance": "acceptance_id",
        "audit_update": "update_id",
    }.get(str(record_type), "")


def _lint_link_fields(record: dict[str, Any], issues: list[str]) -> None:
    record_type = record.get("record_type")
    if record_type == "audit_finding":
        if "linked_attempt_ids" in record and not _string_list(record.get("linked_attempt_ids")):
            issues.append("audit_finding linked_attempt_ids entries must be non-empty strings")
        if "supersedes_finding_id" in record and not _string_value(record.get("supersedes_finding_id")):
            issues.append("audit_finding requires string supersedes_finding_id")
    if record_type == "audit_acceptance" and "linked_finding_id" in record:
        if not _string_value(record.get("linked_finding_id")):
            issues.append("audit_acceptance requires string linked_finding_id")
    if record_type == "audit_update" and "target_id" in record:
        if not _string_value(record.get("target_id")):
            issues.append("audit_update requires string target_id")


def _string_value(value: Any) -> bool:
    return bool(_string_id(value))


def _string_id(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _string_list(value: Any) -> bool:
    return isinstance(value, list) and all(_string_value(item) for item in value)
