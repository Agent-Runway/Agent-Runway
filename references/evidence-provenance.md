# Evidence Provenance

Use this file when claims are derived from mixed sources, summaries, or multi-step reasoning.

## Provenance labels

- **direct**: observed in the current turn from a primary source or command output
- **derived**: inferred from direct evidence with a stated reasoning step
- **historical**: observed earlier but not freshly re-verified
- **unverified**: plausible but not yet tied to current evidence

## Freshness rule

Prefer current-turn direct evidence for any load-bearing claim about status, behavior, or completion.

## Anti-laundering rules

Do not let a derived claim masquerade as direct evidence.
Do not let a summary masquerade as the underlying receipt.
Do not let an old receipt masquerade as a fresh verification.

## Reporting pattern

For important claims, state:

- claim
- provenance label
- evidence or receipt
- whether the claim is direct or inferred
