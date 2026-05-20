from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

RECORD_TYPES = {
    "audit_plan",
    "audit_attempt",
    "audit_finding",
    "audit_disposition",
    "audit_acceptance",
    "audit_update",
}
ATTACK_TYPES = {
    "stale_evidence",
    "mission_epoch",
    "authorization_freshness",
    "receipt_replay_collision",
    "evidence_type_mismatch",
    "assertion_laundering",
    "budget_bypass",
    "counterexample_gap",
    "host_capability_overclaim",
    "secret_path_bypass",
    "opencode_bridge_gap",
    "project_learning_poisoning",
    "release_gate_drift",
    "concurrency_race",
    "install_config_drift",
}
PROFILES = {
    "runtime_gate_adversary",
    "host_harness_adversary",
    "release_claim_adversary",
    "project_learning_adversary",
    "platform_adversary",
    "concurrency_adversary",
    "install_adversary",
}
SEVERITIES = {"critical", "high", "medium", "low", "info", "none"}
DISPOSITIONS = {
    "blocking",
    "must_fix_before_release",
    "accepted_residual_risk",
    "needs_reproduction",
    "false_positive",
    "non_blocking",
}
BLOCKING_SEVERITIES = {"critical", "high"}
BANNED_PHRASES = (
    "proved safe",
    "proves safe",
    "all vulnerabilities eliminated",
    "no vulnerabilities",
    "no bugs",
    "guaranteed secure",
    "proved correctness",
    "证明安全",
    "不存在漏洞",
    "证明不存在 bug",
)
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{20,}"),
    re.compile(r"\b(?:sk|ghp|glpat)-[A-Za-z0-9_\-]{16,}"),
)
DESTRUCTIVE_PATTERNS = ("rm -rf /", "git push", "curl http://169.254.169.254")


