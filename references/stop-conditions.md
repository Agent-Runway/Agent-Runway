# Stop Conditions

## Legal stop conditions

Only these conditions are legal:

- `slice_verified`
- `frontier_exhausted`
- `user_information_required`
- `approval_required`
- `interpretation_deadlock`
- `stuck_escalation`

## Decision table

### slice_verified
Use when the current slice objective was achieved and verified, and no immediate next action remains inside the frontier.

### frontier_exhausted
Use when the currently reachable action frontier was fully consumed and the next useful move depends on a fresh turn boundary rather than missing work.

### user_information_required
Use only when a specific answer from the user is the remaining blocker after local work was exhausted.

### approval_required
Use only when the next step crosses a real authority boundary such as deletion, push, deploy, or outbound communication.

### interpretation_deadlock
Use when multiple live interpretations remain and available local evidence cannot distinguish them.

### stuck_escalation
Use only after materially different retries were recorded and the retry budget is genuinely exhausted.

## Illegal reasons to stop

These are not legal stop conditions:

- convenience
- uncertainty that could be reduced locally
- lack of motivation
- desire to narrate future work instead of doing it
- wanting permission for reversible local actions
