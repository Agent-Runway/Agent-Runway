# Adapter Contract

Use this file when porting the host harness expectations to a different environment.

## Minimum portable contract

A host adapter should ideally support:

- session or task identifiers
- post-tool receipt capture
- pre-risk prompts for destructive or external actions
- a stop event that can reject premature closure
- secret isolation from the model where possible

## Graceful fallback

If a host cannot supply all of these:

- preserve the naming of the missing guarantee
- state the missing guarantee explicitly
- fall back to softer but still auditable behavior
- avoid pretending parity with a stronger host
