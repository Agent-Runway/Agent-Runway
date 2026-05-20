#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MAIN_TYPES = {"pitfall", "runbook", "preference", "invariant"}
ALL_TYPES = MAIN_TYPES | {"memory_update"}
STATUSES = {"draft", "candidate", "active", "mitigated", "obsolete", "disputed"}
ACTIONS = {"mark_obsolete", "mark_disputed", "mark_mitigated", "refresh_verified"}
SEVERITIES = {"low", "medium", "high", "critical"}
MAIN_REQUIRED = {
    "schema_version",
    "type",
    "id",
    "project_id",
    "status",
    "summary",
    "applies_to",
    "source_refs",
    "created_at",
    "can_support_completion",
    "requires_fresh_verification",
}
UPDATE_REQUIRED = {"schema_version", "type", "id", "target_id", "action", "reason", "source_refs", "created_at"}
SCOPE_KEYS = ("hosts", "paths", "platforms", "tasks", "commands", "languages", "scope")
USER_SOURCE_KINDS = {"user_confirmation", "user_message", "user_preference"}
PREFERENCE_AUTH_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"without\s+(asking|approval|authorization)",
        r"no\s+need\s+to\s+ask",
        r"directly\s+(deploy|push|delete|remove)",
        r"不用问|无需询问|不需要询问|不需要授权|无需授权",
        r"直接(部署|推送|删除|移除)",
    ]
]
SECRET_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"\b[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}\b",
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
        r"\bBearer\s+[A-Za-z0-9._\-]{20,}",
        r"\bgh[pousr]_[A-Za-z0-9_]{20,}",
        r"\bAKIA[0-9A-Z]{16}\b",
        r"\bsk-[A-Za-z0-9]{16,}",
        r"\b(api[_-]?key|token|secret)\s*[:=]\s*['\"]?[A-Za-z0-9._\-]{16,}",
    ]
]
TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


@dataclass(frozen=True)
class Finding:
    line: int
    record_id: str
    issue: str


def parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not TIMESTAMP_RE.match(value):
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def is_non_empty_array(value: Any) -> bool:
    return isinstance(value, list) and bool(value)


def source_kinds(record: dict[str, Any]) -> set[str]:
    refs = record.get("source_refs", [])
    if not isinstance(refs, list):
        return set()
    return {item.get("kind") for item in refs if isinstance(item, dict)}


def scoped(applies_to: Any) -> bool:
    if not isinstance(applies_to, dict):
        return False
    for key in SCOPE_KEYS:
        value = applies_to.get(key)
        if isinstance(value, str) and value.strip():
            return True
        if isinstance(value, list) and any(str(item).strip() for item in value):
            return True
    return False


def strings_in(value: Any, prefix: str = "") -> list[tuple[str, str]]:
    if isinstance(value, str):
        return [(prefix or "$", value)]
    if isinstance(value, list):
        result: list[tuple[str, str]] = []
        for index, item in enumerate(value):
            result.extend(strings_in(item, f"{prefix}[{index}]"))
        return result
    if isinstance(value, dict):
        result = []
        for key, item in value.items():
            child = f"{prefix}.{key}" if prefix else str(key)
            result.extend(strings_in(item, child))
        return result
    return []


def add(findings: list[Finding], line: int, record: dict[str, Any], issue: str) -> None:
    findings.append(Finding(line, str(record.get("id", "<missing>")), issue))


def validate_common(record: dict[str, Any], line: int, errors: list[Finding]) -> None:
    if record.get("schema_version") != "1.0":
        add(errors, line, record, "schema_version must be '1.0'")
    if record.get("can_support_completion") is not False:
        add(errors, line, record, "can_support_completion must be false")
    if record.get("requires_fresh_verification") is not True:
        add(errors, line, record, "requires_fresh_verification must be true")
    for field in ("created_at", "last_verified_at", "last_confirmed_at", "expires_at"):
        if field in record and parse_time(record.get(field)) is None:
            add(errors, line, record, f"{field} must be ISO-8601 UTC seconds")
    for field in ("severity", "priority"):
        if field in record and record[field] not in SEVERITIES:
            add(errors, line, record, f"{field} has invalid value")


def validate_main(record: dict[str, Any], line: int, errors: list[Finding]) -> None:
    missing = sorted(MAIN_REQUIRED - set(record))
    for field in missing:
        add(errors, line, record, f"missing required field: {field}")
    record_type = record.get("type")
    if record_type not in MAIN_TYPES:
        add(errors, line, record, f"unknown main record type: {record_type}")
    if record.get("status") not in STATUSES:
        add(errors, line, record, f"invalid status: {record.get('status')}")
    if record.get("status") == "active" and not scoped(record.get("applies_to")):
        add(errors, line, record, "active records require at least one applies_to scope")
    validate_common(record, line, errors)
    validate_type_rules(record, line, errors)


