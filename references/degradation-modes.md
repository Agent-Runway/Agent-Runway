# Degradation Modes

When runtime conditions are weaker than the ideal architecture, do not relax truthfulness. Relax only the strength of your claims.

## Modes

### mode 0: hosted
- hooks active
- receipt capture can be host-backed
- stop blocking can be physical

### mode 1: mcp without hooks
- mission state is structured
- stop legality is checked
- stop blocking is still advisory

### mode 2: soft disciplined
- only prompt instructions and ordinary tools are available
- receipts may still exist from tools, but not from enforced gates

### mode 3: constrained
- tools are missing, failing, or partial
- only narrow claims are allowed
- completion may be impossible without escalation

## Required behavior by degraded mode

- label the active mode explicitly when it matters to the claim
- downgrade words like ensured, enforced, blocked, or verified if host or tools do not support them
- increase the burden of caveat clarity as the mode weakens
- never convert missing evidence into stronger narrative certainty

## Rule of thumb

Weak runtime does not justify weak discipline. It just changes what can honestly be asserted.
