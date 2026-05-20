# Release Gates

Do not claim the skill improved unless these gates pass.

## Mandatory automated gates

`release_gate.py` must run these fifteen gates directly and report every result independently.

1. `quick_validate`: local skill frontmatter and structure validation passes
2. `package_skill_validation`: package validation gate; packaged-skill validation passes, including creation of a `skill.zip` and validation after extraction; when the official skill-creator `package_skill.py` is available, it must also pass
3. `unit_tests`: the bundled MCP/unit regression tests pass
4. `smoke_test`: the smoke test passes
5. `consistency_lint`: cross-file consistency lint passes
6. `claim_parity_audit`: runtime-claim parity audit passes (claim-parity audit)
7. `project_learning_lint`: `scripts/project_learning_lint.py` validates the canonical ledger in strict mode before release
8. `ledger_guard`: evolution ledger guard passes
9. `self_audit`: self-audit passes at the declared threshold
10. `benchmark_suite`: benchmark suite passes
11. `adversarial_audit_suite`: deterministic Adversarial Audit Gate fixtures pass, including no-receipt blockers, stale audit coverage, Project Learning Ledger seed-only boundaries, and banned proof-of-safety language
12. `adversarial_mutation_suite`: adversarial mutation suite passes
13. `evolution_ledger_updated`: the evolution ledger is updated and machine-checkable
14. `generation4_scorecards_updated`: generation-4 scorecards are updated and contain accepted loops at or above the threshold
15. `claims_reflected`: new release claims are reflected in actual files, scripts, MCP tools, hooks, tests, or explicit advisory labeling
16. `release_report_and_version`: the release report shows each gate result and the packaged version marker is current

## Red flags

Stop the release if:

- the score improved only because the rubric got weaker
- the benchmark can be passed without new evidence
- the skill became noticeably easier to over-apply
- a stronger guarantee is claimed without a stronger runtime basis
- a degraded mutant still passes the audit or benchmark that was supposed to catch it
- the self-score saturates at 10 while parity, consistency, packaging, or mutation checks remain shallow
- the release report hides which gate failed behind a single opaque overall boolean
- the package claims a new version while the current-release reference still names an older one
- `package_skill_validation` is absent, skipped, or only inferred from a prior operator log

## Release report quality

The release report shows each gate result, elapsed time, timeout condition, output preview, gate count, and failure detail. A skipped mandatory validator or packager is a release failure, not a pass.


<!-- legacy phrase markers: official skill validator; packaged-skill validation; consistency lint passes; claim-parity audit passes; ledger guard passes -->
