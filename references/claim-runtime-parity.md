# Claim-Runtime Parity

A skill is only as honest as the weakest link between its prose and its runtime.

## Rule

Do not present a behavior as enforced unless at least one of these is true:

1. an MCP tool operationalizes it
2. a script checks it
3. a host hook blocks or prompts on it
4. the skill explicitly labels it as advisory prose only

## Generation-4 practice

Use both of these artifacts together:

- [runtime-capability-matrix.md](runtime-capability-matrix.md) for human-readable guarantee strength by mode
- [runtime-claim-manifest.json](runtime-claim-manifest.json) for machine-checkable mapping from claims to files, tools, scripts, or hooks

For installed-skill use, inspect `runtime-capability-matrix.md` and `runtime-claim-manifest.json` before making guarantee claims. Maintainer parity checks live under `archive/release-tests/` and are not part of the installed skill payload.

## Parity checks

For each major claim, ask:

- where is the runtime surface for this claim
- what script or tool would fail if the claim were false
- what weaker runtime is still allowed to say honestly
- whether the claim is labeled advisory, runtime-backed, or host-backed

## Typical mismatches to reject

- claiming budget discipline with no observable budget status
- claiming budget enforcement while the gate never reacts to exhausted budgets
- claiming handoff continuity with no exported criterion coverage or budget snapshot
- claiming release rigor when parity, consistency, or ledger checks are omitted from the release gate
- claiming risky-tool interception in a mode where hooks are absent
- claiming live user approval with no runtime-backed authorization state or stale authorization status
