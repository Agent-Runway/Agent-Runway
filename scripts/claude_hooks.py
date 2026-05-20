#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import traceback
from functools import wraps
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
MCP_ROOT = REPO_ROOT / "mcp"
if str(MCP_ROOT) not in sys.path:
    sys.path.insert(0, str(MCP_ROOT))

from agent_runway_runtime.store import RuntimeStore  # noqa: E402
from agent_runway_runtime.host_tool_taxonomy import SHELL_LIKE_TOOLS, MUTATION_TOOLS, OBSERVATION_TOOLS  # noqa: E402
from agent_runway_runtime.host_adapters import resolve_event_host  # noqa: E402
from agent_runway_runtime.debug_logging import write_debug_log  # noqa: E402

TOOL_NAME_ALIASES = {
    "bash": "Bash",
    "powershell": "PowerShell",
    "shell": "Shell",
    "read": "Read",
    "glob": "Glob",
    "grep": "Grep",
    "edit": "Edit",
    "write": "Write",
    "multiedit": "MultiEdit",
    "codex": "Codex",
    "opencode": "OpenCode",
}
MISSION_BINDING_TOOLS = frozenset(
    {
        "agent-runway_mission_lock",
        "agent-runway_prompt_intake_gate",
    }
)
SUBAGENT_CONTEXT_MODES = {"fresh", "fork", "resumed", "team", "unknown"}
SUBAGENT_WORKSPACE_KINDS = {
    "shared_checkout",
    "worktree",
    "local_sandbox",
    "cloud_sandbox",
    "unknown",
}
SUBAGENT_STOP_STATUSES = {"completed", "failed", "abandoned", "rejected"}

DANGEROUS_BASH_PATTERNS = [
    "rm -rf",
    "git push",
    "git reset --hard",
    "scp ",
    "ssh ",
    "curl ",
    "wget ",
    "kubectl apply",
    "terraform apply",
    "docker push",
]
NORMALIZED_DANGEROUS_BASH_PATTERNS = [
    " ".join(pattern.split()) for pattern in DANGEROUS_BASH_PATTERNS
]

def protected_paths(cwd: str | None = None) -> list[str]:
    state_root = cwd or str(REPO_ROOT)
    paths = [
        str(
            Path(
                os.environ.get("ILH_SECRET_PATH", "~/.config/agent-runway/secret.key")
            ).expanduser()
        )
    ]
    db_path = os.environ.get("ILH_DB_PATH")
    if db_path:
        paths.append(str(Path(db_path).expanduser()))
    else:
        paths.append(str(Path(state_root) / ".agent-runway" / "state.db"))
    return paths

HOME_ENV_ALIASES = ["$HOME", "%USERPROFILE%", "$env:USERPROFILE"]
SENSITIVE_PATH_MARKERS = [
    "/.ssh/",
    ".ssh/",
    "/.aws/credentials",
    "/.aws/config",
    "/.config/gcloud/application_default_credentials.json",
    "/.azure/accesstokens.json",
    "/.kube/config",
    "/.docker/config.json",
    "/.netrc",
    "/.npmrc",
    "/.pypirc",
]
SENSITIVE_KEY_SUFFIXES = (".pem", ".p12", ".pfx")
SENSITIVE_ENV_FILE = re.compile(r"(?<![\w.-])\.env(?:\.[\w-]+)?(?![\w-])")
SENSITIVE_KEY_FILE = re.compile(r"(?<![\w.-])[\w.-]+\.(?:pem|p12|pfx)(?![\w.-])")
FILE_HASH_CHUNK_SIZE = 1024 * 1024


def decode_event_payload(raw: str, source: str) -> dict[str, Any]:
    text = raw.strip()
    if not text:
        return {}
    if text.startswith("\ufeff"):
        text = text.lstrip("\ufeff")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        preview = text[:200]
        payload_error = {
            "source": source,
            "error": "json_decode_failed",
            "raw_preview_sha256": hashlib.sha256(
                preview.encode("utf-8", errors="replace")
            ).hexdigest(),
            "line": exc.lineno,
            "column": exc.colno,
        }
        write_debug_log("hook.payload_error", payload_error)
        sys.stderr.write(
            f"[{source}] failed to parse stdin JSON; "
            f"sha256={payload_error['raw_preview_sha256']} "
            f"error={exc.msg} line={exc.lineno} column={exc.colno}\n"
        )
        return {
            "error": "json_decode_failed",
            "raw_preview_sha256": payload_error["raw_preview_sha256"],
            "line": exc.lineno,
            "column": exc.colno,
        }
    if isinstance(payload, dict):
        return payload
    payload_type = type(payload).__name__
    write_debug_log(
        "hook.payload_error",
        {"source": source, "error": "json_payload_not_object", "payload_type": payload_type},
    )
    sys.stderr.write(f"[{source}] stdin JSON payload is not an object; type={payload_type}\n")
    return {"error": "json_payload_not_object", "payload_type": payload_type}