def validate_type_rules(record: dict[str, Any], line: int, errors: list[Finding]) -> None:
    record_type = record.get("type")
    active = record.get("status") == "active"
    if active and record_type in {"pitfall", "runbook"}:
        if not is_non_empty_array(record.get("source_refs")):
            add(errors, line, record, "active pitfall/runbook requires source_refs")
        if not is_non_empty_array(record.get("invalid_if")):
            add(errors, line, record, "active pitfall/runbook requires invalid_if")
    if active and record_type == "invariant" and not (is_non_empty_array(record.get("invalid_if")) or is_non_empty_array(record.get("reopen_if"))):
        add(errors, line, record, "active invariant requires invalid_if or reopen_if")
    if record_type == "runbook" and active and not is_non_empty_array(record.get("steps")):
        add(errors, line, record, "active runbook requires non-empty steps")
    if record_type == "preference" and active and not (source_kinds(record) & USER_SOURCE_KINDS):
        add(errors, line, record, "active preference requires a user source")
    if record_type == "preference":
        check_preference_authorization(record, line, errors)


def check_preference_authorization(record: dict[str, Any], line: int, errors: list[Finding]) -> None:
    for field_path, text in strings_in(record):
        for pattern in PREFERENCE_AUTH_PATTERNS:
            if pattern.search(text):
                add(errors, line, record, f"preference contains authorization language at {field_path}")
                return


def validate_update(record: dict[str, Any], line: int, known_ids: set[str], errors: list[Finding]) -> None:
    missing = sorted(UPDATE_REQUIRED - set(record))
    for field in missing:
        add(errors, line, record, f"missing required field: {field}")
    if record.get("action") not in ACTIONS:
        add(errors, line, record, f"invalid memory_update action: {record.get('action')}")
    if record.get("target_id") not in known_ids:
        add(errors, line, record, f"memory_update target_id does not exist: {record.get('target_id')}")
    if record.get("can_support_completion") is True:
        add(errors, line, record, "memory_update cannot support completion")
    if record.get("requires_fresh_verification") is False:
        add(errors, line, record, "memory_update cannot disable fresh verification")


def scan_secrets(record: dict[str, Any], line: int, errors: list[Finding]) -> None:
    for field_path, text in strings_in(record):
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                add(errors, line, record, f"secret-like value at {field_path}")
                return


def parse_jsonl(path: Path) -> tuple[list[tuple[int, dict[str, Any]]], list[Finding]]:
    records: list[tuple[int, dict[str, Any]]] = []
    errors: list[Finding] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#") or line.startswith("//"):
            errors.append(Finding(line_number, "<none>", "comments are not valid JSONL records"))
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(Finding(line_number, "<none>", f"malformed JSON: {exc.msg}"))
            continue
        if not isinstance(payload, dict):
            errors.append(Finding(line_number, "<none>", "record must be a JSON object"))
            continue
        records.append((line_number, payload))
    return records, errors


def lint(path: Path, strict: bool = False) -> dict[str, Any]:
    records, errors = parse_jsonl(path)
    warnings: list[Finding] = []
    seen: dict[str, int] = {}
    main_ids = {record["id"] for _, record in records if record.get("type") in MAIN_TYPES and isinstance(record.get("id"), str)}
    for line, record in records:
        record_id = record.get("id")
        if isinstance(record_id, str) and record_id in seen:
            add(errors, line, record, f"duplicate id first seen on line {seen[record_id]}")
        elif isinstance(record_id, str):
            seen[record_id] = line
        record_type = record.get("type")
        if record_type not in ALL_TYPES:
            add(errors, line, record, f"unknown type: {record_type}")
        elif record_type == "memory_update":
            validate_update(record, line, main_ids, errors)
        else:
            validate_main(record, line, errors)
        scan_secrets(record, line, errors)
        add_time_warnings(record, line, warnings)
    if strict:
        errors.extend(warnings)
        warnings = []
    return build_payload(path, records, errors, warnings)


def add_time_warnings(record: dict[str, Any], line: int, warnings: list[Finding]) -> None:
    created = parse_time(record.get("created_at"))
    expires = parse_time(record.get("expires_at"))
    if created and expires and expires <= created:
        warnings.append(Finding(line, str(record.get("id", "<missing>")), "expires_at must be later than created_at"))
    if expires and record.get("status") == "active" and expires < datetime.now(timezone.utc):
        warnings.append(Finding(line, str(record.get("id", "<missing>")), "active record is expired"))


def serialize(findings: list[Finding]) -> list[dict[str, Any]]:
    return [{"line": item.line, "id": item.record_id, "issue": item.issue} for item in findings]


def build_payload(path: Path, records: list[tuple[int, dict[str, Any]]], errors: list[Finding], warnings: list[Finding]) -> dict[str, Any]:
    return {
        "path": str(path),
        "record_count": len(records),
        "errors": serialize(errors),
        "warnings": serialize(warnings),
        "passed": not errors,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Lint Agent-Runway Project Learning Ledger JSONL")
    parser.add_argument("path", type=Path)
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.path.exists():
        payload = {"path": str(args.path), "record_count": 0, "errors": [{"line": 0, "id": "<none>", "issue": "file does not exist"}], "warnings": [], "passed": False}
    else:
        payload = lint(args.path, strict=args.strict)
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if payload["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
