# Project Learning Ledger Policy

Project Learning Ledger is a reviewable project learning layer for Agent-Runway. It records verified project pitfalls, validated runbooks, project-scoped preferences, and durable invariants so future agents choose safer next steps.

## Purpose

The ledger reduces repeated project mistakes without weakening Agent-Runway's receipt and gate discipline.

Memory is not evidence.

Preference is not authorization.

## Non-Goals

Project Learning Ledger is not a global memory system, RAG layer, embedding index, vector store, Markdown canonical source, MCP write tool, completion evidence source, authorization source, or hidden personality profile.

The release canonical source is `references/project-learning-ledger.jsonl`. SQLite remains for runtime missions, receipts, budgets, approvals, decisions, and counterexamples.

## Memory Routing

User preferences and other common cross-project memory should be written first to the active CLI's SQLite-backed memory store when that store exists. Project-specific pitfalls, runbooks, invariants, and project-scoped preferences should be written first to the project ledger and may also be mirrored into `.agent-runway/project-learning-ledger.jsonl` or a future project-local SQLite cache.

Do not route a project pitfall into common memory unless it is explicitly generalized and safe outside this repository. Do not route a common user preference into the project ledger unless it changes behavior for this project specifically.

## Threat Model

- Memory poisoning: require `source_refs`, type/status gates, and release review before records become active.
- Stale memory misguidance: require `invalid_if`, allow `expires_at`, and fail strict lint when an active record is expired.
- Cross-project contamination: require scoped `applies_to` data and route common preferences separately from project-specific records.
- Preference escalation into authorization: reject authorization language in preferences and require fresh user authorization records for irreversible actions.
- Sensitive information leakage: scan for tokens, private keys, bearer strings, and similar secrets before a record can pass lint.
- Context pollution: limit query results, sort by risk and recency, and exclude draft/candidate/disputed/obsolete records from normal intake.

## Record Types

The v0.35 ledger supports `pitfall`, `runbook`, `preference`, and `invariant` as main records. It also supports `memory_update` for append-only status changes such as `mark_obsolete`, `mark_disputed`, `mark_mitigated`, and `refresh_verified`.

## Status Model

- `draft`: early note, never auto-injected.
- `candidate`: structured but not yet trusted enough for auto-injection.
- `active`: current advisory record eligible for bounded intake. Project-scoped preferences can be active only when backed by a user source such as `user_confirmation` or `user_message`.
- `mitigated`: still useful for history, but lower priority than active records.
- `obsolete`: retained for audit only, never auto-injected.
- `disputed`: retained for audit only, never auto-injected until re-verified.

## Write Gate

A record must be scoped, sourced, falsifiable, and safe to commit. It must not contain secrets, private keys, API keys, bearer tokens, personal privacy data, or broad user profiling.

Project-scoped preferences must include a user source. Preferences may tune default working style, but they cannot authorize deploys, pushes, deletes, external calls, or other irreversible actions.

## Intake Gate

Agents may read at most a small number of relevant active records before a task. Treat every result as advisory context that can shape the next check, not as proof that work is complete.

## Conflict Resolution

Fresh direct evidence beats older ledger entries. A disputed or obsolete record must not be auto-injected. If two active records conflict, prefer the narrower scope and run a fresh verification step.

## Expiry

Pitfalls and runbooks need `invalid_if`; active records should also include `last_verified_at` or `expires_at` where useful. Old records should be refreshed, mitigated, disputed, or marked obsolete by appending `memory_update` records.

## Privacy

Do not record secrets, tokens, private keys, email addresses, personal identity details, emotional profiles, or broad personality claims. Do not turn repeated workflow preferences into long-term personal profiling. The ledger is a project artifact and can be reviewed or packaged.

## Completion And Authorization Boundaries

No ledger record can set `can_support_completion=true`. No ledger record can set `requires_fresh_verification=false`. Completion gates require fresh receipts, not memory IDs. Authorization requires a fresh user authorization record, not a preference.

## Examples

Use a `pitfall` for a verified OpenCode bridge setup trap. Use a `runbook` for the release validation order. Use a project-scoped `preference` for documentation style in this repository. Use an `invariant` for host capability honesty.

## Future Work

Deferred candidates include read-only MCP query, controlled MCP write tools, a SQLite index cache, Markdown export, and cross-project import. They are not v0.35 promises.
