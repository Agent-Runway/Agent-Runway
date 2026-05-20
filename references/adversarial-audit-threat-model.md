# Adversarial Audit Threat Model

Adversarial auditing introduces a new governance surface. The adversary must not become a privileged attacker.

| Risk | Mitigation |
|---|---|
| Sandbox escape | v0.36 uses documented tmp workspace rules and host risk interception; no OS isolation claim |
| Secret reads | Lint rejects secret-like material and policy forbids secret path reads |
| Destructive commands | Excluded actions and static command checks reject destructive examples |
| Network use | Default excluded action unless mission explicitly authorizes it |
| Infinite loops | Audit budget requires runtime, retry, output, and artifact caps |
| Output floods | `max_output_bytes` is mandatory |
| Memory poisoning | Project Learning Ledger is seed-only, never evidence or authorization |
| Flaky findings | Flaky or single-observation findings stay `needs_reproduction` unless deterministic security bypass exists |
| False positives | Judge/Gate disposition can mark `false_positive` without deleting history |
| Overclaiming | Banned proof-of-safety phrases are linted in audit records and release claims |

The MVP is deterministic and fixture-driven. It does not claim networked sandboxing, automatic red-team orchestration, or exhaustive fuzzing.
