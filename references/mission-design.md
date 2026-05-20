# Mission Design

## Goal

Write missions that can be falsified rather than admired.

## Completion criteria rules

Good completion criteria are:

- concrete
- observable
- narrow enough to test
- tied to user value rather than vague activity

Bad criteria:

- "made good progress"
- "looks correct"
- "handled the issue"

Better criteria:

- "the failing test now passes"
- "the report includes the requested three sections"
- "the generated file opens and preserves the required fields"

## Scope boundary rules

A scope boundary should state what the model will not quietly expand into.

Examples:

- do not redesign architecture unless the original request requires it
- do not fix adjacent lint issues unless they block the requested change
- do not contact external systems without explicit authorization

## Red lines

Red lines mark real authority boundaries, not generic caution.

Examples:

- no destructive deletion without explicit approval
- no push, deploy, or outbound message without explicit approval
- no secret or access-control changes without explicit approval

## Budget sizing

Use small budgets by default.

- simple local task: slice budget 3 to 6, retry budget 2 to 3
- medium debugging task: slice budget 6 to 12, retry budget 3 to 4
- broad analysis task: slice budget 8 to 16, retry budget 3 to 5

If the task is huge, split it into smaller missions instead of creating an enormous budget.
