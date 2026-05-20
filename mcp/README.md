# Agent-Runway MCP

This project turns prompt-only diligence into a small control plane with optional host enforcement.

## Components

| Tool | Purpose |
|---|---|
| `mission_lock` | create or refresh a mission namespace with criteria, budgets, and verification planning |
| `mission_status` | inspect mission state, budgets, and gate freshness |
| `budget_status` | observe remaining slices, retries, time budget, and gate/approval freshness |
| `list_recent_receipts` | inspect recent harness-captured receipts |
| `verify_receipt_integrity` | verify receipt signatures against stored state |
| `record_stuck_attempt` | record a materially different failed strategy |
| `record_decision_record` | record a consequential reversible choice with evidence |
| `record_counterexample_check` | record a disconfirming check with surviving risk |
| `record_user_authorization` | record explicit user approval for irreversible or externally visible actions |
| `authorization_status` | inspect latest user authorization freshness and scope |
| `turn_end_gate` | approve or reject ending a turn using fresh receipts |
| `completion_gate` | approve or reject completion using criterion-to-receipt mappings with semantic and freshness checks |
| `export_handoff_packet` | export a continuity packet with mission state, receipts, budget, decisions, and residual risk |

## Runtime files

Default database path:

```bash
.agent-runway/state.db
```

Default secret path:

```bash
~/.config/agent-runway/secret.key
```

Override with:

```bash
ILH_DB_PATH=/tmp/ilh.db ILH_SECRET_PATH=/tmp/secret.key python mcp/server.py
```

## Quick workflow

1. call `mission_lock`
2. perform a bounded slice of work
3. verify using real tools or direct reads
4. inspect receipts if needed
5. call `turn_end_gate` before ending the turn
6. if blocked repeatedly, call `record_stuck_attempt`
7. call `completion_gate` before declaring done

## Why receipts matter

Receipts replace unverifiable prose with runtime evidence. Bash receipts can include command text and exit code. Write/Edit receipts can include file path and resulting file hash. Read-like receipts show what source was inspected.

## Claude Code integration

Generate a settings snippet with:

```bash
python scripts/generate_host_config.py --project-dir /absolute/path/to/agent-runway
```

The bundled hooks can:

- ensure session state exists at session start
- ask for confirmation on risky shell commands
- deny secret-path reads
- record receipts for tool activity
- block stopping when no fresh gate approval exists

## OpenCode integration

Generate an OpenCode config snippet with:

```bash
python scripts/generate_host_config.py --host opencode --project-dir /absolute/path/to/agent-runway
```

This release now provides:

- a host-native OpenCode MCP configuration snippet
- repo-local runtime wiring via `ILH_DB_PATH` and `ILH_SECRET_PATH`
- optional bridge environment propagation from OpenCode config into the Python bridge process, with Python bytecode writes disabled for bridge calls

For automatic OpenCode receipt capture, the bridge still needs discovery from a real OpenCode plugin directory such as project `.opencode/plugins/`, user `~/.config/opencode/plugins/`, or Windows `%USERPROFILE%\.config\opencode\plugins\`. The skill-internal plugin file is not auto-loaded by OpenCode on its own.

This release does not claim:

- Claude Code `Stop` parity
- Claude Code hosted hook parity inside OpenCode

## Pi CLI integration

Generate the Pi CLI capability note with:

```bash
python scripts/generate_host_config.py --host pi-cli --project-dir /absolute/path/to/agent-runway
```

This is extension-only. The v0.36 experiment verifies Pi extension `tool_call` blocking for an actual `bash` call, but it does not emit native MCP configuration and does not claim Claude Code `Stop` parity.

## Recommended validation

Run these checks before shipping changes:

```bash
python -m unittest discover -s mcp/tests -p 'test_*.py'
python scripts/smoke_test.py
python scripts/host_blocking_experiments.py
```

`host_blocking_experiments.py` is optional when host CLIs are unavailable. When available, it gives reproducible evidence for Claude Code configured hooks, Pi CLI extension tool-call blocking, and OpenCode plugin bridge blocking.

## Honest limits

- without host hooks, stop enforcement remains advisory
- a successful receipt proves a tool ran, not that the high-level task is semantically complete
- if the host allows secret or database tampering, receipt trust degrades
- Pi CLI support is extension-only, not native MCP or Stop hook parity
