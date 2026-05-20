from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def debug_enabled() -> bool:
    return os.environ.get("ILH_DEBUG") in {"1", "true", "TRUE", "yes", "on"}


def debug_log_path() -> Path:
    configured = os.environ.get("ILH_DEBUG_LOG_PATH")
    if configured:
        return Path(configured).expanduser()
    db_path = Path(os.environ.get("ILH_DB_PATH", ".agent-runway/state.db")).expanduser()
    return db_path.parent / "debug.log"


def write_debug_log(event: str, details: dict[str, Any] | None = None) -> None:
    if not debug_enabled():
        return
    path = debug_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "event": event,
        "details": _redact(details or {}),
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _redact_field(str(key), item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        return _redact_protected_paths(value)
    return value


def _redact_field(key: str, value: Any) -> Any:
    lowered = key.lower()
    if _is_path_key(lowered):
        return "[REDACTED_PATH]" if value else value
    if any(marker in lowered for marker in ("secret", "password", "token")):
        return "[REDACTED]"
    return _redact(value)


def _is_path_key(key: str) -> bool:
    return key in {"path", "file_path", "filepath", "cwd", "db_path"} or key.endswith("_path")


def _redact_protected_paths(text: str) -> str:
    redacted = text
    for key in ("ILH_SECRET_PATH", "ILH_DB_PATH"):
        protected = os.environ.get(key)
        for variant in _path_variants(protected):
            redacted = re.sub(re.escape(variant), "[REDACTED_PATH]", redacted, flags=re.IGNORECASE)
    return redacted


def _path_variants(path: str | None) -> set[str]:
    if not path:
        return set()
    expanded = str(Path(path).expanduser())
    return {expanded, expanded.replace("\\", "/"), expanded.replace("/", "\\")}
