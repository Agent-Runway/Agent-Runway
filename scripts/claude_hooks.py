#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

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

PROTECTED_PATHS = [
    str(
        Path(
            os.environ.get("ILH_SECRET_PATH", "~/.config/agent-runway/secret.key")
        ).expanduser()
    ),
    str(
        Path(
            os.environ.get("ILH_DB_PATH", str(REPO_ROOT / ".agent-runway" / "state.db"))
        ).expanduser()
    ),
]

HOME_ENV_ALIASES = ["$HOME", "%USERPROFILE%", "$env:USERPROFILE"]


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
        sys.stderr.write(
            f"[{source}] failed to parse stdin JSON; "
            f"sha256={hashlib.sha256(preview.encode('utf-8', errors='replace')).hexdigest()} "
            f"error={exc.msg} line={exc.lineno} column={exc.colno}\n"
        )
        return {
            "error": "json_decode_failed",
            "raw_preview_sha256": hashlib.sha256(
                preview.encode("utf-8", errors="replace")
            ).hexdigest(),
            "line": exc.lineno,
            "column": exc.colno,
        }
    if isinstance(payload, dict):
        return payload
    payload_type = type(payload).__name__
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
    return hashlib.sha256(file_path.read_bytes()).hexdigest()


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


def _matches_secret_path(path: str) -> bool:
    normalized = _normalized_path_text(path)
    return any(
        normalized in _secret_path_variants(secret_path) for secret_path in PROTECTED_PATHS
    )


def _bash_reads_secret(command: str) -> bool:
    normalized_command = _security_fold(command)
    for secret_path in PROTECTED_PATHS:
        secret_variants = _secret_path_variants(secret_path)
        if any(variant in normalized_command for variant in secret_variants):
            return True
    return False


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


def receipt_scope(store: RuntimeStore, event: dict[str, Any], source: str) -> tuple[str, str | None]:
    session_id = str(event.get("session_id", "unknown"))
    mission = store.get_active_mission(session_id)
    if mission is not None:
        return mission.session_id, mission.task_id
    cwd = event.get("cwd") or str(REPO_ROOT)
    fallback = store.get_latest_active_mission_by_cwd(str(cwd))
    if fallback is None:
        return session_id, None
    return fallback.session_id, fallback.task_id


def json_response(payload: dict[str, Any]) -> int:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))
    sys.stdout.flush()
    return 0


def session_start(event: dict[str, Any]) -> int:
    write_debug_log("session_start", {"session_id": event.get("session_id"), "cwd": event.get("cwd")})
    if event_parse_failed(event):
        return 0

    store = build_store(event)
    host = resolve_event_host(event)
    store.ensure_session(
        session_id=event.get("session_id", "unknown"),
        host=str(host),
        cwd=event.get("cwd") or str(REPO_ROOT),
    )
    return 0


def pre_tool_use_decision(tool_name: str, tool_input: dict[str, Any]) -> dict[str, str] | None:
    if tool_name in SHELL_LIKE_TOOLS:
        command = shell_command_text(tool_input)
        # Secret-path reads must fail closed before generic risky-command prompts.
        # Otherwise commands such as curl file://<secret> would be downgraded
        # from deny to ask, which weakens the secret boundary.
        if _bash_reads_secret(command):
            return {
                "permissionDecision": "deny",
                "permissionDecisionReason": "Harness secret/state protected paths are not readable by the agent.",
            }
        lowered = " ".join(command.lower().split())
        if any(pattern in lowered for pattern in NORMALIZED_DANGEROUS_BASH_PATTERNS):
            return {
                "permissionDecision": "ask",
                "permissionDecisionReason": f"Risky command requires host confirmation: {command[:200]}",
            }

    for key in ("file_path", "filePath", "path"):
        path = tool_input.get(key)
        if isinstance(path, str) and _matches_secret_path(path):
            return {
                "permissionDecision": "deny",
                "permissionDecisionReason": "Harness secret/state protected paths are not readable by the agent.",
            }
    return None


def _extract_exit_code(tool_response: dict[str, Any]) -> int | None:
    if "exit_code" in tool_response:
        return tool_response.get("exit_code")
    metadata = tool_response.get("metadata")
    if isinstance(metadata, dict):
        if "exitCode" in metadata:
            return metadata.get("exitCode")
        if "exit_code" in metadata:
            return metadata.get("exit_code")
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


def record_tool_use_event(event: dict[str, Any], source: str) -> dict[str, Any]:
    malformed = first_malformed_object_field(event, ("tool_input", "tool_response"))
    if malformed is not None:
        return {"recorded": False, "reason": malformed_field_reason(malformed)}

    store = build_store(event)
    session_id, task_id = receipt_scope(store, event, source)
    tool_name = canonical_tool_name(event.get("tool_name", ""))
    tool_input = optional_object_field(event, "tool_input") or {}
    tool_response = optional_object_field(event, "tool_response") or {}

    metadata: dict[str, Any] = {"hook_event": event.get("hook_event_name")}
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
        return json_response(
            {"hookSpecificOutput": {"hookEventName": "PreToolUse", **parse_failure}}
        )

    tool_name = canonical_tool_name(event.get("tool_name", ""))
    tool_input = optional_object_field(event, "tool_input")
    if tool_input is None:
        return json_response(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    **malformed_field_decision("tool_input"),
                }
            }
        )

    decision = pre_tool_use_decision(tool_name, tool_input)
    if decision is not None:
        return json_response(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    **decision,
                }
            }
        )

    return 0


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
        return 0

    record_tool_use_event(event, source="claude-hook")
    return 0


def stop(event: dict[str, Any]) -> int:
    write_debug_log("stop", {"session_id": event.get("session_id")})
    parse_failure = parse_failure_stop_response(event)
    if parse_failure is not None:
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
    return json_response({"continue": False, "stopReason": reason})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "event", choices=["session-start", "pre-tool-use", "post-tool-use", "stop"]
    )
    args = parser.parse_args()
    event = load_event()
    if args.event == "session-start":
        return session_start(event)
    if args.event == "pre-tool-use":
        return pre_tool_use(event)
    if args.event == "post-tool-use":
        return post_tool_use(event)
    if args.event == "stop":
        return stop(event)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
