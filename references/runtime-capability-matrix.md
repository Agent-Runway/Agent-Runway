# Runtime Capability Matrix

Use this matrix when deciding how strongly the skill may describe its own guarantees.

## Modes

| Capability | soft mode | mcp mode | host-assisted mode | hosted-hook mode |
|---|---|---|---|---|
| mission planning guidance | advisory prose | advisory prose plus mission state | advisory prose plus mission state | advisory prose plus mission state |
| receipt storage | none | enforced by MCP runtime | enforced by MCP runtime, plus host-specific bridge/extension evidence in some hosts | enforced by MCP runtime and host receipts |
| receipt integrity verification | none | available via `verify_receipt_integrity` | available via `verify_receipt_integrity` | available via `verify_receipt_integrity` |
| stop gating | advisory only | gate tokens recorded, but stop remains advisory | gate tokens recorded, but stop remains advisory | gate tokens plus host-level stop blocking |
| risky-tool interception | none | none | partial, host-specific blocking or fail-closed behavior may exist | host hooks can ask or deny |
| budget observability | prose only | `budget_status` tool | `budget_status` tool plus optional host-side evidence | `budget_status` tool plus host receipts |
| user authorization recording | none | `record_user_authorization` and `authorization_status` | runtime-backed authorization state plus optional host-assisted interception for some tools | runtime-backed authorization state plus host interception |
| handoff packet export | prose summary only | `export_handoff_packet` | `export_handoff_packet` | `export_handoff_packet` |
| project learning ledger | reviewable file-backed advisory context | reviewable file-backed advisory context, not MCP evidence or authorization | reviewable file-backed advisory context, not MCP evidence or authorization | reviewable file-backed advisory context unless a future release adds tools |
| release audit and packaging | scripts only | scripts only | scripts only | scripts only |

## Rule

Never describe a capability above the strongest mode that actually supports it.

## Common truthfulness examples

- In **soft mode**, say the stop gate is advisory and procedural, not enforced.
- In **mcp mode**, say receipts, mission state, budgets, handoffs, and gates are runtime-backed, but host blocking is still advisory.
- In **host-assisted mode**, say only the evidenced host-specific assists are real; do not promote them to full hook parity or stop blocking.
- In **hosted-hook mode**, say risky tools and unsafe stopping can be physically blocked only if the configured hooks are actually active.


## v0.36 note

Authorization recording is runtime-backed in MCP mode, but actual stop blocking still requires hosted hooks. Host-assisted paths may add narrower interception without creating hook parity.

Project Learning Ledger is file-backed advisory context in v0.35. Memory is not evidence. Preference is not authorization. The ledger does not create MCP completion evidence, runtime authorization, a RAG layer, or a vector recall system.

Adversarial Audit Gate is conditional in v0.36. It can block completion only for fresh, reproducible, in-scope blocking findings; it never proves absence of bugs.

## Host-specific note

- Claude Code currently has the strongest repo-supported hosted-hook path: host hooks plus stop blocking when configured.
- OpenCode fits host-assisted mode in this repo: native MCP config plus an optional plugin bridge, without Claude-style stop blocking parity.
- Pi CLI also fits host-assisted mode here: the reproducible experiment uses `@mariozechner/pi-coding-agent@0.73.1` and a Pi extension `tool_call` handler to block an actual `bash` tool call; this is not native MCP support and not Claude Code `Stop` parity.

## Host experiment evidence

Run this optional check when the local host CLIs are available:

```bash
python scripts/host_blocking_experiments.py
```

The script verifies configured Claude Code `PreToolUse` / `Stop` behavior, Pi CLI extension `tool_call` blocking, and OpenCode plugin bridge secret-read blocking. It is recommended validation evidence, not a mandatory release gate, because local host CLIs may be absent on packaging machines.
