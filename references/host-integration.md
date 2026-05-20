# Host Integration

## Claude Code

The bundled `scripts/claude_hooks.py` supports these events:

- `SessionStart`: ensure the runtime database and session row exist
- `PreToolUse`: escalate risky shell commands or secret-path reads to host confirmation
- `PostToolUse`: record receipts for tool activity
- `Stop`: block stopping unless a fresh MCP gate approval exists for the active mission

Generate a project configuration snippet with:

```bash
python scripts/generate_host_config.py --project-dir /absolute/path/to/project
```

Then merge the emitted JSON into `.claude/settings.json` or `.claude/settings.local.json`.

## OpenCode

OpenCode supports native MCP server configuration. Generate a project configuration snippet with:

```bash
python scripts/generate_host_config.py --host opencode --project-dir /absolute/path/to/project
```

Then merge the emitted JSON into your OpenCode config, such as `opencode.json` or `.opencode/opencode.json`.
This default snippet enables the MCP runtime only; the bridge still requires discovery from a real OpenCode plugin directory.

OpenCode does not auto-load plugins from the skill package directory. The real bridge implementation lives inside this repo at `.opencode/plugins/agent-runway.js`, but OpenCode only auto-discovers local plugins from project `.opencode/plugins/`, user `~/.config/opencode/plugins/`, or Windows `%USERPROFILE%\.config\opencode\plugins\`.

To enable automatic OpenCode receipt capture, create a shim or symlink in one of those real plugin directories, for example:

```js
export { default } from "../skills/agent-runway/.opencode/plugins/agent-runway.js"
```

If the skill is installed somewhere else, update the re-export path to the actual skill location. Prefer a shim or symlink rather than copying the raw plugin file, because the implementation depends on its relative path to `scripts/opencode_plugin_bridge.py`.

Current OpenCode support is intentionally narrower than Claude Code hosted-hook mode and should be described as host-assisted mode:

- **Native MCP server installation**: supported
- **Repo-local runtime state wiring** via `ILH_DB_PATH` / `ILH_SECRET_PATH`: supported
- **Optional plugin bridge**: available, but only after a shim or symlink is placed in an OpenCode plugin discovery directory
- **Bridge environment propagation**: supported; the bridge reads `mcp.agent-runway.environment`, passes `ILH_DB_PATH` / `ILH_SECRET_PATH` to `scripts/opencode_plugin_bridge.py`, and disables Python bytecode writes for bridge subprocesses
- **Claude-style stop blocking parity**: not claimed
- **Claude-style declarative hosted hook parity**: not claimed

## Pi CLI

Pi CLI support is extension-only and should be described as host-assisted mode, not hosted-hook mode. Generate the capability note with:

```bash
python scripts/generate_host_config.py --host pi-cli --project-dir /absolute/path/to/project
```

This output is not a native MCP installer. The tested path uses `@mariozechner/pi-coding-agent@0.73.1` with a Pi extension `tool_call` handler that blocks an actual `bash` tool call before it writes a sentinel file. This verifies tool-call blocking through Pi's extension system only; it does not claim native MCP support, Claude Code `Stop` parity, or a full hosted hook contract.

The experiment fixture lives at `scripts/fixtures/pi_block_extension.js` and is run through `scripts/host_blocking_experiments.py`.

## What the hooks improve

- **Physical stop blocking** inside Claude Code when gate approval is missing
- **Host-visible risk prompts** for sensitive shell commands
- **Real receipt capture** from tool executions instead of relying on model-written “evidence” prose

## What OpenCode native config improves

- **Installable MCP integration** instead of an instructions-only note block
- **Stable repo-local runtime wiring** for mission state, receipts, and gates
- **Honest portability**: OpenCode gets a real host-native config path without over-claiming Claude-style stop interception

## Reproducible host experiments

Run this optional check when Claude Code, OpenCode, Node, and npm are available:

```bash
python scripts/host_blocking_experiments.py
```

It checks:

- Claude Code generated hooks ask on risky `Bash` and block stale `Stop`
- Pi CLI extension `tool_call` blocks a sentinel-writing `bash` call
- OpenCode plugin bridge blocks secret-path reads when discovered and enabled with `ILH_OPENCODE_BRIDGE=1`
- OpenCode plugin bridge uses the configured Agent Runway database instead of falling back to the current project `.agent-runway/state.db`

This script is recommended evidence for cross-host capability claims. It is not part of the mandatory release gate because those host CLIs are environment-dependent.

## What the hooks do not solve

- they cannot make a non-hooked host behave the same way
- they cannot prove semantic correctness of a command, only that it ran and what it produced
- if the host allows the model to read the harness secret or tamper with the database, receipt trust degrades

## What remains host-specific

- Claude Code is still the strongest hosted path because it has documented hook-based stop blocking in this repo
- OpenCode now has a real native MCP config path, but this repo does not currently claim a documented stop-veto equivalent there
- Pi CLI can block tool calls through extensions, but this repo does not claim native MCP or stop-veto support there

## Recommended permissions

Use host permissions to deny or prompt for:

- reading secret storage paths used by the harness
- networked shell commands that can exfiltrate data
- destructive shell commands
- writes outside the project boundary unless explicitly intended
