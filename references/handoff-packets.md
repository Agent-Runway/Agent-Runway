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

## Schema

`export_handoff_packet` returns JSON with `schema_version: "1.0"`.

Top-level fields:

- `schema_version`
- `mission`
- `budget_status`
- `latest_receipts`
- `decision_records`
- `counterexample_checks`
- `latest_turn_gate`
- `latest_completion_gate`
- `latest_user_authorization`
- `adversarial_audit_status`
- `criterion_coverage`
- `known_risks`
- `unverified_items`
- `recommended_next_action`

Budget counters such as `slice_budget`, `slice_count`, and `retry_budget` live only under `budget_status`. The `mission` object carries identity, goal, status, criteria, boundaries, notes, and `mission_start_receipt_seq` so handoff readers do not need to reconcile duplicate budget semantics.


## v0.34 addition

If authority boundaries mattered, include the latest user authorization token, scope, authorization kind, freshness, and expiry. The next operator should not ask again for an authorized command, and should still ask for commands outside that scope.
