# Subagent Capability Matrix

This matrix keeps v0.37 runtime claims scoped to the host path that can actually observe child work. The rule is simple: no physical stop blocking claim without host lifecycle stop hook.

## Levels

| Level | Name | Guarantee |
|---|---|---|
| L0 | L0 prompt-only supervision | The parent prompt carries the contract, but Agent Runway only sees the child's final text. |
| L1 | L1 proof-bundle import | The child returns logs, artifacts, or structured handoff data that the parent can inspect and re-verify. |
| L2 | L2 shared MCP child receipts | The child can write Agent Runway receipts into the parent runtime with `metadata.child_span_id`. |
| L3 | L3 hosted lifecycle/tool-hook supervision | The host exposes child start, tool use, and stop events to Agent Runway hooks or plugins. |

## Host Matrix

| Host | Level | launch mechanism | context inheritance | tool/MCP inheritance | hook/event visibility | budget visibility | stop enforceability | Agent Runway support |
|---|---|---|---|---|---|---|---|---|
| Claude Code | L3 | Native subagents plus SubagentStart/SubagentStop hooks | Explicit child context contract; inheritance is not assumed | Can be configured through subagent tools and MCP settings | Best path for child lifecycle, child tool receipts, and child stop events | Delegated budget plus hook-observed tool use when configured | Host-assisted for child stops only when SubagentStop hook is active | Reference implementation target |
| OpenCode | L2 | Native agents and plugin events | Explicit prompt/agent contract; inheritance is not assumed | Shared MCP may be available when configured | Plugin/session events can attribute receipts, but stop parity with Claude Code is not claimed | Delegated budget and MCP/plugin receipts when present | Advisory unless a concrete OpenCode stop event bridge is installed and verified | Shared MCP/plugin path |
| Codex | L1 | CLI/cloud tasks or experimental spawn paths | Fresh or cloud context; inheritance is not assumed | MCP availability depends on host configuration | No stable child lifecycle stop hook is assumed | Proof-bundle or parent-observed receipts only | Advisory; parent must re-verify before completion | Proof-bundle import path |
| Pi | L1 | Extension/package subagent paths | Extension-defined; inheritance is not assumed | MCP tool entries must be explicit | Extension events may exist, but core parity is not claimed | Proof-bundle or extension metadata when available | Advisory unless a verified extension supplies lifecycle stop events | Proof-bundle/import path |
| Unknown/future host | L0 | Host-specific | subagent inheritance is not assumed | Unknown until configured | Unknown | Parent-visible only | None | Prompt-only contract |

## Claim Hygiene

- Claude Code | L3 is the only default row that may describe hosted lifecycle/tool-hook supervision.
- OpenCode | L2 can describe shared MCP child receipts and plugin attribution, not Claude Code stop parity.
- Codex | L1 and Pi | L1 can describe proof-bundle import unless a separate verified adapter raises the level.
- Any host can downgrade to L0 when MCP, plugins, hooks, or extension events are unavailable.
- A stronger row does not make child output evidence. Child summaries still require receipts, handoffs, and parent gate checks.
