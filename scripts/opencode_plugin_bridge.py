#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

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
        str(key): str(value)
        for key, value in environment.items()
        if value is not None
    }


def _config_environment_from_content() -> dict[str, str] | None:
    content = os.environ.get("OPENCODE_CONFIG_CONTENT")
    if not content:
        return None
    try:
        return _agent_runway_environment(json.loads(content))
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
                json.loads(path.read_text(encoding="utf-8"))
            )
        except (OSError, json.JSONDecodeError):
            continue
        if environment is not None:
            return environment
    return None


def configure_bridge_environment() -> None:
    sys.dont_write_bytecode = True
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    environment = _config_environment_from_content() or _config_environment_from_files()
    if environment is None:
        return
    for key, value in environment.items():
        os.environ.setdefault(key, value)


configure_bridge_environment()

import claude_hooks  # noqa: E402


def load_event() -> dict[str, Any]:
    return claude_hooks.decode_event_payload(
        sys.stdin.read(), "opencode-plugin-bridge"
    )


def session_created(event: dict[str, Any]) -> dict[str, Any]:
    if claude_hooks.event_parse_failed(event):
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


def pre_tool_use(event: dict[str, Any]) -> dict[str, Any]:
    if event.get("error") == "json_decode_failed":
        return {
            "decision": "deny",
            "reason": "tool use denied because the bridge could not parse the pre-tool event payload",
        }
    tool_name = claude_hooks.canonical_tool_name(str(event.get("tool_name", "")))
    tool_input = event.get("tool_input", {}) or {}
    decision = claude_hooks.pre_tool_use_decision(tool_name, tool_input)
    if decision is None:
        return {"decision": "allow"}
    return {
        "decision": decision["permissionDecision"],
        "reason": decision["permissionDecisionReason"],
    }


def post_tool_use(event: dict[str, Any]) -> dict[str, Any]:
    if claude_hooks.event_parse_failed(event):
        return {"recorded": False}

    tool_input = event.get("tool_input", {}) or {}
    tool_response = event.get("tool_response", {}) or {}
    raw_tool_name = str(event.get("tool_name", ""))
    canonical = claude_hooks.canonical_tool_name(raw_tool_name)
    if canonical in claude_hooks.SHELL_LIKE_TOOLS:
        tool_name = canonical
        normalized_input = {
            "command": tool_input.get("command") or tool_input.get("cmd") or tool_input.get("prompt") or tool_input.get("task") or "",
        }
    else:
        tool_name = canonical
        normalized_input = {
            "filePath": tool_input.get("filePath") or tool_input.get("file_path") or tool_input.get("path") or "",
            "path": tool_input.get("path") or tool_input.get("filePath") or tool_input.get("file_path") or "",
            "pattern": tool_input.get("pattern") or "",
        }

    normalized = {
        "session_id": event.get("session_id", "unknown"),
        "cwd": event.get("cwd") or str(REPO_ROOT),
        "tool_name": tool_name,
        "tool_input": normalized_input,
        "tool_response": {
            "output": tool_response.get("output") or tool_response.get("stdout") or "",
            "stderr": tool_response.get("stderr") or "",
            "metadata": tool_response.get("metadata") or {},
        },
        "hook_event_name": event.get("hook_event_name", "OpenCodeToolExecuteAfter"),
    }
    return claude_hooks.record_tool_use_event(normalized, source="opencode-plugin")


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