def load_event() -> dict[str, Any]:
    return decode_event_payload(sys.stdin.read(), "claude-hooks")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="surrogateescape")).hexdigest()


def receipt_text(value: Any) -> str:
    text = str(value)
    return text.encode("utf-8", errors="backslashreplace").decode("utf-8")


def sha256_file(path: str) -> str | None:
    file_path = Path(path)
    if not file_path.exists() or not file_path.is_file():
        return None
    digest = hashlib.sha256()
    with file_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(FILE_HASH_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compact_text(value: Any, limit: int = 300) -> str:
    text = (
        json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    )
    text = receipt_text(text).replace("\n", " ")
    return text[:limit]


def _security_fold(value: str) -> str:
    return os.path.normcase(value).casefold()


def _normalized_path_text(path: str) -> str:
    normalized = os.path.expandvars(str(Path(path).expanduser()))
    return _security_fold(os.path.normpath(normalized))


def _slash_fold(value: str) -> str:
    return _security_fold(os.path.expandvars(value)).replace("\\", "/")


def _path_basename(path: str) -> str:
    return _slash_fold(path).rstrip("/").rsplit("/", 1)[-1]


def _matches_sensitive_credential_path(path: str) -> bool:
    normalized = _protected_path_text(path)
    return _has_sensitive_path_marker(normalized) or _has_sensitive_basename(path)


def _protected_path_text(path: str) -> str:
    return "/" + _slash_fold(os.path.normpath(path)).strip("/")


def _has_sensitive_path_marker(normalized: str) -> bool:
    return any(marker in normalized for marker in SENSITIVE_PATH_MARKERS)


def _has_sensitive_basename(path: str) -> bool:
    basename = _path_basename(path)
    return (
        SENSITIVE_ENV_FILE.fullmatch(basename) is not None
        or basename.endswith(SENSITIVE_KEY_SUFFIXES)
    )


def _secret_path_variants(secret_path: str) -> set[str]:
    variants: set[str] = set()
    absolute = Path(os.path.expandvars(secret_path)).expanduser()
    absolute_text = str(absolute)
    variants.add(_security_fold(absolute_text))
    variants.add(_security_fold(absolute_text.replace("\\", "/")))
    variants.add(_security_fold(absolute_text.replace("/", "\\")))

    home = Path.home()
    try:
        relative_to_home = absolute.relative_to(home)
    except ValueError:
        relative_to_home = None

    if relative_to_home is not None:
        rel_posix = relative_to_home.as_posix()
        rel_windows = rel_posix.replace("/", "\\")
        variants.add(_security_fold(f"~/{rel_posix}"))
        variants.add(_security_fold(f"~\\{rel_windows}"))
        for alias in HOME_ENV_ALIASES:
            variants.add(_security_fold(f"{alias}/{rel_posix}"))
            variants.add(_security_fold(f"{alias}\\{rel_windows}"))

    return variants


def _matches_secret_path(path: str, cwd: str | None = None) -> bool:
    normalized = _normalized_path_text(path)
    return any(
        normalized in _secret_path_variants(secret_path)
        for secret_path in protected_paths(cwd)
    )


def _matches_protected_read_path(path: str, cwd: str | None = None) -> bool:
    return _matches_secret_path(path, cwd) or _matches_sensitive_credential_path(path)


def _bash_reads_secret(command: str, cwd: str | None = None) -> bool:
    normalized_command = _security_fold(command)
    for secret_path in protected_paths(cwd):
        secret_variants = _secret_path_variants(secret_path)
        if any(variant in normalized_command for variant in secret_variants):
            return True
    return False


def _bash_references_sensitive_credential_path(command: str) -> bool:
    normalized = _slash_fold(command)
    return _has_sensitive_path_marker(normalized) or _has_sensitive_file_token(normalized)


def _has_sensitive_file_token(text: str) -> bool:
    return SENSITIVE_ENV_FILE.search(text) is not None or SENSITIVE_KEY_FILE.search(text) is not None


def _bash_reads_protected_path(command: str, cwd: str | None = None) -> bool:
    return _bash_reads_secret(command, cwd) or _bash_references_sensitive_credential_path(command)


def build_store(event: dict[str, Any]) -> RuntimeStore:
    cwd = event.get("cwd") or str(REPO_ROOT)
    db_path = os.environ.get("ILH_DB_PATH") or str(
        Path(cwd) / ".agent-runway" / "state.db"
    )
    return RuntimeStore(db_path=db_path)


def canonical_tool_name(tool_name: str) -> str:
    raw = str(tool_name or "").strip()
    if not raw:
        return ""
    return TOOL_NAME_ALIASES.get(raw.lower(), raw)


def shell_command_text(tool_input: dict[str, Any]) -> str:
    return str(
        tool_input.get("command")
        or tool_input.get("cmd")
        or tool_input.get("prompt")
        or tool_input.get("task")
        or ""
    )


def parse_failure_decision(event: dict[str, Any]) -> dict[str, str] | None:
    if not event_parse_failed(event):
        return None
    return {
        "permissionDecision": "deny",
        "permissionDecisionReason": "tool use denied because the hook could not parse the event payload",
    }


def parse_failure_stop_response(event: dict[str, Any]) -> dict[str, Any] | None:
    if not event_parse_failed(event):
        return None
    return {
        "continue": False,
        "stopReason": "stop denied because the hook could not parse the event payload",
    }


def event_parse_failed(event: dict[str, Any]) -> bool:
    return event.get("error") in {"json_decode_failed", "json_payload_not_object"}


def optional_object_field(event: dict[str, Any], field: str) -> dict[str, Any] | None:
    value = event.get(field)
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    return None


def malformed_field_reason(field: str) -> str:
    return f"hook payload rejected because {field} must be an object"


def malformed_field_decision(field: str) -> dict[str, str]:
    return {
        "permissionDecision": "deny",
        "permissionDecisionReason": malformed_field_reason(field),
    }


def first_malformed_object_field(event: dict[str, Any], fields: tuple[str, ...]) -> str | None:
    for field in fields:
        if optional_object_field(event, field) is None:
            return field
    return None


def active_task_id(store: RuntimeStore, session_id: str) -> str | None:
    mission = store.get_active_mission(session_id)
    return mission.task_id if mission else None


def _unscoped_receipt_metadata(
    event: dict[str, Any], reason: str, candidates: list[Any] | None = None
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "scope_status": "unscoped",
        "scope_reason": reason,
        "scope_host_session_id": receipt_text(event.get("session_id", "unknown")),
        "scope_cwd": receipt_text(event.get("cwd") or str(REPO_ROOT)),
    }
    if candidates is not None:
        metadata["scope_candidate_count"] = len(candidates)
    return metadata


def receipt_scope_details(
    store: RuntimeStore, event: dict[str, Any], source: str
) -> tuple[str, str | None, dict[str, Any]]:
    session_id = str(event.get("session_id", "unknown"))
    explicit = explicit_mission_binding(store, event, session_id)
    if explicit is not None:
        return explicit.session_id, explicit.task_id, {}
    tool_bound = agent_runway_tool_mission_binding(store, event)
    if tool_bound is not None:
        return tool_bound.session_id, tool_bound.task_id, {}
    tool_name = str(event.get("tool_name") or "")
    tool_input = optional_object_field(event, "tool_input") or {}
    if (
        tool_name.startswith("agent-runway_")
        and isinstance(tool_input.get("session_id"), str)
        and isinstance(tool_input.get("task_id"), str)
    ):
        return session_id, None, _unscoped_receipt_metadata(
            event, "unknown_agent_runway_mission"
        )
    bound = store.bound_active_mission_for_host_session(session_id)
    if bound is not None:
        return bound.session_id, bound.task_id, {}
    mission = store.get_active_mission(session_id)
    if mission is not None:
        return mission.session_id, mission.task_id, {}
    cwd = event.get("cwd") or str(REPO_ROOT)
    candidates = store.list_active_missions_by_cwd(str(cwd))
    if len(candidates) == 1:
        fallback = candidates[0]
        return fallback.session_id, fallback.task_id, {}
    reason = "ambiguous_cwd_mission" if candidates else "no_active_mission_or_binding"
    return session_id, None, _unscoped_receipt_metadata(event, reason, candidates)


def receipt_scope(store: RuntimeStore, event: dict[str, Any], source: str) -> tuple[str, str | None]:
    session_id, task_id, _scope_metadata = receipt_scope_details(store, event, source)
    return session_id, task_id


def explicit_mission_binding(
    store: RuntimeStore, event: dict[str, Any], host_session_id: str
) -> Any | None:
    if str(event.get("hook_event_name") or "") != "OpenCodeToolExecuteAfter":
        return None
    tool_name = str(event.get("tool_name") or "")
    if tool_name not in MISSION_BINDING_TOOLS:
        return None
    tool_input = optional_object_field(event, "tool_input") or {}
    session_id = tool_input.get("session_id")
    task_id = tool_input.get("task_id")
    if not isinstance(session_id, str) or not isinstance(task_id, str):
        return None
    mission = store.get_active_mission(session_id.strip(), task_id.strip())
    if mission is None:
        return None
    store.bind_host_session_to_mission(host_session_id, mission, source=tool_name)
    return mission


def agent_runway_tool_mission_binding(store: RuntimeStore, event: dict[str, Any]) -> Any | None:
    tool_name = str(event.get("tool_name") or "")
    if not tool_name.startswith("agent-runway_"):
        return None
    tool_input = optional_object_field(event, "tool_input") or {}
    session_id = tool_input.get("session_id")
    task_id = tool_input.get("task_id")
    if not isinstance(session_id, str) or not isinstance(task_id, str):
        return None
    try:
        return store.get_mission(session_id.strip(), task_id.strip())
    except KeyError:
        return None


def agent_runway_contract(event: dict[str, Any]) -> dict[str, Any] | None:
    contract = event.get("agent_runway")
    if contract is None:
        return None
    if not isinstance(contract, dict):
        raise ValueError("agent_runway must be an object")
    return contract


def event_host(event: dict[str, Any], default: str = "unknown") -> str:
    host = resolve_event_host(event)
    return default if host == "unknown" else str(host)


def required_contract_text(contract: dict[str, Any], field: str) -> str:
    value = contract.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"agent_runway.{field} must be a non-empty string")
    return value.strip()


