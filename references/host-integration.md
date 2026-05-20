# Host Integration

## Claude Code

The bundled `scripts/claude_hooks.py` supports these events:

- `SessionStart`: ensure the runtime database and session row exist
- `PreToolUse`: ask for risky shell commands and deny protected secret, state, or credential path reads
- `PostToolUse`: record receipts for tool activity
- `SubagentStart`: register a child span when the event includes an explicit `agent_runway` contract; otherwise record visibility only
- `SubagentStop`: close a child span when the event includes an explicit `agent_runway` contract; otherwise record visibility only
- `Stop`: block stopping unless a fresh MCP gate approval exists for the active mission

Generate a configuration snippet from the Agent-Runway skill/MCP directory with:

```bash
python scripts/generate_host_config.py --agent-runway-dir /absolute/path/to/agent-runway
```

Then merge the emitted JSON into `.claude/settings.json` or `.claude/settings.local.json`.

`SubagentStart` and `SubagentStop` lifecycle updates require an `agent_runway` object with `task_id` and the relevant child-span fields. If the host event `session_id` is not the parent MCP session, include `agent_runway.session_id`; otherwise the hook can use `cwd` only when it resolves to exactly one active parent mission with that `task_id`. Ambiguous cwd matches are rejected instead of guessing.

## OpenCode

OpenCode supports native MCP server configuration. Generate a configuration snippet from the Agent-Runway skill/MCP directory with:

```bash
python scripts/generate_host_config.py --host opencode --agent-runway-dir /absolute/path/to/agent-runway
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
- **Project-local runtime state wiring**: supported; mission state defaults to the active project `.agent-runway/state.db`, with `ILH_DB_PATH` reserved for explicit per-project overrides
- **Optional plugin bridge**: available, but only after a shim or symlink is placed in an OpenCode plugin discovery directory
- **Bridge environment propagation**: supported; the bridge reads `mcp.agent-runway.environment`, applies configured values such as `ILH_SECRET_PATH` and `ILH_OPENCODE_BRIDGE`, honors explicit `ILH_DB_PATH` overrides when present, and disables Python bytecode writes for bridge subprocesses
- **Pre-tool risk interception through the optional bridge**: supported for tool events; protected secret/state/credential path reads are denied and ordinary risky shell commands return `ask`, which the plugin treats as fail-closed when native host confirmation is unavailable
- **Prompt Intake Gate MCP tool**: supported through native MCP; agents or host adapters can call `prompt_intake_gate` to classify short prompts, recover session/workspace mission context, and return confidence, sources, first actions, and authority boundaries
- **Prompt/user-message pre-response injection**: not claimed for the bundled OpenCode plugin; `.opencode/plugins/agent-runway.js` currently handles `session.created` and `tool.execute.before/after`, not raw user message submission
- **Claude-style stop blocking parity**: not claimed
- **Claude-style declarative hosted hook parity**: not claimed

For OpenCode, short messages such as `continue`, `继续`, `weiter`, `continuez`, `continúa`, `continua`, `続けて`, or `계속` can be classified by MCP only if the model or a future host adapter calls the tool. Until OpenCode exposes and this repo wires a user-message event, this is not a guaranteed pre-prompt interception path.

## Pi CLI

Pi CLI support is extension-only and should be described as host-assisted mode, not hosted-hook mode. Generate the capability note with:

```bash
python scripts/generate_host_config.py --host pi-cli --agent-runway-dir /absolute/path/to/agent-runway
```

This output is not a native MCP installer. The tested path uses `@mariozechner/pi-coding-agent@0.73.1` with a Pi extension `tool_call` handler that blocks an actual `bash` tool call before it writes a sentinel file. This verifies tool-call blocking through Pi's extension system only; it does not claim native MCP support, Claude Code `Stop` parity, or a full hosted hook contract.

The experiment fixture lives at `scripts/fixtures/pi_block_extension.js` and is run through `scripts/host_blocking_experiments.py`.

## What the hooks improve

- **Physical stop blocking** inside Claude Code when gate approval is missing
- **Host-visible risk prompts** for risky shell commands and host-level denial for protected credential reads
- **Real receipt capture** from tool executions instead of relying on model-written “evidence” prose

## What OpenCode native config improves

- **Installable MCP integration** instead of an instructions-only note block
- **Stable project-local runtime wiring** for mission state, receipts, and gates
- **Honest portability**: OpenCode gets a real host-native config path without over-claiming Claude-style stop interception

## Reproducible host experiments

Run this optional check when Claude Code, OpenCode, Node, and npm are available:

```bash
python scripts/host_blocking_experiments.py
```

It checks:

- Claude Code generated hooks ask on risky `Bash` and block stale `Stop`
- Pi CLI extension `tool_call` blocks a sentinel-writing `bash` call
- OpenCode plugin bridge blocks protected secret/state/credential path reads when discovered and enabled with `ILH_OPENCODE_BRIDGE=1`
- OpenCode plugin bridge defaults to the event project's `.agent-runway/state.db` when no explicit `ILH_DB_PATH` override is configured

This script is recommended evidence for cross-host capability claims. It is not part of the mandatory release gate because those host CLIs are environment-dependent.

## What the hooks do not solve

- they cannot make a non-hooked host behave the same way
- they cannot prove semantic correctness of a command, only that it ran and what it produced
- if the host allows the model to read the harness secret or tamper with the database, receipt trust degrades
- they cannot inspect model-internal prompt injection before a tool call unless the host exposes and wires a user-message hook
- they cannot protect tools that bypass `PreToolUse` / `tool.execute.before` or hosts that run without the bridge/hooks enabled

## What remains host-specific

- Claude Code is still the strongest hosted path because it has documented hook-based stop blocking in this repo
- OpenCode now has a real native MCP config path, but this repo does not currently claim a documented stop-veto equivalent there
- Pi CLI can block tool calls through extensions, but this repo does not claim native MCP or stop-veto support there

## Recommended permissions

Use host permissions to deny or prompt for:

- reading secret storage paths used by the harness and common local credential files such as SSH private keys, `.env*`, cloud credentials, kubeconfig, and private key bundles
- networked shell commands that can exfiltrate data
- destructive shell commands
- writes outside the project boundary unless explicitly intended