def read_records(paths: list[Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in paths:
        records.extend(_read_one(path))
    return records


def lint_records(records: list[dict[str, Any]]) -> list[str]:
    issues: list[str] = []
    ids = _index(records, issues)
    for record in records:
        _lint_record(record, records, ids, issues)
    return issues


def gate_violations(
    records: list[dict[str, Any]],
    required_profiles: list[str],
    required_claims: list[str],
    latest_receipt_seq: int,
) -> list[str]:
    issues = lint_records(records)
    if issues:
        return issues
    plans = [r for r in records if r.get("record_type") == "audit_plan"]
    if not plans:
        return ["adversarial audit required but no audit_plan was provided"]
    violations: list[str] = []
    _check_required_profiles(records, required_profiles, violations)
    _check_required_claims(records, required_claims, violations)
    _check_freshness(plans, latest_receipt_seq, violations)
    for item in unresolved_blockers(records):
        violations.append(
            f"unresolved blocking adversarial finding {item.get('finding_id')}: {item.get('required_action', '')}"
        )
    return violations


def unresolved_blockers(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        record
        for record in records
        if record.get("record_type") == "audit_finding" and record.get("disposition") == "blocking"
    ]


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    blockers = unresolved_blockers(records)
    for record in records:
        key = str(record.get("disposition") or record.get("record_type"))
        counts[key] = counts.get(key, 0) + 1
    return {
        "record_count": len(records),
        "counts": counts,
        "unresolved_blockers": [item.get("finding_id") for item in blockers],
        "passed": not blockers and not lint_records(records),
    }


def _read_one(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    stripped = text.strip()
    if not stripped:
        return []
    if path.suffix == ".md":
        return _records_from_markdown(stripped)
    if path.suffix == ".json":
        data = json.loads(stripped)
        if isinstance(data, dict) and "$schema" in data and "properties" in data:
            return []
        return data if isinstance(data, list) else [data]
    if stripped.startswith("["):
        data = json.loads(stripped)
        return data if isinstance(data, list) else [data]
    return [json.loads(line) for line in stripped.splitlines() if line.strip()]


def _records_from_markdown(text: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for match in re.finditer(r"```json\s*(.*?)\s*```", text, flags=re.DOTALL):
        data = json.loads(match.group(1))
        records.extend(data if isinstance(data, list) else [data])
    return records


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
    if record_type == "audit_plan":
        _lint_plan(record, issues)
    if record_type == "audit_attempt":
        _lint_attempt(record, issues)
    if record_type == "audit_finding":
        _lint_finding(record, records, ids, issues)
    if record_type == "audit_acceptance":
        _lint_acceptance(record, issues)
    if record_type == "audit_update":
        _lint_update(record, ids, issues)


def _lint_plan(record: dict[str, Any], issues: list[str]) -> None:
    scope = record.get("audit_scope") if isinstance(record.get("audit_scope"), dict) else {}
    budget = record.get("audit_budget") if isinstance(record.get("audit_budget"), dict) else {}
    for field in ("target_claims", "target_files", "allowed_attack_types", "excluded_actions"):
        if not _nonempty_list(scope.get(field)):
            issues.append(f"audit_plan requires audit_scope.{field}")
    for field in _budget_fields():
        if not isinstance(budget.get(field), int) or budget.get(field) < 1:
            issues.append(f"audit_plan requires audit_budget.{field} >= 1")
    for profile in record.get("profiles_required", []):
        if profile not in PROFILES:
            issues.append(f"unknown adversarial profile: {profile}")
    for attack in scope.get("allowed_attack_types", []):
        if attack not in ATTACK_TYPES:
            issues.append(f"unknown attack_type in audit_scope: {attack}")


def _lint_attempt(record: dict[str, Any], issues: list[str]) -> None:
    attack_type = record.get("attack_type")
    outcome = record.get("outcome")
    receipts = record.get("execution_receipts") or []
    if attack_type not in ATTACK_TYPES:
        issues.append(f"unknown attack_type: {attack_type}")
    if record.get("profile") not in PROFILES:
        issues.append(f"unknown adversarial profile: {record.get('profile')}")
    if outcome in {"attack_succeeded", "attack_failed"} and not _nonempty_list(receipts):
        issues.append("audit_attempt with attack outcome requires execution_receipts")
    if _uses_project_learning(record) and not _nonempty_list(receipts):
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
    attempts = [ids.get(item) for item in record.get("linked_attempt_ids", [])]
    has_evidence = any(
        attempt and attempt.get("outcome") == "attack_succeeded" and _nonempty_list(attempt.get("execution_receipts"))
        for attempt in attempts
    )
    if not has_evidence:
        issues.append("blocking finding requires executable evidence from a successful attempt")


def _lint_acceptance(record: dict[str, Any], issues: list[str]) -> None:
    if not str(record.get("accepted_scope", "")).strip():
        issues.append("audit_acceptance requires accepted_scope")
    if not str(record.get("reason", "")).strip():
        issues.append("audit_acceptance requires reason")
    if "authorize" in json.dumps(record, ensure_ascii=False).lower():
        issues.append("audit_acceptance must not be used as authorization")


def _lint_update(record: dict[str, Any], ids: dict[str, dict[str, Any]], issues: list[str]) -> None:
    if record.get("target_id") not in ids:
        issues.append(f"audit_update targets unknown record: {record.get('target_id')}")
    if not str(record.get("reason", "")).strip():
        issues.append("audit_update requires reason")


def _lint_text(record: dict[str, Any], issues: list[str]) -> None:
    scan_record = dict(record)
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


def _check_required_profiles(records: list[dict[str, Any]], required: list[str], issues: list[str]) -> None:
    covered = {r.get("profile") for r in records if r.get("record_type") == "audit_attempt"}
    missing = [profile for profile in required if profile not in covered]
    if missing:
        issues.append(f"missing required adversarial profiles: {missing}")


def _check_required_claims(records: list[dict[str, Any]], required: list[str], issues: list[str]) -> None:
    covered = {claim for r in records for claim in r.get("target_claims", r.get("affected_claims", []))}
    missing = [claim for claim in required if claim not in covered]
    if missing:
        issues.append(f"missing adversarial coverage for claims: {missing}")


def _check_freshness(plans: list[dict[str, Any]], latest_seq: int, issues: list[str]) -> None:
    baselines = [int((p.get("freshness_baseline") or {}).get("latest_receipt_seq") or 0) for p in plans]
    if baselines and max(baselines) < latest_seq:
        issues.append(f"adversarial audit coverage is stale after receipt seq {latest_seq}")


def _budget_fields() -> tuple[str, ...]:
    return (
        "max_hypotheses",
        "max_executable_attacks",
        "max_runtime_seconds",
        "max_retries_per_attack",
        "max_output_bytes",
        "max_generated_artifacts",
    )


def _nonempty_list(value: Any) -> bool:
    return isinstance(value, list) and any(str(item).strip() for item in value)


def _uses_project_learning(record: dict[str, Any]) -> bool:
    return "project_learning" in json.dumps(record.get("source_refs", []), ensure_ascii=False)


def _has_acceptance(finding: dict[str, Any], records: list[dict[str, Any]]) -> bool:
    finding_id = finding.get("finding_id")
    for record in records:
        if record.get("record_type") != "audit_acceptance":
            continue
        if record.get("linked_finding_id") == finding_id and record.get("accepted_scope") and record.get("reason"):
            return True
    return False