def optional_contract_text(contract: dict[str, Any], field: str) -> str:
    value = contract.get(field, "")
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"agent_runway.{field} must be a string")
    return value.strip()


def optional_contract_object(contract: dict[str, Any], field: str) -> dict[str, Any]:
    value = contract.get(field)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"agent_runway.{field} must be an object")
    return value


def optional_contract_list(contract: dict[str, Any], field: str) -> list[str]:
    value = contract.get(field)
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"agent_runway.{field} must be a string list")
    return [item.strip() for item in value if item.strip()]


def contract_enum(contract: dict[str, Any], field: str, allowed: set[str], default: str) -> str:
    value = contract.get(field, default)
    if not isinstance(value, str) or value.strip() not in allowed:
        raise ValueError(f"agent_runway.{field} must be one of {sorted(allowed)}")
    return value.strip()


def contract_mission(store: RuntimeStore, event: dict[str, Any], contract: dict[str, Any]) -> Any:
    task_id = required_contract_text(contract, "task_id")
    session_id = optional_contract_text(contract, "session_id") or str(event.get("session_id", "unknown"))
    direct = store.get_active_mission(session_id, task_id)
    if direct is not None:
        return direct
    cwd = event.get("cwd")
    if not cwd:
        raise ValueError(f"agent_runway.task_id has no active parent mission: {task_id!r}")
    matches = [
        mission
        for mission in store.list_active_missions_by_cwd(str(cwd))
        if mission.task_id == task_id
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError(
            "agent_runway.task_id matched multiple active cwd missions; include parent session_id"
        )
    raise ValueError(f"agent_runway.task_id has no active parent mission: {task_id!r}")


def record_subagent_visibility_event(
    store: RuntimeStore, event: dict[str, Any], source: str
) -> dict[str, Any]:
    session_id, task_id, scope_metadata = receipt_scope_details(store, event, source)
    receipt = store.record_receipt(
        session_id=session_id,
        task_id=task_id,
        source=source,
        tool_name=str(event.get("hook_event_name") or source),
        command_text=compact_text(event.get("subagent") or event.get("agent") or "visible subagent event"),
        exit_code=None,
        metadata={
            "hook_event": event.get("hook_event_name"),
            "visibility_only": True,
            **scope_metadata,
        },
    )
    return {"recorded": True, "receipt_id": receipt.receipt_id, "task_id": receipt.task_id}


def json_response(payload: dict[str, Any]) -> int:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))
    sys.stdout.flush()
    return 0


