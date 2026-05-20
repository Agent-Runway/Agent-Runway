# Subagent Supervision

Agent Runway does not launch every subagent. v0.37 defines how already-launched child agents become accountable to a parent mission through child spans, delegated scope, delegated budgets, child receipts, handoff records, and parent gate checks.

## Hard Rules

- child summary is not evidence. It may guide parent work, but it cannot satisfy a completion criterion unless backed by valid child receipt IDs or fresh parent verification receipts.
- subagent inheritance is not assumed. Model context, tool permissions, workspace, MCP access, and hook visibility can diverge independently.
- parent authorization does not automatically flow to child. Any irreversible or externally visible child action needs explicit delegated scope and fresh authorization.
- memory is not evidence. Project learning and child notes can route attention, but they do not prove work happened.
- preference is not authorization. A remembered preference cannot approve a child action outside the current delegated scope.
- A child receipt must identify its `child_span_id` before it can support delegated parent evidence.
- A child handoff is not a receipt. Parent completion maps must cite the underlying receipt IDs.

## Supervision Levels

| Level | Name | What It Means | Completion Implication |
|---|---|---|---|
| L0 | L0 prompt-only supervision | The parent prompt asks the child to follow Agent Runway rules, but no runtime receipt path is visible. | Advisory only; parent must re-verify. |
| L1 | L1 proof-bundle import | The child returns logs or artifacts that can be imported as a proof bundle. | Not completion-ready until parent verifies and records fresh receipts. |
| L2 | L2 shared MCP child receipts | The child can write receipts into the same Agent Runway runtime with a `child_span_id`. | Usable only after handoff, terminal child status, freshness, and scope checks. |
| L3 | L3 hosted lifecycle/tool-hook supervision | The host exposes child start, tool use, and stop events to hooks or plugins. | Strongest path; still must pass receipt and gate validation. |

## Runtime Model

Every delegated task is a child span under the parent mission, not an independent completion claim. The span records parent task, host, host child ID, subagent type, `context_mode`, `workspace_kind`, status, delegated scope, delegated budget, and budget consumed.

The v0.37 runtime uses these enum values from the development book:

- `context_mode`: `fresh`, `fork`, `resumed`, `team`, `unknown`
- `workspace_kind`: `shared_checkout`, `worktree`, `local_sandbox`, `cloud_sandbox`, `unknown`

`unknown` is allowed only to preserve runtime honesty when the host adapter cannot determine the field. It should downgrade claims, not loosen evidence rules.

## Glossary

- child span: the runtime record for one delegated child execution under a parent mission; it can support completion only when linked receipts and handoff checks pass.
- child summary: prose from the child about what happened; advisory only and never completion evidence by itself.
- child receipt: a signed Agent Runway receipt that includes `metadata.child_span_id`; it can support completion only when scoped, fresh, handoff-covered, and attached to a completed child span.
- proof bundle: child logs, artifacts, transcripts, or structured output returned outside shared runtime receipt capture; advisory until parent verification records fresh receipts.
- child handoff: a structured record mapping child claims to receipt IDs, risks, blockers, and unverified items; it is not a receipt.
- imported child evidence: proof-bundle material the parent has imported for review; advisory until parent verification creates fresh receipt-backed evidence.
- delegated budget: the bounded slice, tool-call, elapsed-time, and retry allowance assigned to a child span; it reports hidden child work separately from direct parent slices.
- orphan child: a child span left running, abandoned, or unresolved beyond the parent turn or expected lifecycle; it is a risk signal, not completion evidence.

## Non-Goals

Agent Runway v0.37 is not an orchestration platform. It does not provide a universal launcher, does not capture hidden reasoning, does not promise physical stop enforcement on every host, does not provide precise provider billing, and does not make child work automatically complete the parent mission.

## Parent Gate Rules

Completion gates treat child evidence as delegated evidence, not as a shortcut. A parent completion must reject summary-only child claims, handoff IDs used as receipt IDs, child receipts without matching `child_span_id`, child receipts without handoff coverage, and child receipts from spans that are not completed.
