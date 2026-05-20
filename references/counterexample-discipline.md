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

The hypothesis, each attempted disconfirmer, and the outcome must be specific enough to
say what was challenged, what was tried, and what was observed. Short generic outcomes
such as `ok`, `done`, `checked`, `完成`, `erledigt`, `terminé`, `hecho`, `feito`,
`完了`, `완료`, or similarly short multilingual equivalents are not acceptable runtime
records. This is a specificity heuristic, not a proof that every vague phrasing can
be detected.

A counterexample check can succeed by disproving the current path, because that still prevents a false acceptance.
