# Handoff Packets

Use a handoff packet when work will continue in another turn, another runtime, or by another operator.

## Minimum contents

- goal and current status
- completion criteria
- current budgets and usage
- current budget status snapshot
- latest verified receipts
- open assumptions and known unknowns
- recorded decision records
- recorded counterexample checks
- criterion coverage if completion was attempted
- residual risks, unverified items, latest user authorization state, and the recommended next action

## Rule

A handoff packet should be sufficient for a competent new operator to continue without relying on hidden memory.

## Generation-4 addition

The handoff packet should expose budget pressure and coverage state explicitly enough that a new operator can tell whether to continue locally, refresh the mission, or escalate.


## v0.34 addition

If authority boundaries mattered, include the latest user authorization token, scope, freshness, and expiry so the next operator does not mistake stale approval for live authority.
