# Threat Model

## Primary failure modes addressed

1. **Prompt non-compliance**
   - Mitigation: host stop hooks and permission prompts

2. **Evidence hallucination**
   - Mitigation: receipt-oriented verification bound to actual tool executions

3. **Shared mutable state collisions**
   - Mitigation: session/task-scoped SQLite state with atomic transactions

4. **Persistence degrading into loops**
   - Mitigation: retry budgets plus explicit stuck escalation

## Residual risks

- if the host has no hooks, enforcement remains partly soft
- if a model can read or modify harness secrets, receipt trust weakens
- a successful command receipt does not automatically prove the user’s high-level goal is satisfied
- semantic correctness still depends on good criteria and good verification design

## Dialectical takeaway

This system is deliberately stronger than prompt-only discipline, but not magic. It improves control by moving from self-report to observable runtime evidence and host participation. It still requires honest scoping, good criteria, and secure host configuration.
