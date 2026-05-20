from __future__ import annotations

import re

RECORD_TYPES = {
    "audit_plan",
    "audit_attempt",
    "audit_finding",
    "audit_disposition",
    "audit_acceptance",
    "audit_update",
}
ATTACK_TYPES = {
    "stale_evidence",
    "mission_epoch",
    "authorization_freshness",
    "receipt_replay_collision",
    "evidence_type_mismatch",
    "assertion_laundering",
    "budget_bypass",
    "counterexample_gap",
    "host_capability_overclaim",
    "secret_path_bypass",
    "opencode_bridge_gap",
    "project_learning_poisoning",
    "release_gate_drift",
    "concurrency_race",
    "install_config_drift",
}
PROFILES = {
    "runtime_gate_adversary",
    "host_harness_adversary",
    "release_claim_adversary",
    "project_learning_adversary",
    "platform_adversary",
    "concurrency_adversary",
    "install_adversary",
}
SEVERITIES = {"critical", "high", "medium", "low", "info", "none"}
DISPOSITIONS = {
    "blocking",
    "must_fix_before_release",
    "accepted_residual_risk",
    "needs_reproduction",
    "false_positive",
    "non_blocking",
}
BLOCKING_SEVERITIES = {"critical", "high"}
BUDGET_FIELDS = (
    "max_hypotheses",
    "max_executable_attacks",
    "max_runtime_seconds",
    "max_retries_per_attack",
    "max_output_bytes",
    "max_generated_artifacts",
)
BANNED_PHRASES = (
    "proved safe",
    "proves safe",
    "all vulnerabilities eliminated",
    "no vulnerabilities",
    "no bugs",
    "guaranteed secure",
    "proved correctness",
    "证明安全",
    "不存在漏洞",
    "证明不存在 bug",
)
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{20,}"),
    re.compile(r"\b(?:sk|ghp|glpat)-[A-Za-z0-9_\-]{16,}"),
)
DESTRUCTIVE_PATTERNS = ("rm -rf /", "git push", "curl http://169.254.169.254")
