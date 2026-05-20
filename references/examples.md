# Worked Examples

## Example 1: local bug fix

Mission shape:

- goal: fix a failing test without changing the public API
- completion criteria:
  - the original failing test now passes
  - the full targeted test suite passes
  - the public function signature is unchanged
- scope boundary: do not redesign unrelated parsing logic
- red lines: no push, deploy, or external writes

Useful receipts:

- failing test reproduction receipt
- file-write receipt for the code change
- read-back or diff receipt
- passing test receipt

Legal stop:

- `slice_verified` after the repair was validated
- `completion_gate` only after all criteria map to receipts

## Example 2: research synthesis

Mission shape:

- goal: produce a sourced answer with a recommendation
- completion criteria:
  - the answer includes the requested comparison
  - every load-bearing factual claim is sourced
  - the recommendation is clearly labeled as an inference
- scope boundary: do not expand into unrelated market mapping
- red lines: no outbound contact, no external writes

Useful receipts:

- source reads
- notes or extracted evidence
- final answer section read-back

Legal stop:

- `user_information_required` only if a missing preference truly blocks the recommendation

## Example 3: project learning ledger JSONL snippets

### `pitfall`

```json
{"schema_version":"1.0","type":"pitfall","id":"pitfall_opencode_bridge_optional","project_id":"agent-runway","status":"active","summary":"OpenCode native MCP works by default, but the optional plugin bridge only forwards tool events when ILH_OPENCODE_BRIDGE=1 is set.","applies_to":{"hosts":["opencode"],"tasks":["host setup"]},"source_refs":[{"kind":"file","path":"README.md","summary":"OpenCode bridge is optional."}],"created_at":"2026-05-08T00:00:00Z","last_verified_at":"2026-05-08T00:00:00Z","invalid_if":["The bridge becomes enabled by default."],"severity":"high","can_support_completion":false,"requires_fresh_verification":true}
```

### `runbook`

```json
{"schema_version":"1.0","type":"runbook","id":"runbook_release_validation_order","project_id":"agent-runway","status":"active","summary":"Run release validation in the same order as release_gate.py before claiming a packaged release.","applies_to":{"tasks":["release"],"commands":["python scripts/release_gate.py ."]},"source_refs":[{"kind":"file","path":"references/release-gates.md","summary":"Release order is documented here."}],"created_at":"2026-05-08T00:00:00Z","last_verified_at":"2026-05-08T00:00:00Z","steps":["Run quick_validate.","Run package_skill_validation.","Run unit tests and smoke test."],"invalid_if":["release_gate.py changes its gate order."],"severity":"high","can_support_completion":false,"requires_fresh_verification":true}
```

### `preference`

```json
{"schema_version":"1.0","type":"preference","id":"pref_project_docs_accuracy_first","project_id":"agent-runway","status":"active","summary":"For project docs, prioritize accuracy and runtime honesty first, then reduce generic AI tone.","applies_to":{"tasks":["documentation"],"scope":"project-docs"},"source_refs":[{"kind":"user_confirmation","summary":"User requested accuracy-first documentation."}],"created_at":"2026-05-08T00:00:00Z","last_confirmed_at":"2026-05-08T00:00:00Z","priority":"high","can_support_completion":false,"requires_fresh_verification":true}
```

### `invariant`

```json
{"schema_version":"1.0","type":"invariant","id":"inv_host_enforcement_honesty","project_id":"agent-runway","status":"active","summary":"Without configured hooks, stop enforcement remains advisory; OpenCode must not be described as having Claude Code Stop-hook parity.","applies_to":{"hosts":["opencode","codex","vscode","cursor"],"tasks":["documentation","runtime claims"]},"source_refs":[{"kind":"file","path":"references/runtime-capability-matrix.md","summary":"Capability matrix separates hosted and advisory guarantees."}],"created_at":"2026-05-08T00:00:00Z","last_verified_at":"2026-05-08T00:00:00Z","invalid_if":["A host adds tested Stop-hook parity and docs are updated."],"severity":"critical","can_support_completion":false,"requires_fresh_verification":true}
```
