# Scoring Rubric

Use this rubric to audit whether the skill is improving in ways that materially change execution quality under real pressure, not only under friendly phrasing checks.

## Twenty-four scoring dimensions

1. invocation specificity
2. trigger-boundary precision
3. runtime honesty
4. mission schema rigor
5. slice discipline clarity
6. evidence traceability
7. stop-condition precision
8. stuck-escalation discipline
9. authority-boundary safety
10. output-contract usability
11. progressive-loading structure
12. operability and quickstart quality
13. degradation resilience
14. adversarial robustness
15. composition interoperability
16. benchmarkability and release governance
17. claim-runtime parity
18. counterexample discipline
19. handoff packet quality
20. evaluation hardness
21. cross-file consistency
22. budget observability and enforcement
23. ledger integrity
24. release-report quality

## External review scorecard used in this generation

When reviewing a proposed upgrade, score these twelve load-bearing items first before trusting any finer-grained self-audit:

1. trigger precision
2. runtime honesty
3. mission design rigor
4. evidence traceability
5. stop legality
6. authority-boundary discipline
7. budget observability
8. handoff continuity
9. claim-runtime parity
10. benchmark hardness
11. mutation resistance
12. release-gate completeness

## Scale

- **10.0**: explicit, operational, mutation-resistant, benchmarked against negative cases, and cross-file consistent
- **9.5**: strong and deployable, with only minor non-load-bearing ambiguity
- **8.0 to 9.4**: useful but still has noticeable ambiguity, shallow checking, or weak runtime binding
- **below 8.0**: likely to misfire, self-score too easily, or drift under real pressure

## Audit rule

Treat 9.5 as the acceptance threshold for any claimed improvement loop.

A loop does not count as successful unless:

- the targeted dimension reaches at least 9.5
- the change is reflected in actual skill contents, scripts, tests, or MCP runtime, not only commentary
- the change survives at least one consistency, benchmark, mutation, or parity check that could have falsified it

## Generation 4 rule

Fourth-generation claims must also survive these additional pressures:

- **anti-saturation**: self-audit cannot plateau at 10 merely because the rubric stayed shallow
- **cross-file consistency**: SKILL, references, scripts, tests, and release gates must agree on the same contract
- **budget realism**: mission budgets must be observable and, where claimed, enforced
- **ledger integrity**: evolution evidence must prove ten rounds and at least 200 accepted micro-optimizations at or above 9.5
- **release-report quality**: the release output must expose which gates passed, not just a single overall boolean


## v0.35 anti-saturation rule

A dimension may not score at or above 9.5 unless all checks for that dimension pass. A full pass can score between 9.5 and 9.8 depending on whether the dimension is also backed by stronger runtime, script, benchmark, or mutation evidence.