def hook_entrypoint(func: Callable[[dict[str, Any]], int]) -> Callable[[dict[str, Any]], int]:
    @wraps(func)
    def wrapper(event: dict[str, Any]) -> int:
        try:
            return func(event)
        except Exception as exc:
            write_debug_log("hook.error", hook_error_details(func.__name__, event, exc))
            raise

    return wrapper


def hook_error_details(entrypoint: str, event: Any, exc: Exception) -> dict[str, Any]:
    return {
        "entrypoint": entrypoint,
        "exception_type": type(exc).__name__,
        "error_message": str(exc),
        "session_id": event.get("session_id") if isinstance(event, dict) else None,
        "tool_name": event.get("tool_name") if isinstance(event, dict) else None,
        "event_keys": sorted(event) if isinstance(event, dict) else [],
        "payload_type": type(event).__name__,
        "traceback": traceback.format_exception(type(exc), exc, exc.__traceback__),
    }


def log_hook_validation_error(details: dict[str, Any]) -> None:
    event = details.get("event")
    write_debug_log(
        "hook.validation_error",
        {
            "entrypoint": details.get("entrypoint"),
            "source": details.get("source"),
            "error": details.get("error"),
            "field": details.get("field", ""),
            "session_id": event.get("session_id") if isinstance(event, dict) else None,
            "tool_name": event.get("tool_name") if isinstance(event, dict) else None,
        },
    )


