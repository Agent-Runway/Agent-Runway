from __future__ import annotations

import re
from datetime import datetime
from typing import Any


def nonempty_list(value: Any) -> bool:
    return isinstance(value, list) and any(str(item).strip() for item in value)


def nonempty_string_list(value: Any) -> bool:
    return isinstance(value, list) and any(isinstance(item, str) and item.strip() for item in value)


def record_claims(record: dict[str, Any]) -> set[str]:
    return claim_set(record.get("target_claims")) | claim_set(record.get("affected_claims"))


def claim_set(value: Any) -> set[str]:
    if isinstance(value, list):
        return {item.strip() for item in value if isinstance(item, str) and item.strip()}
    if not isinstance(value, str):
        return set()
    text = value.strip()
    return {text} if text else set()


def scope_tokens(value: str) -> set[str]:
    if not isinstance(value, str):
        return set()
    return {item.strip() for item in re.split(r"[,;\n]", value) if item.strip()}


def parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def has_timezone(value: Any) -> bool:
    parsed = parse_time(value)
    return parsed is not None and parsed.tzinfo is not None


def parse_aware_time(value: Any) -> datetime | None:
    parsed = parse_time(value)
    if parsed is None or parsed.tzinfo is None:
        return None
    return parsed
