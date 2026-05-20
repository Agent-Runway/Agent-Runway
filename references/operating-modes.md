# Operating Modes

## Summary

This skill supports four runtime modes. Choose the strongest one the environment actually provides and be honest about what remains soft.

| Mode | Active controls | What is strong | What remains soft |
|---|---|---|---|
| soft | skill files only | phrasing discipline | everything can still be ignored by the host/runtime |
| mcp | mission state, receipts, gates | auditable state, explicit criteria, budget tracking | stopping is still advisory if the host does not enforce it |
| host-assisted | MCP plus host-specific bridge/extension paths | some hosts can add partial tool interception or extra receipt capture | stopping is still advisory and interception remains host-specific |
| hosted-hook | MCP plus host hooks | receipt capture, risky-tool prompts, stop blocking | semantic correctness still depends on good criteria and verification |

## Selection rule

Use the strongest mode available, but do not pretend a weaker mode is stronger.

- In **soft mode**, report that gates are conceptual and behavioral.
- In **mcp mode**, report that state and approvals are real, but stop blocking is still advisory.
- In **host-assisted mode**, report only the extra host behavior that is actually evidenced, and keep stop blocking advisory unless a real hook contract exists.
- In **hosted-hook mode**, report that the host can physically block risky tool use or stopping when configured.

## Reporting rule

When describing progress or guarantees, separate these layers:

1. what the instructions require
2. what the MCP can verify
3. what the host can physically block

## Common failure

The most damaging honesty failure is saying "the system will block this" when only MCP or a weaker host-assisted path is active.
