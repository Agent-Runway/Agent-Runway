# Budget Discipline

Budgets keep persistence real instead of theatrical.

## Budget families

- **slice budget**: how many bounded slices are allowed before reassessing mission shape
- **retry budget**: how many materially different strategies are justified before escalation
- **time budget**: how much local time or latency burn is justified before a handoff or escalation
- **risk budget**: what degree of local experimentation is acceptable before explicit approval is needed

## Rule

Tighter budgets should change behavior, not just prose. If the budget is near exhaustion, either narrow the slice, escalate honestly, or export a handoff packet.

## Value Gate

Budget discipline answers "how much continuation is justified."
Value Gate answers "whether continuation is still the right move at all."

`Agent-Runway` does not treat persistence as an end in itself. Continue only when the next slice is still the highest-value move available inside the active mission.

Continuing is reasonable when at least one of these is true:

- it fixes a release blocker, data-integrity problem, security boundary issue, evidence contamination, or authorization error
- it materially lowers the risk of false completion, false-positive validation, cross-session contamination, or stale receipt reuse
- it closes a concrete gap between what the system claims and what current receipts or tests actually prove
- it improves the critical path for first-time install, run, verification, or debugging
- it closes a high-impact issue through a bounded change with a clear verification path

Convergence is preferable when the remaining work is mostly:

- wording preference, style tuning, or repeated explanation
- runtime, API, or host-surface expansion without a matching high-risk defect
- polish that improves appearance or score without improving safety, installability, or verifiability
- more local churn after release gates, package validation, benchmark, mutation, and targeted checks already pass, with no new reproducible defect
- a next step whose value, verification path, or stop condition cannot be stated clearly

## Compact evaluation

Before continuing, check these seven dimensions:

- **impact**: does it affect correctness, safety, release quality, installation, or user trust?
- **evidence gap**: is any current claim stronger than the evidence behind it?
- **blocker status**: does skipping this leave a real release, usage, or verification blocker?
- **change size**: can it be closed with a bounded change?
- **expansion risk**: does it enlarge runtime, API, or host surface?
- **verification path**: can success be checked clearly?
- **stop condition**: will it be obvious when to stop after doing it?

## Practical threshold

Continue only when all of these hold:

- impact is high
- and either an evidence gap or a real blocker exists
- and verification is clear
- and scope expansion is low
- and the stop condition is explicit

Otherwise, converge.
