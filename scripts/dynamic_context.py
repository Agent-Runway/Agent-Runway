#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_CONTEXT_PATH = Path(".agent-runway") / "dynamic-context.jsonl"
MAX_CONTENT_BYTES = 100_000
DEFAULT_MAX_OUTPUT_BYTES = 100_000
KINDS = {"note", "finding", "next_action", "decision", "risk"}
REQUIRED_FIELDS = {
    "schema_version", "type", "mission_id", "session_id", "task_id", "kind",
    "summary", "content", "created_at", "can_support_completion",
    "requires_fresh_verification",
}


@dataclass(frozen=True)
class Finding:
    line: int
    record_id: str
    issue: str


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Maintain local Agent-Runway dynamic context JSONL")
    subcommands = parser.add_subparsers(dest="command", required=True)
    add_common_path(subcommands.add_parser("lint", help="validate dynamic context JSONL"))
    add_query_args(add_common_path(subcommands.add_parser("query", help="query mission dynamic context")))
    add_append_args(add_common_path(subcommands.add_parser("append", help="append one context record")))
    return parser.parse_args()


def add_common_path(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser.add_argument("--path", type=Path, default=DEFAULT_CONTEXT_PATH)
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def add_query_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--max-output-bytes", type=int, default=DEFAULT_MAX_OUTPUT_BYTES)


def add_append_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--kind", required=True, choices=sorted(KINDS))
    parser.add_argument("--summary", required=True)
    content = parser.add_mutually_exclusive_group(required=True)
    content.add_argument("--content")
    content.add_argument("--content-file", type=Path)


def mission_id(session_id: str, task_id: str) -> str:
    return f"{session_id.strip()}/{task_id.strip()}"


def build_record(args: argparse.Namespace) -> dict[str, Any]:
    content = read_content(args)
    validate_content_size(content)
    return {
        "schema_version": "1.0",
        "type": "dynamic_context",
        "mission_id": mission_id(args.session_id, args.task_id),
        "session_id": args.session_id.strip(),
        "task_id": args.task_id.strip(),
        "kind": args.kind,
        "summary": args.summary.strip(),
        "content": content,
        "created_at": utc_now(),
        "can_support_completion": False,
        "requires_fresh_verification": True,
    }


def read_content(args: argparse.Namespace) -> str:
    if args.content_file is not None:
        return args.content_file.read_text(encoding="utf-8")
    return str(args.content)


def validate_content_size(content: str) -> None:
    size = len(content.encode("utf-8"))
    if size > MAX_CONTENT_BYTES:
        raise ValueError(f"content exceeds {MAX_CONTENT_BYTES} bytes: {size}")


def parse_jsonl(path: Path) -> tuple[list[tuple[int, dict[str, Any]]], list[Finding]]:
    records: list[tuple[int, dict[str, Any]]] = []
    errors: list[Finding] = []
    if not path.exists():
        return [], [Finding(0, "<file>", f"file does not exist: {path}")]
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            record, error = parse_line(line, line_number)
            if error is not None:
                errors.append(error)
            if record is not None:
                records.append((line_number, record))
    return records, errors


def parse_line(line: str, line_number: int) -> tuple[dict[str, Any] | None, Finding | None]:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError as exc:
        return None, Finding(line_number, "<none>", f"malformed JSON: {exc.msg}")
    if not isinstance(payload, dict):
        return None, Finding(line_number, "<none>", "record must be a JSON object")
    return payload, None


def lint_records(records: list[tuple[int, dict[str, Any]]], initial_errors: list[Finding]) -> list[Finding]:
    errors = list(initial_errors)
    for line, record in records:
        validate_record(record, line, errors)
    return errors


def validate_record(record: dict[str, Any], line: int, errors: list[Finding]) -> None:
    record_id = str(record.get("mission_id", "<missing>"))
    for field in sorted(REQUIRED_FIELDS - set(record)):
        errors.append(Finding(line, record_id, f"missing required field: {field}"))
    errors.extend(validate_record_values(record, line, record_id))


def validate_record_values(record: dict[str, Any], line: int, record_id: str) -> list[Finding]:
    expected_mission_id = mission_id(str(record.get("session_id", "")), str(record.get("task_id", "")))
    checks = [
        (record.get("schema_version") == "1.0", "schema_version must be '1.0'"),
        (record.get("type") == "dynamic_context", "type must be dynamic_context"),
        (record.get("mission_id") == expected_mission_id, "mission_id must equal session_id/task_id"),
        (record.get("kind") in KINDS, "kind has invalid value"),
        (record.get("can_support_completion") is False, "can_support_completion must be false"),
        (record.get("requires_fresh_verification") is True, "requires_fresh_verification must be true"),
    ]
    errors = [Finding(line, record_id, issue) for passed, issue in checks if not passed]
    if isinstance(record.get("content"), str):
        content_error = content_size_error(record["content"], line, record_id)
        if content_error is not None:
            errors.append(content_error)
    return errors


def content_size_error(content: str, line: int, record_id: str) -> Finding | None:
    size = len(content.encode("utf-8"))
    if size > MAX_CONTENT_BYTES:
        return Finding(line, record_id, f"content exceeds {MAX_CONTENT_BYTES} bytes: {size}")
    return None


def append_record(args: argparse.Namespace) -> int:
    record = build_record(args)
    args.path.parent.mkdir(parents=True, exist_ok=True)
    with args.path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(json.dumps({"appended": True, "path": str(args.path), "mission_id": record["mission_id"]}, indent=2))
    return 0


def lint_command(args: argparse.Namespace) -> int:
    records, parse_errors = parse_jsonl(args.path)
    errors = lint_records(records, parse_errors)
    payload = {"path": str(args.path), "record_count": len(records), "errors": serialize(errors), "passed": not errors}
    emit(payload, args.as_json)
    return 0 if not errors else 2


def query_command(args: argparse.Namespace) -> int:
    records, parse_errors = parse_jsonl(args.path)
    errors = lint_records(records, parse_errors)
    if errors:
        emit({"path": str(args.path), "errors": serialize(errors), "passed": False}, args.as_json)
        return 2
    mission = mission_id(args.session_id, args.task_id)
    selected, truncated = select_records(records, mission, max(1, args.max_output_bytes))
    emit({"mission_id": mission, "records": selected, "truncated": truncated}, args.as_json)
    return 0


def select_records(records: list[tuple[int, dict[str, Any]]], target_mission_id: str, budget: int) -> tuple[list[dict[str, Any]], bool]:
    selected: list[dict[str, Any]] = []
    used = 0
    matches = [record for _, record in records if record.get("mission_id") == target_mission_id]
    for record in reversed(matches):
        size = len(json.dumps(record, ensure_ascii=False).encode("utf-8"))
        if selected and used + size > budget:
            return selected, True
        selected.append(record)
        used += size
    return selected, len(selected) < len(matches)


def serialize(errors: list[Finding]) -> list[dict[str, Any]]:
    return [{"line": item.line, "id": item.record_id, "issue": item.issue} for item in errors]


def emit(payload: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(json.dumps(payload, ensure_ascii=False))


def main() -> int:
    args = parse_args()
    try:
        if args.command == "append":
            return append_record(args)
        if args.command == "lint":
            return lint_command(args)
        if args.command == "query":
            return query_command(args)
    except (OSError, ValueError) as exc:
        print(str(exc))
        return 2
    raise ValueError(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
