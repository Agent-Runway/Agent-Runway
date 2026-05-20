from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class HostAdapter:
    key: str
    display_name: str
    hosted_hooks_supported: bool
    native_mcp_config_supported: bool
    stop_blocking_supported: bool
    config_mode: str
    execution_tools: frozenset[str]
    observation_tools: frozenset[str]
    mutation_tools: frozenset[str]


HOST_ADAPTERS: dict[str, HostAdapter] = {
    "claude-code": HostAdapter(
        key="claude-code",
        display_name="Claude Code",
        hosted_hooks_supported=True,
        native_mcp_config_supported=True,
        stop_blocking_supported=True,
        config_mode="hosted_installer",
        execution_tools=frozenset({"Bash", "PowerShell", "Shell"}),
        observation_tools=frozenset({"Read", "Glob", "Grep"}),
        mutation_tools=frozenset({"Edit", "Write", "MultiEdit"}),
    ),
    "codex": HostAdapter(
        key="codex",
        display_name="Codex",
        hosted_hooks_supported=False,
        native_mcp_config_supported=False,
        stop_blocking_supported=False,
        config_mode="instructions_only",
        execution_tools=frozenset({"Codex"}),
        observation_tools=frozenset({"Read", "Glob", "Grep"}),
        mutation_tools=frozenset({"Edit", "Write", "MultiEdit"}),
    ),
    "opencode": HostAdapter(
        key="opencode",
        display_name="OpenCode",
        hosted_hooks_supported=False,
        native_mcp_config_supported=True,
        stop_blocking_supported=False,
        config_mode="host_native_config",
        execution_tools=frozenset({"OpenCode"}),
        observation_tools=frozenset({"Read", "Glob", "Grep"}),
        mutation_tools=frozenset({"Edit", "Write", "MultiEdit"}),
    ),
    "pi-cli": HostAdapter(
        key="pi-cli",
        display_name="Pi CLI",
        hosted_hooks_supported=True,
        native_mcp_config_supported=False,
        stop_blocking_supported=False,
        config_mode="extension_only",
        execution_tools=frozenset({"bash"}),
        observation_tools=frozenset({"read", "grep", "find", "ls"}),
        mutation_tools=frozenset({"edit", "write"}),
    ),
    "vscode": HostAdapter(
        key="vscode",
        display_name="VSCode",
        hosted_hooks_supported=False,
        native_mcp_config_supported=False,
        stop_blocking_supported=False,
        config_mode="instructions_only",
        execution_tools=frozenset(),
        observation_tools=frozenset({"Read", "Glob", "Grep"}),
        mutation_tools=frozenset({"Edit", "Write", "MultiEdit"}),
    ),
    "cursor": HostAdapter(
        key="cursor",
        display_name="Cursor",
        hosted_hooks_supported=False,
        native_mcp_config_supported=False,
        stop_blocking_supported=False,
        config_mode="instructions_only",
        execution_tools=frozenset(),
        observation_tools=frozenset({"Read", "Glob", "Grep"}),
        mutation_tools=frozenset({"Edit", "Write", "MultiEdit"}),
    ),
    "unknown": HostAdapter(
        key="unknown",
        display_name="Unknown Host",
        hosted_hooks_supported=False,
        native_mcp_config_supported=False,
        stop_blocking_supported=False,
        config_mode="instructions_only",
        execution_tools=frozenset(),
        observation_tools=frozenset({"Read", "Glob", "Grep"}),
        mutation_tools=frozenset({"Edit", "Write", "MultiEdit"}),
    ),
}

SUPPORTED_HOST_KEYS: tuple[str, ...] = tuple(
    key for key in HOST_ADAPTERS.keys() if key != "unknown"
)

EXECUTION_TOOLS: frozenset[str] = frozenset(
    tool for adapter in HOST_ADAPTERS.values() for tool in adapter.execution_tools
)
OBSERVATION_TOOLS: frozenset[str] = frozenset(
    tool for adapter in HOST_ADAPTERS.values() for tool in adapter.observation_tools
)
MUTATION_TOOLS: frozenset[str] = frozenset(
    tool for adapter in HOST_ADAPTERS.values() for tool in adapter.mutation_tools
)
SHELL_LIKE_TOOLS: frozenset[str] = EXECUTION_TOOLS
KNOWN_NON_EXECUTION_TOOLS: frozenset[str] = MUTATION_TOOLS | OBSERVATION_TOOLS


def resolve_event_host(event: dict[str, Any]) -> str:
    return str(
        event.get("host")
        or event.get("client_name")
        or event.get("runtime_name")
        or "unknown"
    )


def classify_host_key(host_name: str) -> str:
    lowered = host_name.strip().lower()
    if not lowered or lowered == "unknown":
        return "unknown"

    first_word = lowered.split()[0]

    if first_word == "claude-code":
        return "claude-code"
    if lowered == "claude code" or lowered.startswith("claude code "):
        return "claude-code"
    if first_word in {"codex", "codex-cli"}:
        return "codex"
    if first_word == "opencode":
        return "opencode"
    if lowered in {"pi", "pi cli", "pi-cli"} or first_word == "pi-coding-agent":
        return "pi-cli"
    if first_word in {"vscode", "vscode-mcp"} or lowered.startswith("vs code"):
        return "vscode"
    if first_word == "cursor":
        return "cursor"
    return "unknown"


def get_host_adapter(host_key: str) -> HostAdapter:
    return HOST_ADAPTERS.get(host_key, HOST_ADAPTERS["unknown"])
