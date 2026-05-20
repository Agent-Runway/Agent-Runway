# Adversarial Audit Examples

These records are deterministic examples for `scripts/adversarial_audit_lint.py`; maintainer release suites that exercise them live under `archive/release-tests/`.

```json
[
  {
    "schema_version": "1.0",
    "record_type": "audit_plan",
    "plan_id": "plan-runtime-1",
    "mission_id": "release/v0.36",
    "task_id": "v0.36",
    "target_claims": ["completion gate rejects stale receipts"],
    "target_files": ["mcp/server.py"],
    "profiles_required": ["runtime_gate_adversary"],
    "audit_scope": {
      "target_claims": ["completion gate rejects stale receipts"],
      "target_files": ["mcp/server.py"],
      "allowed_attack_types": ["stale_evidence"],
      "excluded_actions": ["network", "deployment", "git push", "secret reads"]
    },
    "audit_budget": {
      "max_hypotheses": 2,
      "max_executable_attacks": 1,
      "max_runtime_seconds": 10,
      "max_retries_per_attack": 1,
      "max_output_bytes": 10000,
      "max_generated_artifacts": 1
    },
    "freshness_baseline": {"latest_receipt_seq": 3, "timestamp": "2026-05-09T00:00:00Z"},
    "created_at": "2026-05-09T00:00:00Z",
    "source_refs": [{"kind": "file", "path": "mcp/server.py", "summary": "runtime gate target"}]
  },
  {
    "schema_version": "1.0",
    "record_type": "audit_attempt",
    "attempt_id": "attempt-runtime-1",
    "plan_id": "plan-runtime-1",
    "profile": "runtime_gate_adversary",
    "target_claims": ["completion gate rejects stale receipts"],
    "hypothesis": "A stale receipt can satisfy a post-edit completion criterion.",
    "attack_type": "stale_evidence",
    "command_or_script": "python mcp/tests/test_runtime.py RuntimeTestCase.test_completion_gate_rejects_receipts_older_than_latest_mutation",
    "artifact_paths": ["mcp/tests/test_runtime.py"],
    "execution_receipts": ["receipt-runtime-1"],
    "observed_result": "The gate rejected stale evidence.",
    "outcome": "attack_succeeded",
    "residual_risk": "Only deterministic stale receipt path covered.",
    "timestamp": "2026-05-09T00:00:01Z",
    "created_at": "2026-05-09T00:00:01Z"
  },
  {
    "schema_version": "1.0",
    "record_type": "audit_finding",
    "finding_id": "finding-blocking",
    "linked_attempt_ids": ["attempt-runtime-1"],
    "severity": "high",
    "reproducibility": "deterministic",
    "affected_claims": ["completion gate rejects stale receipts"],
    "affected_files": ["mcp/server.py"],
    "disposition": "blocking",
    "required_action": "Add a regression test and rerun audit.",
    "residual_risk": "No broader fuzzing was attempted.",
    "created_at": "2026-05-09T00:00:02Z"
  }
]
```
