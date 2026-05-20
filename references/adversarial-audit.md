# Adversarial Audit Gate

Adversarial Audit Gate adds bounded falsification before high-risk completion claims. It is a governance gate, not a generic multi-agent arena.

## Purpose

Builder evidence often covers the path the Builder expected. For high-risk work, the project needs a separate adversarial profile that tries to falsify the completion claim with executable counterexamples, then lets a Judge/Gate classify the result from scope, budget, receipts, severity, reproducibility, and residual risk.

Adversarial audit increases confidence by failing to falsify a claim within scope and budget. It never proves absence of bugs.

## Activation

Run adversarial audit when work changes completion gates, turn gates, receipt freshness, mission epoch, authorization, secret paths, host hooks, OpenCode bridge behavior, release gates, claim parity, package validation, Project Learning Ledger schema/lint/query, high-severity bug fixes, or cross-host capability claims.

Do not run full adversarial audit for tiny docs edits, visual-only changes, or low-risk wording tweaks unless a release claim would otherwise exceed the evidence.

## Model

| Role | Responsibility | Boundary |
|---|---|---|
| Builder | Implements and produces ordinary mission receipts | Cannot self-certify adversarial audit pass |
| Adversary | Generates executable counterexample attempts | Cannot modify production source or block completion by vibe |
| Judge/Gate | Classifies findings by evidence and rubric | Cannot replace receipts with preference |

## Scope And Budget

Every `audit_plan` must include target claims, target files, required profiles, allowed attack types, excluded actions, a freshness baseline, and an audit budget. The minimum budget fields are `max_hypotheses`, `max_executable_attacks`, `max_runtime_seconds`, `max_retries_per_attack`, `max_output_bytes`, and `max_generated_artifacts`.

## Stop Legality

Adversarial audit may stop when budget is exhausted, required profiles are complete, no unresolved blocking findings remain, blocking findings were fixed and re-audited, residual risks are recorded, or a user accepts a scoped residual risk. It must not continue indefinitely seeking perfection.

## Evidence Rules

- Blocking findings require fresh, reproducible, in-scope execution evidence.
- Low/info findings cannot block.
- `needs_reproduction` and `false_positive` do not block completion.
- Project Learning Ledger can seed hypotheses, but cannot satisfy adversarial evidence.
- Audit records cannot be used as direct completion evidence for implementation criteria.
- Preference is not authorization.

## Sandbox Policy

The adversary defaults to no network, no destructive commands, no secret reads, and writes only under `tmp/adversarial-audit/<audit_id>/` unless a repro is explicitly promoted. The v0.36 MVP documents and lints this policy; it does not claim OS-level container isolation.

## Prompts

Adversary prompt template: use only the provided scope, budget, mission criteria, public artifacts, receipts, decision records, and Project Learning Ledger seed records. Generate executable counterexamples, record receipts or direct reproducible artifacts, classify severity/disposition, state residual risk, and never claim proof of safety.

Judge/Gate prompt template: reject no-receipt blockers, reject out-of-scope blockers, reject low/info blocking, check freshness, classify severity and disposition from the rubric, require re-audit after fixes, and report residual risk without proof-of-safety language.

## Builder Repair Loop

After a blocking finding, reproduce the failure, make the smallest fix, promote the repro to a regression test, rerun targeted tests, rerun the required adversarial profile, and record residual risk. If a verified fixed finding is broadly reusable, suggest a Project Learning Ledger record for human review; do not auto-create active memory.

## Non-Goals

- No full multi-agent scheduler.
- No automatic `spawn_adversary_agent`.
- No mandatory libFuzzer integration.
- No networked sandbox.
- No global adversarial memory.
- No automatic PR comment bot.
- No proof-of-safety or proof-of-correctness claims.

## Future Adapter Boundary

Future fuzzing adapters may record `fuzz_target`, `corpus_dir`, `max_seconds`, `crash_artifact`, and `minimized_input`. Hypothesis, libFuzzer, AFL, and scheduler support are future work, not v0.36 dependencies.