@hook_entrypoint
def session_start(event: dict[str, Any]) -> int:
    write_debug_log("session_start", {"session_id": event.get("session_id"), "cwd": event.get("cwd")})
    if event_parse_failed(event):
        log_hook_validation_error(
            {"entrypoint": "session_start", "event": event, "error": event.get("error") or "parse_failed"}
        )
        return 0

    store = build_store(event)
    host = resolve_event_host(event)
    store.ensure_session(
        session_id=event.get("session_id", "unknown"),
        host=str(host),
        cwd=event.get("cwd") or str(REPO_ROOT),
    )
    return 0


def pre_tool_use_decision(
    tool_name: str,
    tool_input: dict[str, Any],
    cwd: str | None = None,
) -> dict[str, str] | None:
    if tool_name in SHELL_LIKE_TOOLS:
        command = shell_command_text(tool_input)
        # Secret-path reads must fail closed before generic risky-command prompts.
        # Otherwise commands such as curl file://<secret> would be downgraded
        # from deny to ask, which weakens the secret boundary.
        if _bash_reads_protected_path(command, cwd):
            return {
                "permissionDecision": "deny",
                "permissionDecisionReason": "Protected secret, state, or credential paths are not readable by the agent.",
            }
        lowered = " ".join(command.lower().split())
        if any(pattern in lowered for pattern in NORMALIZED_DANGEROUS_BASH_PATTERNS):
            return {
                "permissionDecision": "ask",
                "permissionDecisionReason": f"Risky command requires host confirmation: {command[:200]}",
            }

    for key in ("file_path", "filePath", "path"):
        path = tool_input.get(key)
        if isinstance(path, str) and _matches_protected_read_path(path, cwd):
            return {
                "permissionDecision": "deny",
                "permissionDecisionReason": "Protected secret, state, or credential paths are not readable by the agent.",
            }
    return None


def _extract_exit_code(tool_response: dict[str, Any]) -> int | None:
    for key in ("exit_code", "exitCode", "exit"):
        if key in tool_response:
            return _normalized_exit_code(tool_response.get(key))
    metadata = tool_response.get("metadata")
    if isinstance(metadata, dict):
        for key in ("exitCode", "exit_code", "exit"):
            if key in metadata:
                return _normalized_exit_code(metadata.get(key))
    return None


