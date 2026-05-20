# Architecture

This project is intentionally split into three layers.

## 1. Skill layer

The skill teaches behavioral defaults:

- own the goal
- reduce the action frontier
- verify before claiming
- ask only when the blocker is truly user-exclusive
- stop only at legal boundaries

This layer is cheap and portable, but soft.

## 2. MCP control plane

The MCP server is the structured policy layer. It manages:

- mission lock and scope boundary
- session/task-scoped durable state
- slice counts and retry budgets
- receipt-aware turn-end gating
- criterion-to-receipt completion checks
- stuck escalation after materially different failed strategies

This layer is stronger than prompt text because it is explicit, stateful, and inspectable, but it is still not enough by itself to physically block a host from letting the model stop.

## 3. Host harness layer

The host harness is where the strongest practical enforcement lives.

For Claude Code, hooks let the project:

- capture receipts from real tool executions
- ask for user confirmation on risky commands before they run
- block stop events when the model did not obtain a fresh gate approval

That closes the main enforcement gap in the original version.

## Design principles

- use the softest mechanism that is sufficient, but do not pretend it is stronger than it is
- move critical controls out of prompt text and into app-level code when the host supports it
- separate mission state from execution receipts
- make every approval and stop decision auditable
- prefer session/task namespaces over one global mutable slot
- prefer bounded escalation over infinite self-debate
