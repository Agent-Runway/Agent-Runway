# Anti-Patterns Reference

## Narration instead of execution

- "I can continue if you want."
- "The next step would be X." when X is still inside the action frontier
- "My plan is to..." without doing the work in the same turn

## Fake blockage

- "I need more context." before reading the available files
- "I cannot determine this." before testing or inspecting
- "I am not sure how to proceed." when a conservative next action exists

## Premature closure

- "Done." without fresh verification
- "Fixed." without re-testing the original symptom
- "Should work now." based on visual inspection alone

## Permission theater

- "Should I proceed?" when the action is reversible and local
- "Waiting for your confirmation." when no true authority boundary exists
- asking multiple preference questions before exhausting local evidence

## Scope creep disguised as diligence

- silently solving adjacent issues without saying they are out of scope
- turning a local fix into a redesign without justification
- adding broad cleanup while the asked-for target is unfinished

## Control-plane anti-patterns

- submitting free-text evidence instead of receipts
- ending a turn without calling `turn_end_gate`
- using `stuck_escalation` before materially different retries are exhausted
- claiming host enforcement exists when the hooks are not installed
- mapping completion criteria to receipts that do not actually prove the criterion
