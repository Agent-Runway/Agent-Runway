# Adversarial Audit Rubric

## Severity

| Severity | Meaning | Default gate effect |
|---|---|---|
| `critical` | Completion, authorization, or secret boundary bypass | Blocking |
| `high` | False pass, stale evidence, release gate bypass, host parity overclaim | Blocking or must-fix before release |
| `medium` | Reliability, install, host consistency, flakiness with evidence | Case-by-case residual risk |
| `low` | Documentation or low-impact edge case | Non-blocking |
| `info` | Useful observation without gate impact | Non-blocking |
| `none` | Attack did not falsify the claim within scope and budget | Non-blocking |

## Disposition

| Disposition | Rule |
|---|---|
| `blocking` | Requires critical/high severity, in-scope claim, reproducible successful attempt, and receipt/direct artifact |
| `must_fix_before_release` | Release blocker that may not block the current local slice |
| `accepted_residual_risk` | Requires scoped acceptance record with reason and expiry where appropriate |
| `needs_reproduction` | Suspicion without deterministic evidence; does not block |
| `false_positive` | Adversary claim was wrong; keep the record |
| `non_blocking` | Real but not gate-blocking within this mission |

## Freshness

If target files or mission epoch change after the audit freshness baseline, the audit coverage is stale. Stale audit records can document history but cannot satisfy a required audit gate.

## Residual Risk

Allowed wording: "No blocking counterexample was found within the configured scope and budget; residual risks remain." Forbidden wording includes proof-of-safety claims such as "proved safe", "all vulnerabilities eliminated", and "不存在漏洞".
