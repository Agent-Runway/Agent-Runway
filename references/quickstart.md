# Quickstart

## Validate the skill package

```bash
python /home/oai/skills/skill-creator/scripts/quick_validate.py /path/to/agent-runway
```

## Run the MCP tests

```bash
python -m unittest discover -s mcp/tests -p 'test_*.py'
```

## Run the smoke test

```bash
python scripts/smoke_test.py
```

## Run the consistency lint

```bash
python scripts/consistency_lint.py /path/to/agent-runway
```

## Run the claim-parity audit

```bash
python scripts/claim_parity_audit.py /path/to/agent-runway
```

## Run the project learning lint

```bash
python scripts/project_learning_lint.py /path/to/agent-runway/references/project-learning-ledger.jsonl --strict
```

## Run the ledger guard

```bash
python scripts/ledger_guard.py /path/to/agent-runway
```

## Current packaged version

`v0.36`

## Run the self-audit

```bash
python scripts/self_audit.py /path/to/agent-runway
```

## Run the benchmark suite

```bash
python scripts/benchmark_suite.py /path/to/agent-runway
```

## Run the adversarial mutation suite

```bash
python scripts/adversarial_mutation_suite.py /path/to/agent-runway
```

## Run the adversarial audit suite

```bash
python scripts/adversarial_audit_suite.py /path/to/agent-runway
```

## Run the package validation gate

```bash
python scripts/package_skill_check.py /path/to/agent-runway
```

## Run the release gate

```bash
python scripts/release_gate.py /path/to/agent-runway
```

## Generate host settings

```bash
python scripts/generate_host_config.py --project-dir /absolute/path/to/agent-runway
python scripts/generate_host_config.py --host opencode --project-dir /absolute/path/to/agent-runway
```

## Package the skill

```bash
python /home/oai/skills/skill-creator/scripts/package_skill.py /path/to/agent-runway /path/to/output-dir
```

## Recommended order

1. validate structure
2. run unit tests
3. run smoke test
4. run consistency lint
5. run claim-parity audit
6. run project learning lint
7. run ledger guard
8. run self-audit
9. run benchmark suite
10. run adversarial mutation suite
11. run package validation gate
12. run release gate
13. generate host settings if needed
14. package only after all checks pass
