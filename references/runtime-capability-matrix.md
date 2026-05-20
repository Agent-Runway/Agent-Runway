# Runtime Capability Matrix

Use this matrix when deciding how strongly the skill may describe its own guarantees.

## Modes

| Capability | soft mode | mcp mode | host-assisted mode | hosted-hook mode |
|---|---|---|---|---|
| mission planning guidance | advisory prose | advisory prose plus mission state | advisory prose plus mission state | advisory prose plus mission state |
| receipt storage | none | enforced by MCP runtime | enforced by MCP runtime, plus host-specific bridge/extension evidence in some hosts | enforced by MCP runtime and host receipts |
| receipt integrity verification | none | available via `verify_receipt_integrity` | available via `verify_receipt_integrity` | available via `verify_receipt_integrity` |
| stop gating | advisory only | gate tokens recorded, but stop remains advisory | gate tokens recorded, but stop remains advisory | gate tokens plus host-level stop blocking |
| risky-tool interception | none | none | partial, host-specific blocking or fail-closed behavior may exist for tool events | host hooks can ask or deny when configured |
| budget observability | prose only | `budget_status` tool | `budget_status` tool plus optional host-side evidence | `budget_status` tool plus host receipts |
| user authorization recording | none | `record_user_authorization` and `authorization_status` | runtime-backed authorization state plus optional host-assisted interception for some tools | runtime-backed authorization state plus host interception |
| handoff packet export | prose summary only | `export_handoff_packet` | `export_handoff_packet` | `export_handoff_packet` |
| prompt intake classification | advisory prose only | `prompt_intake_gate` can classify prompts, inspect active session/workspace mission state, return confidence/sources, and draft required first actions | MCP classification plus any host-specific bridge evidence, but pre-prompt injection only if that host exposes a user-message event | host user-message hooks may inject the intake directive before the model responds |
| project learning ledger | reviewable file-backed advisory context | reviewable file-backed advisory context, not MCP evidence or authorization | reviewable file-backed advisory context, not MCP evidence or authorization | reviewable file-backed advisory context unless a future release adds tools |
| release audit and packaging | scripts only | scripts only | scripts only | scripts only |

## Rule

Never describe a capability above the strongest mode that actually supports it.

## Common truthfulness examples

- In **soft mode**, say the stop gate is advisory and procedural, not enforced.
- In **mcp mode**, say receipts, mission state, budgets, handoffs, and gates are runtime-backed, but host blocking is still advisory.
- In **host-assisted mode**, say only the evidenced host-specific assists are real; do not promote them to full hook parity or stop blocking.
- In **hosted-hook mode**, say risky tools and unsafe stopping can be physically blocked only if the configured hooks are actually active.
- `prompt_intake_gate` is runtime-backed classification, not proof that a model will call it. Without a host user-message hook, short-prompt recovery remains a tool/skill discipline rather than a physical pre-response block.
- `mission_resume` can refresh an explicit host-session binding for an existing active mission, but it is not automatic unless the agent or host adapter calls it. It does not create pre-prompt injection or stop-blocking parity by itself.
- Host-level secret protection applies to tool calls that pass through configured hooks or the optional OpenCode bridge. It denies protected secret/state/credential path reads, while ordinary risky shell commands such as `ssh`, `scp`, `curl`, `wget`, and `git push` require confirmation or fail closed when confirmation is unavailable.


## v0.36 note

Authorization recording is runtime-backed in MCP mode, but actual stop blocking still requires hosted hooks. Host-assisted paths may add narrower interception without creating hook parity.

Project Learning Ledger is file-backed advisory context in v0.35. Memory is not evidence. Preference is not authorization. The ledger does not create MCP completion evidence, runtime authorization, a RAG layer, or a vector recall system.

Adversarial Audit Gate is conditional in v0.36. It can block completion only for fresh, reproducible, in-scope blocking findings; it never proves absence of bugs.

Prompt Intake Gate is available as an MCP tool. It supports multilingual continuation signals for English, Chinese, German, French, Spanish, Portuguese, Japanese, and Korean, including common polite wrappers, directive wrappers, short attached text, and Unicode normalization. The registry and signal layer are only sensors; state decides whether to continue, clarify, recover context, or record scoped authorization. Latin action-word detection must use word boundaries so substrings such as `contest`, `pushdown`, or `release notes` do not become fake mission or external-side-effect requests.

## Host-specific note

- Claude Code currently has the strongest repo-supported hosted-hook path: host hooks plus stop blocking when configured.
- Claude Code SubagentStart/SubagentStop hooks can register or close supervised child spans only when the event includes an explicit `agent_runway` contract and resolves to one active parent mission; events without that contract are visibility-only evidence, not delegated-work lifecycle proof.
- Codex is an MCP/advisory path in this repo: MCP tools can store mission state and verify receipts that already exist, but no repo-evidenced Codex hook automatically captures shell/read/edit receipts or blocks Stop. Empty `receipt_ids` in stuck attempts, decision records, or counterexample checks should be treated as a host capability gap or degraded direct evidence path, not as runtime-backed evidence.
- OpenCode fits host-assisted mode in this repo: native MCP config plus an optional plugin bridge, without Claude-style stop blocking parity.
- The optional OpenCode bridge shares the Claude hook pre-tool classifier for tool events and records post-tool receipts, including shell exit codes when OpenCode reports `exit`, `exitCode`, or `exit_code`; it is not active unless discovered and enabled with `ILH_OPENCODE_BRIDGE=1`.
- OpenCode does not currently have a repo-evidenced user-message/prompt-submit hook in `.opencode/plugins/agent-runway.js`; do not claim automatic pre-prompt `prompt_intake_gate` injection there.
- Pi CLI also fits host-assisted mode here: the reproducible experiment uses `@mariozechner/pi-coding-agent@0.73.1` and a Pi extension `tool_call` handler to block an actual `bash` tool call; this is not native MCP support and not Claude Code `Stop` parity.

## Host experiment evidence

Run this optional check when the local host CLIs are available:

```bash
python scripts/host_blocking_experiments.py
```

The script verifies configured Claude Code `PreToolUse` / `Stop` behavior, Pi CLI extension `tool_call` blocking, and OpenCode plugin bridge secret-read blocking. It is recommended validation evidence, not a mandatory release gate, because local host CLIs may be absent on packaging machines.
