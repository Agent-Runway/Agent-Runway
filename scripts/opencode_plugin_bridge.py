#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from functools import wraps
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
MCP_ROOT = REPO_ROOT / "mcp"
if str(MCP_ROOT) not in sys.path:
    sys.path.insert(0, str(MCP_ROOT))

CONFIG_CANDIDATES = [
    os.environ.get("OPENCODE_CONFIG_PATH"),
    str(Path.cwd() / ".opencode" / "opencode.json"),
    str(Path.cwd() / "opencode.json"),
    str(Path.home() / ".config" / "opencode" / "opencode.json"),
    str(Path.home() / ".config" / "opencode" / "config.json"),
]


def _parse_config_text(content: str) -> object:
    result: list[str] = []
    in_string = False
    escaping = False
    index = 0
    while index < len(content):
        char = content[index]
        if in_string:
            result.append(char)
            if escaping:
                escaping = False
            elif char == "\\":
                escaping = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            result.append(char)
            index += 1
            continue
        if char == "/" and index + 1 < len(content) and content[index + 1] == "/":
            index += 2
            while index < len(content) and content[index] not in "\r\n":
                index += 1
            if index < len(content):
                result.append(content[index])
            index += 1
            continue
        if char == "/" and index + 1 < len(content) and content[index + 1] == "*":
            index += 2
            while index + 1 < len(content) and content[index : index + 2] != "*/":
                index += 1
            if index + 1 >= len(content):
                raise json.JSONDecodeError(
                    "unterminated block comment in OpenCode config", content, index
                )
            index += 2
            continue
        if char == ",":
            lookahead = _next_significant_config_char(content, index + 1)
            if lookahead < len(content) and content[lookahead] in "}]":
                index += 1
                continue
        result.append(char)
        index += 1
    return json.loads("".join(result))


def _next_significant_config_char(content: str, start: int) -> int:
    index = start
    while index < len(content):
        if content[index].isspace():
            index += 1
            continue
        if content[index : index + 2] == "//":
            index += 2
            while index < len(content) and content[index] not in "\r\n":
                index += 1
            continue
        if content[index : index + 2] == "/*":
            index += 2
            while index + 1 < len(content) and content[index : index + 2] != "*/":
                index += 1
            if index + 1 >= len(content):
                raise json.JSONDecodeError(
                    "unterminated block comment in OpenCode config", content, index
                )
            index += 2
            continue
        break
    return index


def _agent_runway_environment(config: object) -> dict[str, str] | None:
    if not isinstance(config, dict):
        return None
    mcp = config.get("mcp")
    if not isinstance(mcp, dict):
        return None
    server = mcp.get("agent-runway")
    if not isinstance(server, dict):
        return None
    environment = server.get("environment")
    if not isinstance(environment, dict):
        return None
    return {
        key: str(value)
        for key, value in environment.items()
        if isinstance(key, str) and key.strip() and value is not None
    }


def _config_environment_from_content() -> dict[str, str] | None:
    content = os.environ.get("OPENCODE_CONFIG_CONTENT")
    if not content:
        return None
    try:
        return _agent_runway_environment(_parse_config_text(content))
    except json.JSONDecodeError:
        return None


def _config_environment_from_files() -> dict[str, str] | None:
    for candidate in CONFIG_CANDIDATES:
        if not candidate:
            continue
        path = Path(candidate)
        if not path.exists():
            continue
        try:
            environment = _agent_runway_environment(
                _parse_config_text(path.read_text(encoding="utf-8"))
            )
        except (OSError, json.JSONDecodeError):
            continue
        if environment is not None:
            return environment
    return None


def configure_bridge_environment() -> None:
    sys.dont_write_bytecode = True
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    environment = _config_environment_from_content() or _config_environment_from_files()
    if environment is None:
        return
    for key, value in environment.items():
        os.environ.setdefault(key, value)


configure_bridge_environment()

import claude_hooks  # noqa: E402
from agent_runway_runtime.debug_logging import write_debug_log  # noqa: E402


def load_event() -> dict[str, Any]:
    return claude_hooks.decode_event_payload(
        sys.stdin.read(), "opencode-plugin-bridge"
    )


def bridge_entrypoint(func: Callable[[dict[str, Any]], dict[str, Any]]) -> Callable[[dict[str, Any]], dict[str, Any]]:
    @wraps(func)
    def wrapper(event: dict[str, Any]) -> dict[str, Any]:
        try:
            return func(event)
        except Exception as exc:
            write_debug_log("opencode_bridge.error", bridge_error_details(func.__name__, event, exc))
            raise

    return wrapper


def bridge_error_details(entrypoint: str, event: Any, exc: Exception) -> dict[str, Any]:
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


def log_bridge_validation_error(details: dict[str, Any]) -> None:
    event = details.get("event")
    write_debug_log(
        "opencode_bridge.validation_error",
        {
            "entrypoint": details.get("entrypoint"),
            "error": details.get("error"),
            "field": details.get("field", ""),
            "session_id": event.get("session_id") if isinstance(event, dict) else None,
            "tool_name": event.get("tool_name") if isinstance(event, dict) else None,
        },
    )


@bridge_entrypoint
def session_created(event: dict[str, Any]) -> dict[str, Any]:
    write_debug_log(
        "opencode_bridge.session_created",
        {"session_id": event.get("session_id"), "cwd": event.get("cwd")},
    )
    if claude_hooks.event_parse_failed(event):
        log_bridge_validation_error(
            {"entrypoint": "session_created", "event": event, "error": event.get("error") or "parse_failed"}
        )
        return {"recorded": False}

    normalized = {
        "session_id": event.get("session_id", "unknown"),
        "host": event.get("host") or "OpenCode",
        "cwd": event.get("cwd") or str(REPO_ROOT),
    }
    claude_hooks.session_start(normalized)
    return {
        "recorded": True,
        "session_id": normalized["session_id"],
        "host": normalized["host"],
    }


