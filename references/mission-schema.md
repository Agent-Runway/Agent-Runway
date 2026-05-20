# Mission Schema

Use this schema when a task has multiple completion criteria, non-obvious risk, or several reversible branches.

## Required fields

- goal
- completion_criteria
- scope_boundary
- red_lines
- slice_budget
- retry_budget
- verification_plan
- evidence_map

## Recommended fields

- assumptions
- defaults_chosen
- open_unknowns
- degradation_mode
- decision_records_required
- counterexample_required
- benchmark_targets
- time_budget_minutes
- risk_budget

## Minimal object

```yaml
goal: fix the failing parser behavior without changing the public api
completion_criteria:
  - parser regression test passes
  - targeted suite passes
  - public function signature is unchanged
scope_boundary:
  - do not redesign unrelated tokenization logic
red_lines:
  - no deploy
  - no remote push
slice_budget: 24
retry_budget: 3
verification_plan:
  - reproduce the failure
  - change the smallest plausible area
  - re-run the failing test
  - re-run the targeted suite
evidence_map:
  parser regression test passes:
    - current test receipt
  targeted suite passes:
    - current suite receipt
  public function signature is unchanged:
    - read-back or diff receipt
counterexample_required: true
time_budget_minutes: 45
risk_budget: local reversible edits only
```

## Rule

Every completion criterion must have a planned evidence type before execution starts. If a criterion lacks a plausible receipt, the mission is underspecified.
