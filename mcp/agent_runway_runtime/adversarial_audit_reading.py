from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


class AuditRecordReadError(ValueError):
    def __init__(self, path: Path, location: str, error: json.JSONDecodeError) -> None:
        self.path = path
        self.location = location
        self.error = error
        super().__init__(self.issue)

    @property
    def issue(self) -> str:
        return f"invalid adversarial audit JSON in {self.path} at {self.location}: {self.error.msg}"


def read_records(paths: list[Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in paths:
        records.extend(read_one(path))
    return records


def read_one(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    stripped = text.strip()
    if not stripped:
        return []
    if path.suffix == ".md":
        return records_from_markdown(path, stripped)
    if path.suffix == ".json" or stripped.startswith("["):
        data = loads_with_location(path, stripped, "document")
        if isinstance(data, dict) and "$schema" in data and "properties" in data:
            return []
        return data if isinstance(data, list) else [data]
    return records_from_jsonl(path, stripped)


def records_from_markdown(path: Path, text: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for index, match in enumerate(re.finditer(r"```json\s*(.*?)\s*```", text, flags=re.DOTALL), 1):
        data = loads_with_location(path, match.group(1), f"json block {index}")
        records.extend(data if isinstance(data, list) else [data])
    return records


def records_from_jsonl(path: Path, text: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for index, line in enumerate(text.splitlines(), 1):
        if line.strip():
            records.append(loads_with_location(path, line, f"line {index}"))
    return records


def loads_with_location(path: Path, text: str, location: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        raise AuditRecordReadError(path, location, error) from error
