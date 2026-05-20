#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from project_learning_lint import DEFAULT_PROJECT_LEDGER_PATH, parse_jsonl, parse_time, scoped

DEFAULT_LIMIT = 5
MAX_LIMIT = 5
ACTIVE_STATUSES = {"active", "mitigated"}
TYPE_ORDER = {"invariant": 0, "pitfall": 1, "runbook": 2, "preference": 3}
SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
TASK_SEPARATOR_TRANSLATION = str.maketrans({"-": " ", "_": " "})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Query Agent-Runway Project Learning Ledger")
    parser.add_argument("path", nargs="?", type=Path, default=DEFAULT_PROJECT_LEDGER_PATH)
    parser.add_argument("--host")
    parser.add_argument("--path", dest="file_path")
    parser.add_argument("--task")
    parser.add_argument("--type", choices=["pitfall", "runbook", "preference", "invariant"])
    parser.add_argument("--severity", choices=["low", "medium", "high", "critical"])
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser.parse_args()


def values(record: dict[str, Any], key: str) -> list[str]:
    applies_to = record.get("applies_to", {})
    if not isinstance(applies_to, dict):
        return []
    value = applies_to.get(key, [])
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


def normalized_task(value: str) -> str:
    return " ".join(value.translate(TASK_SEPARATOR_TRANSLATION).casefold().split())


def matches(record: dict[str, Any], args: argparse.Namespace) -> bool:
    if record.get("type") == "memory_update" or record.get("status") not in ACTIVE_STATUSES:
        return False
    if record.get("status") == "active" and not scoped(record.get("applies_to")):
        return False
    expires_at = parse_time(record.get("expires_at"))
    if expires_at is not None and expires_at < datetime.now(timezone.utc):
        return False
    if args.type and record.get("type") != args.type:
        return False
    if args.severity and record.get("severity") != args.severity:
        return False
    if args.host and args.host not in values(record, "hosts"):
        return False
    if args.task and not matches_task(args.task, values(record, "tasks")):
        return False
    if args.file_path and not any(args.file_path in item or item in args.file_path for item in values(record, "paths")):
        return False
    return True


def matches_task(requested: str, candidates: list[str]) -> bool:
    return normalized_task(requested) in {normalized_task(item) for item in candidates}


def recency_key(record: dict[str, Any]) -> float:
    timestamp = parse_time(record.get("last_verified_at"))
    if timestamp is None:
        timestamp = parse_time(record.get("last_confirmed_at"))
    if timestamp is None:
        timestamp = parse_time(record.get("created_at"))
    return -(timestamp.timestamp() if timestamp is not None else 0.0)


def sort_key(record: dict[str, Any]) -> tuple[int, int, int, float, str]:
    mitigated_penalty = 1 if record.get("status") == "mitigated" else 0
    return (
        mitigated_penalty,
        TYPE_ORDER.get(str(record.get("type")), 9),
        SEVERITY_ORDER.get(str(record.get("severity", record.get("priority", "medium"))), 2),
        recency_key(record),
        str(record.get("id", "")),
    )


def query(path: Path, args: argparse.Namespace) -> dict[str, Any]:
    if not path.exists():
        return {"warning": advisory(), "warnings": [f"file does not exist: {path}"], "records": []}
    records, parse_errors = parse_jsonl(path)
    if parse_errors:
        return {"warning": advisory(), "errors": [item.issue for item in parse_errors], "records": []}
    matched = [record for _, record in records if matches(record, args)]
    limit = max(0, min(args.limit, MAX_LIMIT))
    return {"warning": advisory(), "limit": limit, "records": sorted(matched, key=sort_key)[:limit]}


def advisory() -> str:
    return "Project learning is advisory context, not completion evidence or authorization."


def terminal_safe(value: str) -> str:
    encoding = sys.stdout.encoding or "utf-8"
    return value.encode(encoding, errors="backslashreplace").decode(encoding, errors="replace")


def main() -> int:
    args = parse_args()
    payload = query(args.path, args)
    if args.as_json:
        print(json.dumps(payload, indent=2))
    else:
        print(terminal_safe(payload["warning"]))
        for warning in payload.get("warnings", []):
            print(terminal_safe(f"warning: {warning}"))
        for error in payload.get("errors", []):
            print(terminal_safe(f"error: {error}"))
        for record in payload.get("records", []):
            print(terminal_safe(f"- {record.get('id')}: {record.get('summary')}"))
    return 0 if not payload.get("errors") else 2


if __name__ == "__main__":
    raise SystemExit(main())