@bridge_entrypoint
def pre_tool_use(event: dict[str, Any]) -> dict[str, Any]:
    write_debug_log(
        "opencode_bridge.pre_tool_use",
        {"session_id": event.get("session_id"), "tool_name": event.get("tool_name"), "tool_input": event.get("tool_input")},
    )
    if claude_hooks.event_parse_failed(event):
        log_bridge_validation_error(
            {"entrypoint": "pre_tool_use", "event": event, "error": event.get("error") or "parse_failed"}
        )
        return {
            "decision": "deny",
            "reason": "tool use denied because the bridge could not parse the pre-tool event payload",
        }
    tool_name = claude_hooks.canonical_tool_name(str(event.get("tool_name", "")))
    tool_input = claude_hooks.optional_object_field(event, "tool_input")
    if tool_input is None:
        log_bridge_validation_error(
            {"entrypoint": "pre_tool_use", "event": event, "error": "malformed_field", "field": "tool_input"}
        )
        return _deny_malformed_field("tool_input")
    decision = claude_hooks.pre_tool_use_decision(tool_name, tool_input, event.get("cwd"))
    if decision is None:
        return {"decision": "allow"}
    claude_hooks.record_hook_decision_event(
        event,
        source="opencode-plugin",
        hook_event_name="OpenCodeToolExecuteBefore",
        decision=decision["permissionDecision"],
        reason=decision["permissionDecisionReason"],
    )
    return {
        "decision": decision["permissionDecision"],
        "reason": decision["permissionDecisionReason"],
    }


@bridge_entrypoint
def post_tool_use(event: dict[str, Any]) -> dict[str, Any]:
    write_debug_log(
        "opencode_bridge.post_tool_use",
        {"session_id": event.get("session_id"), "tool_name": event.get("tool_name"), "tool_input": event.get("tool_input")},
    )
    if claude_hooks.event_parse_failed(event):
        log_bridge_validation_error(
            {"entrypoint": "post_tool_use", "event": event, "error": event.get("error") or "parse_failed"}
        )
        return {"recorded": False}

    malformed = claude_hooks.first_malformed_object_field(
        event, ("tool_input", "tool_response")
    )
    if malformed is not None:
        log_bridge_validation_error(
            {"entrypoint": "post_tool_use", "event": event, "error": "malformed_field", "field": malformed}
        )
        return {"recorded": False, "reason": _malformed_field_reason(malformed)}

    normalized = {
        "session_id": event.get("session_id", "unknown"),
        "cwd": event.get("cwd") or str(REPO_ROOT),
        "tool_name": _normalized_tool_name(event),
        "tool_input": _normalized_tool_input(event),
        "tool_response": _normalized_tool_response(event),
        "hook_event_name": event.get("hook_event_name", "OpenCodeToolExecuteAfter"),
    }
    return claude_hooks.record_tool_use_event(normalized, source="opencode-plugin")


def _normalized_tool_name(event: dict[str, Any]) -> str:
    return claude_hooks.canonical_tool_name(str(event.get("tool_name", "")))


def _normalized_tool_input(event: dict[str, Any]) -> dict[str, Any]:
    tool_input = claude_hooks.optional_object_field(event, "tool_input") or {}
    canonical = _normalized_tool_name(event)
    if canonical in claude_hooks.SHELL_LIKE_TOOLS:
        return {
            "command": tool_input.get("command") or tool_input.get("cmd") or tool_input.get("prompt") or tool_input.get("task") or "",
        }
    if canonical.startswith("agent-runway_"):
        return tool_input
    return {
        "filePath": tool_input.get("filePath") or tool_input.get("file_path") or tool_input.get("path") or "",
        "path": tool_input.get("path") or tool_input.get("filePath") or tool_input.get("file_path") or "",
        "pattern": tool_input.get("pattern") or "",
    }


def _normalized_tool_response(event: dict[str, Any]) -> dict[str, Any]:
    tool_response = claude_hooks.optional_object_field(event, "tool_response") or {}
    metadata = tool_response.get("metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}
    normalized_response: dict[str, Any] = {
        "output": tool_response.get("output") or tool_response.get("stdout") or "",
        "stderr": tool_response.get("stderr") or "",
        "metadata": metadata,
    }
    for key in ("exit", "exitCode", "exit_code"):
        if key in tool_response:
            normalized_response[key] = tool_response[key]
    for key in ("durationMs", "duration_ms", "durationSeconds", "duration_seconds"):
        if key in tool_response:
            normalized_response[key] = tool_response[key]
    return normalized_response


def _malformed_field_reason(field: str) -> str:
    return claude_hooks.malformed_field_reason(field)


def _deny_malformed_field(field: str) -> dict[str, str]:
    return {"decision": "deny", "reason": _malformed_field_reason(field)}


def emit(payload: dict[str, Any]) -> int:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))
    sys.stdout.flush()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "event", choices=["session-created", "pre-tool-use", "post-tool-use"]
    )
    args = parser.parse_args()
    event = load_event()
    if args.event == "session-created":
        return emit(session_created(event))
    if args.event == "pre-tool-use":
        return emit(pre_tool_use(event))
    if args.event == "post-tool-use":
        return emit(post_tool_use(event))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