def _normalized_exit_code(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if re.fullmatch(r"-?\d+", stripped):
            return int(stripped)
    return None


def _extract_duration_seconds(tool_response: dict[str, Any]) -> int | float | None:
    for source in (tool_response, tool_response.get("metadata")):
        if not isinstance(source, dict):
            continue
        value = _first_present(
            source,
            ("duration_seconds", "durationSeconds", "elapsed_seconds", "elapsedSeconds"),
        )
        if _valid_duration_number(value):
            return value
        milliseconds = _first_present(source, ("duration_ms", "durationMs", "elapsed_ms", "elapsedMs"))
        if _valid_duration_number(milliseconds):
            return milliseconds / 1000
    return None


def _valid_duration_number(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and value >= 0
        and math.isfinite(float(value))
    )


def _first_present(source: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in source:
            return source[key]
    return None


def agent_runway_tool_metadata(tool_name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
    if not tool_name.startswith("agent-runway_"):
        return {}
    gate_name = tool_name.removeprefix("agent-runway_")
    metadata: dict[str, Any] = {"agent_runway_tool": gate_name}
    if gate_name == "turn_end_gate":
        metadata["gate_type"] = "turn_end_gate"
        metadata["stop_condition"] = receipt_text(tool_input.get("stop_condition", ""))
        metadata["work_summary_preview"] = compact_text(tool_input.get("work_summary", ""))
        metadata["work_summary_sha256"] = sha256_text(str(tool_input.get("work_summary", "")))
        receipt_ids = tool_input.get("receipt_ids")
        if isinstance(receipt_ids, list):
            metadata["receipt_ids"] = [receipt_text(item) for item in receipt_ids]
    elif gate_name == "completion_gate":
        metadata["gate_type"] = "completion_gate"
        summary = receipt_text(tool_input.get("completion_summary", ""))
        metadata["completion_summary"] = summary
        metadata["completion_summary_preview"] = compact_text(summary)
        metadata["completion_summary_sha256"] = sha256_text(summary)
        criterion_map = tool_input.get("criterion_receipt_map")
        if isinstance(criterion_map, list):
            metadata["criterion_receipt_map"] = criterion_map
    elif gate_name in {"mission_lock", "prompt_intake_gate"}:
        metadata["gate_type"] = gate_name
    return metadata


def record_tool_use_event(event: dict[str, Any], source: str) -> dict[str, Any]:
    malformed = first_malformed_object_field(event, ("tool_input", "tool_response"))
    if malformed is not None:
        log_hook_validation_error(
            {"source": source, "event": event, "error": "malformed_field", "field": malformed}
        )
        return {"recorded": False, "reason": malformed_field_reason(malformed)}

    store = build_store(event)
    session_id, task_id, scope_metadata = receipt_scope_details(store, event, source)
    tool_name = canonical_tool_name(event.get("tool_name", ""))
    tool_input = optional_object_field(event, "tool_input") or {}
    tool_response = optional_object_field(event, "tool_response") or {}

    metadata: dict[str, Any] = {
        "hook_event": event.get("hook_event_name"),
        **scope_metadata,
        **agent_runway_tool_metadata(tool_name, tool_input),
    }
    duration_seconds = _extract_duration_seconds(tool_response)
    if duration_seconds is not None:
        metadata["duration_seconds"] = duration_seconds
    command_text: str | None = None
    exit_code: int | None = None

    if tool_name in SHELL_LIKE_TOOLS:
        command = shell_command_text(tool_input)
        command_text = receipt_text(command or compact_text(tool_input))
        exit_code = _extract_exit_code(tool_response)
        stdout_text = tool_response.get("stdout") or tool_response.get("output") or ""
        stderr_text = tool_response.get("stderr") or ""
        metadata.update(
            {
                "stdout_sha256": sha256_text(str(stdout_text)),
                "stderr_sha256": sha256_text(str(stderr_text)),
                "stdout_preview": compact_text(stdout_text),
                "stderr_preview": compact_text(stderr_text),
            }
        )
    elif tool_name in MUTATION_TOOLS:
        path = tool_input.get("file_path") or tool_input.get("filePath") or tool_input.get("path")
        if isinstance(path, str):
            command_text = receipt_text(path)
            metadata.update({"file_path": command_text, "file_sha256": sha256_file(path)})
            exit_code = 0
    elif tool_name in OBSERVATION_TOOLS:
        path = (
            tool_input.get("file_path")
            or tool_input.get("filePath")
            or tool_input.get("path")
            or tool_input.get("pattern")
            or ""
        )
        command_text = receipt_text(path) if path else None
        metadata.update({"selector": compact_text(path)})
        exit_code = 0
    else:
        command_text = compact_text(tool_input)
        exit_code = _extract_exit_code(tool_response)

    receipt = store.record_receipt(
        session_id=session_id,
        task_id=task_id,
        source=source,
        tool_name=tool_name,
        command_text=command_text,
        exit_code=exit_code,
        metadata=metadata,
    )
    return {
        "recorded": True,
        "receipt_id": receipt.receipt_id,
        "tool_name": receipt.tool_name,
        "task_id": receipt.task_id,
        "exit_code": receipt.exit_code,
    }


def record_hook_decision_event(
    event: dict[str, Any],
    source: str,
    hook_event_name: str,
    decision: str,
    reason: str,
    extra_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    store = build_store(event)
    session_id, task_id, scope_metadata = receipt_scope_details(store, event, source)
    target_tool = canonical_tool_name(str(event.get("tool_name", "")))
    metadata = {
        "hook_event": hook_event_name,
        "hook_decision": decision,
        "hook_reason": receipt_text(reason),
        "target_tool_name": target_tool,
        **scope_metadata,
        **(extra_metadata or {}),
    }
    receipt = store.record_receipt(
        session_id=session_id,
        task_id=task_id,
        source=source,
        tool_name=hook_event_name,
        command_text=hook_decision_command_text(event, target_tool, reason),
        exit_code=hook_decision_exit_code(decision),
        metadata=metadata,
    )
    return {
        "recorded": True,
        "receipt_id": receipt.receipt_id,
        "tool_name": receipt.tool_name,
        "task_id": receipt.task_id,
        "exit_code": receipt.exit_code,
    }


def hook_decision_command_text(event: dict[str, Any], target_tool: str, reason: str) -> str:
    tool_input = optional_object_field(event, "tool_input")
    if tool_input is None:
        return compact_text(reason)
    if target_tool in SHELL_LIKE_TOOLS:
        return receipt_text(shell_command_text(tool_input) or compact_text(tool_input))
    if target_tool:
        return compact_text({"tool_name": target_tool, "tool_input": tool_input})
    return compact_text(reason)


def hook_decision_exit_code(decision: str) -> int | None:
    return 1 if decision in {"deny", "block"} else None


@hook_entrypoint
def pre_tool_use(event: dict[str, Any]) -> int:
    write_debug_log(
        "pre_tool_use",
        {
            "session_id": event.get("session_id"),
            "tool_name": event.get("tool_name"),
            "tool_input": event.get("tool_input"),
        },
    )
    parse_failure = parse_failure_decision(event)
    if parse_failure is not None:
        log_hook_validation_error(
            {"entrypoint": "pre_tool_use", "event": event, "error": event.get("error") or "parse_failed"}
        )
        return json_response(
            {"hookSpecificOutput": {"hookEventName": "PreToolUse", **parse_failure}}
        )

    tool_name = canonical_tool_name(event.get("tool_name", ""))
    tool_input = optional_object_field(event, "tool_input")
    if tool_input is None:
        log_hook_validation_error(
            {"entrypoint": "pre_tool_use", "event": event, "error": "malformed_field", "field": "tool_input"}
        )
        return json_response(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    **malformed_field_decision("tool_input"),
                }
            }
        )

    decision = pre_tool_use_decision(tool_name, tool_input, event.get("cwd"))
    if decision is not None:
        record_hook_decision_event(
            event,
            source="claude-hook",
            hook_event_name="PreToolUse",
            decision=decision["permissionDecision"],
            reason=decision["permissionDecisionReason"],
        )
        return json_response(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    **decision,
                }
            }
        )

    return 0


