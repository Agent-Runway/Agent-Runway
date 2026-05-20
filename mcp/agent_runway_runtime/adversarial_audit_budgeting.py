from __future__ import annotations

import json
from typing import Any

from .adversarial_audit_common import has_timezone, nonempty_string_list, parse_aware_time, parse_time


def budget_usage(records: list[dict[str, Any]], budget: dict[str, int]) -> dict[str, int]:
    attempts = _billable_attempts(records)
    hypotheses = {a.get("hypothesis") for a in attempts if a.get("hypothesis")}
    hypotheses_used = len(hypotheses)
    attacks_used = len(attempts)
    runtime_seconds_used = _audit_runtime_seconds(records, attempts)
    return {
        "hypotheses_used": hypotheses_used,
        "hypotheses_remaining": max(budget.get("max_hypotheses", 0) - hypotheses_used, 0),
        "attacks_used": attacks_used,
        "attacks_remaining": max(budget.get("max_executable_attacks", 0) - attacks_used, 0),
        "runtime_seconds_used": runtime_seconds_used,
        "runtime_seconds_remaining": max(budget.get("max_runtime_seconds", 0) - runtime_seconds_used, 0),
    }


def audit_stop_gate(
    usage: dict[str, int], budget: dict[str, int], stop_condition: str
) -> dict[str, Any]:
    exhausted = (
        usage.get("hypotheses_remaining", 1) == 0
        or usage.get("attacks_remaining", 1) == 0
        or usage.get("runtime_seconds_remaining", 1) == 0
    )
    if not exhausted:
        return {"allowed": True, "reason": "audit budget not exhausted"}
    if stop_condition == "frontier_exhausted":
        return {
            "allowed": True,
            "reason": "audit budget exhausted, allowing frontier_exhausted wrap-up",
        }
    if stop_condition == "slice_verified":
        return {"allowed": False, "reason": "audit budget exhausted, cannot verify new slice"}
    return {"allowed": True, "reason": f"audit budget exhausted, allowing {stop_condition}"}


def _billable_attempts(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    attempts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            continue
        if record.get("record_type") != "audit_attempt":
            continue
        if record.get("outcome") not in {"attack_failed", "attack_succeeded"}:
            continue
        if not nonempty_string_list(record.get("execution_receipts")):
            continue
        if parse_aware_time(record.get("timestamp")) is None:
            continue
        key = _attempt_key(record)
        if key in seen:
            continue
        seen.add(key)
        attempts.append(record)
    return attempts


def _fresh_billable_attempts(
    records: list[dict[str, Any]], plans: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    baseline = _latest_baseline_time(plans)
    if baseline is None:
        return _billable_attempts(records)
    return [a for a in _billable_attempts(records) if _fresh_after_baseline(a, baseline)]


def _latest_baseline_time(plans: list[dict[str, Any]]) -> Any | None:
    times = []
    for plan in plans:
        baseline = plan.get("freshness_baseline") or {}
        if isinstance(baseline, dict):
            if has_timezone(baseline.get("timestamp")):
                times.append(parse_time(baseline.get("timestamp")))
    valid = [item for item in times if item is not None]
    return max(valid) if valid else None


def _attempt_key(record: dict[str, Any]) -> str:
    attempt_value = record.get("attempt_id")
    attempt_id = attempt_value.strip() if isinstance(attempt_value, str) else ""
    if attempt_id:
        return f"attempt_id:{attempt_id}"
    payload = {
        "attack_type": record.get("attack_type"),
        "execution_receipts": record.get("execution_receipts"),
        "hypothesis": record.get("hypothesis"),
    }
    return f"attempt_payload:{json.dumps(payload, sort_keys=True)}"


def _fresh_after_baseline(record: dict[str, Any], baseline: Any) -> bool:
    timestamp = parse_aware_time(record.get("timestamp"))
    return timestamp is not None and timestamp > baseline


def _audit_runtime_seconds(
    records: list[dict[str, Any]], attempts: list[dict[str, Any]]
) -> int:
    timestamps = [parse_time(a.get("timestamp")) for a in attempts]
    for plan in records:
        if not isinstance(plan, dict):
            continue
        if plan.get("record_type") != "audit_plan":
            continue
        baseline = plan.get("freshness_baseline") or {}
        if isinstance(baseline, dict):
            timestamps.append(parse_time(baseline.get("timestamp")))
    valid = [item for item in timestamps if item is not None and item.tzinfo is not None]
    if len(valid) < 2:
        return 0
    return int((max(valid) - min(valid)).total_seconds())
