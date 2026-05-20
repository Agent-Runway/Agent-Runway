# Counterexample Discipline

Use this reference when a result could be accepted too easily.

## Rule

Before declaring a high-stakes or easy-to-overclaim result acceptable, run at least one disconfirming check.

## Good disconfirming checks

- a negative test intended to break the current explanation
- a semantic check that asks whether the receipt proves the user-valued outcome, not only a technical proxy
- a mutant or degraded variant that should fail the audit
- a second-path verification that would catch a locally convenient but globally misleading success

## Record format

State:

- hypothesis being challenged
- attempted disconfirmers
- outcome
- surviving risk
- receipt ids used

A counterexample check can succeed by disproving the current path, because that still prevents a false acceptance.