@hook_entrypoint
def post_tool_use(event: dict[str, Any]) -> int:
    write_debug_log(
        "post_tool_use",
        {
            "session_id": event.get("session_id"),
            "tool_name": event.get("tool_name"),
            "tool_input": event.get("tool_input"),
        },
    )
    if event_parse_failed(event):
        log_hook_validation_error(
            {"entrypoint": "post_tool_use", "event": event, "error": event.get("error") or "parse_failed"}
        )
        return 0

    record_tool_use_event(event, source="claude-hook")
    return 0


@hook_entrypoint
def subagent_start(event: dict[str, Any]) -> int:
    write_debug_log("subagent_start", {"session_id": event.get("session_id")})
    if event_parse_failed(event):
        log_hook_validation_error(
            {"entrypoint": "subagent_start", "event": event, "error": event.get("error") or "parse_failed"}
        )
        return 0

    store = build_store(event)
    contract = agent_runway_contract(event)
    if contract is None:
        record_subagent_visibility_event(store, event, source="claude-subagent-hook")
        return 0

    mission = contract_mission(store, event, contract)
    span = store.create_subagent_span(
        mission.session_id,
        mission.task_id,
        {
            "host": event_host(event, default="claude-code"),
            "subagent_type": required_contract_text(contract, "subagent_type"),
            "host_child_id": optional_contract_text(contract, "host_child_id"),
            "context_mode": contract_enum(contract, "context_mode", SUBAGENT_CONTEXT_MODES, "fresh"),
            "workspace_kind": contract_enum(
                contract, "workspace_kind", SUBAGENT_WORKSPACE_KINDS, "shared_checkout"
            ),
            "delegated_scope": required_contract_text(contract, "delegated_scope"),
            "delegated_budget": optional_contract_object(contract, "delegated_budget"),
        },
    )
    return json_response({"child_span_id": span.child_span_id, "status": span.status})


