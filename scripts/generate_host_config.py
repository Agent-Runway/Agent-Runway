#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import re
from pathlib import Path, PureWindowsPath

import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
MCP_ROOT = REPO_ROOT / "mcp"
if str(MCP_ROOT) not in sys.path:
    sys.path.insert(0, str(MCP_ROOT))

from agent_runway_runtime.host_adapters import SUPPORTED_HOST_KEYS, get_host_adapter  # noqa: E402
import claude_hooks  # noqa: E402

WINDOWS_ABSOLUTE_RE = re.compile(r"^[A-Za-z]:[\\/]")


def resolve_agent_runway_dir(raw_path: str) -> Path:
    if WINDOWS_ABSOLUTE_RE.match(raw_path):
        return PureWindowsPath(raw_path)
    return Path(raw_path).resolve()


def debug_env(agent_runway_dir: Path, enabled: bool) -> dict[str, str]:
    if not enabled:
        return {}
    return {"ILH_DEBUG": "1"}


def claude_hook_command_path(path: Path) -> str:
    return str(path).replace("\\", "/")


def build_claude_code_settings(agent_runway_dir: Path, secret_path: str, debug: bool = False) -> dict:
    hook_path = agent_runway_dir / "scripts" / "claude_hooks.py"
    hook_command = subprocess.list2cmdline(["python", claude_hook_command_path(hook_path)])
    ask_permissions = [
        f"Bash({' '.join(pattern.split())}:*)"
        for pattern in claude_hooks.DANGEROUS_BASH_PATTERNS
    ]
    return {
        "permissions": {
            "deny": [f"Read({secret_path})"],
            "ask": ask_permissions,
        },
        "env": {
            "ILH_SECRET_PATH": secret_path,
            **debug_env(agent_runway_dir, debug),
        },
        "hooks": {
            "SessionStart": [
                {"hooks": [{"type": "command", "command": f"{hook_command} session-start"}]}
            ],
            "PreToolUse": [
                {"matcher": "*", "hooks": [{"type": "command", "command": f"{hook_command} pre-tool-use"}]}
            ],
            "PostToolUse": [
                {"matcher": "*", "hooks": [{"type": "command", "command": f"{hook_command} post-tool-use"}]}
            ],
            "SubagentStart": [
                {"hooks": [{"type": "command", "command": f"{hook_command} subagent-start"}]}
            ],
            "SubagentStop": [
                {"hooks": [{"type": "command", "command": f"{hook_command} subagent-stop"}]}
            ],
            "Stop": [
                {"hooks": [{"type": "command", "command": f"{hook_command} stop"}]}
            ],
        },
    }


def build_mcp_env_settings(agent_runway_dir: Path, secret_path: str, debug: bool = False) -> dict:
    return {
        "mode": "instructions_only",
        "env": {
            "ILH_SECRET_PATH": secret_path,
            **debug_env(agent_runway_dir, debug),
        },
        "note": "For Codex/OpenCode/VSCode/Cursor, configure the MCP server endpoint in your host's MCP settings. "
                "This output is not a host-native installer. "
                "The hook scripts only work with Claude Code hosted mode. "
                "MCP mode provides mission state and gates without host-level interception.",
    }


def build_opencode_settings(agent_runway_dir: Path, secret_path: str, debug: bool = False) -> dict:
    server_path = agent_runway_dir / "mcp" / "server.py"
    return {
        "$schema": "https://opencode.ai/config.json",
        "mode": "host_native_config",
        "mcp": {
            "agent-runway": {
                "type": "local",
                "command": ["python", str(server_path)],
                "environment": {
                    "ILH_SECRET_PATH": secret_path,
                    "ILH_OPENCODE_BRIDGE": "0",
                    **debug_env(agent_runway_dir, debug),
                },
                "enabled": True,
                "timeout": 5000,
            }
        },
        "permission": {
            "bash": {
                "*": "ask",
            },
            "read": {
                "*": "allow",
                secret_path: "deny",
            },
            "edit": {
                "*": "allow",
            },
            "task": {
                "*": "ask",
            },
            "doom_loop": "ask",
        },
        "note": "OpenCode supports native MCP server configuration. This snippet wires the MCP runtime and carries an optional bridge flag. Runtime state defaults to the active project's project-local .agent-runway/state.db unless ILH_DB_PATH is explicitly set by the host. OpenCode does not auto-discover plugins from skill directories, so bridge activation also requires a shim or symlink in .opencode/plugins/ or ~/.config/opencode/plugins/. Once discovered, the bundled bridge reads ILH_OPENCODE_BRIDGE from the host environment first, then falls back to OpenCode config content or config files such as opencode.json or .opencode/opencode.json. This config does not claim Claude-style stop blocking parity.",
    }


def build_pi_cli_settings() -> dict:
    return {
        "mode": "extension_only",
        "note": "Pi CLI support is extension-only: the tested path uses a Pi extension tool_call handler to block tool execution. This is not native MCP configuration and provides no Stop hook parity.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Emit host configuration snippet for Agent-Runway.")
    parser.add_argument("--host", choices=SUPPORTED_HOST_KEYS, default="claude-code",
                        help="Target host to configure (default: claude-code)")
    parser.add_argument(
        "--agent-runway-dir",
        default=".",
        help="Agent-Runway skill/MCP directory containing SKILL.md, scripts/, and mcp/",
    )
    parser.add_argument("--secret-path", default="~/.config/agent-runway/secret.key",
                        help="Secret path to deny from reads")
    parser.add_argument(
        "--debug",
        action="store_true",
        help=(
            "Enable detailed Agent-Runway debug logs; the runtime writes under "
            "the active project's .agent-runway/debug.log unless explicitly overridden"
        ),
    )
    args = parser.parse_args()
    agent_runway_dir = resolve_agent_runway_dir(args.agent_runway_dir)
    secret_path = str(Path(args.secret_path).expanduser())
    adapter = get_host_adapter(args.host)

    if adapter.config_mode == "hosted_installer":
        settings = build_claude_code_settings(agent_runway_dir, secret_path, args.debug)
    elif adapter.config_mode == "host_native_config":
        settings = build_opencode_settings(agent_runway_dir, secret_path, args.debug)
        settings["host"] = adapter.key
        settings["host_display_name"] = adapter.display_name
    elif adapter.config_mode == "extension_only":
        settings = build_pi_cli_settings()
        settings["host"] = adapter.key
        settings["host_display_name"] = adapter.display_name
    else:
        settings = build_mcp_env_settings(agent_runway_dir, secret_path, args.debug)
        settings["host"] = adapter.key
        settings["host_display_name"] = adapter.display_name

    print(json.dumps(settings, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