@hook_entrypoint
def subagent_stop(event: dict[str, Any]) -> int:
    write_debug_log("subagent_stop", {"session_id": event.get("session_id")})
    if event_parse_failed(event):
        log_hook_validation_error(
            {"entrypoint": "subagent_stop", "event": event, "error": event.get("error") or "parse_failed"}
        )
        return 0

    store = build_store(event)
    contract = agent_runway_contract(event)
    if contract is None:
        record_subagent_visibility_event(store, event, source="claude-subagent-hook")
        return 0

    mission = contract_mission(store, event, contract)
    span = store.stop_subagent_span(
        mission.session_id,
        mission.task_id,
        required_contract_text(contract, "child_span_id"),
        {
            "status": contract_enum(contract, "status", SUBAGENT_STOP_STATUSES, "completed"),
            "budget_consumed": optional_contract_object(contract, "budget_consumed"),
            "transcript_ref": optional_contract_text(contract, "transcript_ref"),
            "artifact_refs": optional_contract_list(contract, "artifact_refs"),
            "last_message": optional_contract_text(contract, "last_message"),
        },
    )
    return json_response({"child_span_id": span.child_span_id, "status": span.status})


@hook_entrypoint
def stop(event: dict[str, Any]) -> int:
    write_debug_log("stop", {"session_id": event.get("session_id")})
    parse_failure = parse_failure_stop_response(event)
    if parse_failure is not None:
        log_hook_validation_error(
            {"entrypoint": "stop", "event": event, "error": event.get("error") or "parse_failed"}
        )
        return json_response(parse_failure)

    store = build_store(event)
    session_id = event.get("session_id", "unknown")
    mission = store.get_active_mission(session_id)
    if mission is None:
        mission = store.get_latest_mission(session_id)
    if mission is None:
        return 0

    gate_type = "completion_gate" if mission.status == "completed" else "turn_end_gate"
    approval = store.latest_approval(session_id, mission.task_id, gate_type=gate_type)
    if store.is_approval_fresh(approval, session_id, mission.task_id):
        return 0

    reason = (
        f"Active mission {mission.task_id!r} has no fresh {gate_type} approval after the latest receipt. "
        f"Call the MCP gate before stopping."
    )
    record_hook_decision_event(
        event,
        source="claude-hook",
        hook_event_name="Stop",
        decision="block",
        reason=reason,
        extra_metadata={"gate_type": gate_type, "mission_status": mission.status},
    )
    return json_response({"continue": False, "stopReason": reason})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "event",
        choices=["session-start", "pre-tool-use", "post-tool-use", "subagent-start", "subagent-stop", "stop"],
    )
    args = parser.parse_args()
    event = load_event()
    if args.event == "session-start":
        return session_start(event)
    if args.event == "pre-tool-use":
        return pre_tool_use(event)
    if args.event == "post-tool-use":
        return post_tool_use(event)
    if args.event == "subagent-start":
        return subagent_start(event)
    if args.event == "subagent-stop":
        return subagent_stop(event)
    if args.event == "stop":
        return stop(event)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
