#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def scorecard_rows(text: str) -> int:
    return len(re.findall(r"^\|\s*\d+\.\d+\s*\|", text, flags=re.MULTILINE))


def all_scores_at_threshold(text: str, threshold: float = 9.5) -> bool:
    scores = [float(item) for item in re.findall(r"\|\s*(9\.\d|10(?:\.0)?)\s*\|", text)]
    return bool(scores) and all(score >= threshold for score in scores)


def check(root: Path, name: str) -> tuple[bool, list[str]]:
    issues: list[str] = []
    if name == "evolution_ledger_updated":
        text = read(root / "references" / "evolution-ledger.md")
        for needle in [
            "Generation 4 accepted micro-optimizations: 200",
            "Total accepted micro-optimizations: 800",
            "Acceptance threshold per micro-optimization: 9.5 / 10",
        ]:
            if needle not in text:
                issues.append(f"evolution ledger missing {needle!r}")
    elif name == "generation4_scorecards_updated":
        text = read(root / "references" / "generation-4-scorecards.md")
        rows = scorecard_rows(text)
        if rows < 200:
            issues.append(f"generation-4 scorecards contain only {rows} accepted-loop rows")
        if not all_scores_at_threshold(text):
            issues.append("generation-4 scorecards contain a score below 9.5 or no parseable scores")
        for needle in ["Round 31", "Round 40", "Current packaged release:"]:
            if needle not in text:
                issues.append(f"generation-4 scorecards missing {needle!r}")
    elif name == "claims_reflected":
        manifest_path = root / "references" / "runtime-claim-manifest.json"
        manifest = json.loads(read(manifest_path))
        claim_ids = {claim.get("id") for claim in manifest.get("claims", [])}
        for claim_id in [
            "release-discipline",
            "opencode-plugin-bridge",
            "evolution-evidence",
            "project-learning-ledger",
            "adversarial-audit-gate",
            "host-blocking-experiments",
        ]:
            if claim_id not in claim_ids:
                issues.append(f"manifest missing claim {claim_id}")
        required = [
            "scripts/package_skill_check.py",
            "scripts/release_static_checks.py",
            "scripts/project_learning_lint.py",
            "scripts/project_learning_query.py",
            "scripts/adversarial_audit_lint.py",
            "scripts/adversarial_audit_suite.py",
            "mcp/agent_runway_runtime/adversarial_audit.py",
            "mcp/agent_runway_runtime/adversarial_audit_plan_edges.py",
            "mcp/agent_runway_runtime/adversarial_audit_reading.py",
            "scripts/host_blocking_experiments.py",
            "scripts/fixtures/pi_block_extension.js",
            "scripts/fixtures/opencode_block_experiment.mjs",
            "mcp/tests/test_release_gate.py",
            "mcp/tests/test_debug_logging.py",
            "mcp/tests/test_hook_payload_edges.py",
            "mcp/tests/test_project_learning.py",
            "mcp/tests/test_project_learning_lint.py",
            "mcp/tests/test_adversarial_audit.py",
            "mcp/tests/test_adversarial_audit_plan_edges.py",
            "mcp/tests/test_adversarial_audit_direct_helper_edges.py",
            "mcp/tests/test_adversarial_audit_read_errors.py",
            "mcp/tests/test_adversarial_audit_type_edges.py",
            "mcp/tests/test_opencode_bridge_jsonc_parser.py",
            "mcp/tests/test_opencode_bridge_payload_edges.py",
            "mcp/tests/test_opencode_plugin_jsonc_edges.py",
            "mcp/tests/test_opencode_plugin_duration_edges.py",
            "mcp/tests/test_generate_host_config.py",
            "mcp/tests/test_opencode_plugin.py",
            "mcp/tests/test_runtime_regressions.py",
            "mcp/tests/test_receipt_scope_edges.py",
            "mcp/tests/test_receipt_scope_validation_edges.py",
            "mcp/agent_runway_runtime/debug_logging.py",
            ".opencode/plugins/agent-runway.js",
            "references/project-learning-ledger.jsonl",
            "references/project-learning-ledger.schema.json",
            "references/project-learning-ledger-policy.md",
            "references/adversarial-audit.md",
            "references/adversarial-audit-rubric.md",
            "references/adversarial-audit-threat-model.md",
            "references/adversarial-audit-schema.json",
            "references/adversarial-audit-examples.md",
            "references/adversarial-audit-profiles.json",
        ]
        for rel in required:
            if not (root / rel).exists():
                issues.append(f"missing release claim artifact: {rel}")
        plugin = read(root / ".opencode" / "plugins" / "agent-runway.js")
        bridge = read(root / "scripts" / "opencode_plugin_bridge.py")
        opencode_tests = read(root / "mcp" / "tests" / "test_opencode_plugin.py")
        for needle in [
            "BRIDGE_ENVIRONMENT",
            "PYTHONDONTWRITEBYTECODE",
            "readFromConfigContent(readBridgeEnvironmentFromObject)",
        ]:
            if needle not in plugin:
                issues.append(f"OpenCode plugin missing {needle!r}")
        for needle in [
            "configure_bridge_environment",
            "sys.dont_write_bytecode = True",
            "_config_environment_from_files",
        ]:
            if needle not in bridge:
                issues.append(f"OpenCode bridge missing {needle!r}")
        for needle in [
            "test_python_bridge_loads_config_environment_before_hooks_import",
            "test_plugin_disables_python_bytecode_for_bridge_process",
        ]:
            if needle not in opencode_tests:
                issues.append(f"OpenCode plugin tests missing {needle!r}")
    elif name == "release_report_and_version":
        release_gate = read(root / "scripts" / "release_gate.py")
        current = read(root / "references" / "current-release.md")
        gates = re.findall(r'\("([a-z0-9_]+)",\s*"run"', release_gate)
        if len(gates) != 16:
            issues.append(f"release_gate.py declares {len(gates)} runnable gates instead of 16")
        for needle in ["elapsed_seconds", "timeout_scale", "output", "package_skill_validation"]:
            if needle not in release_gate:
                issues.append(f"release gate report missing {needle!r}")
        for needle in ["v0.36", "16-gate", "adversarial_audit_suite", "project_learning_lint", "receipt nonce"]:
            if needle.lower() not in current.lower():
                issues.append(f"current-release.md missing {needle!r}")
    elif name == "adversarial_audit_valid":
        for rel in [
            "references/adversarial-audit.md",
            "references/adversarial-audit-rubric.md",
            "references/adversarial-audit-threat-model.md",
            "references/adversarial-audit-schema.json",
            "references/adversarial-audit-examples.md",
            "references/adversarial-audit-profiles.json",
            "scripts/adversarial_audit_lint.py",
            "scripts/adversarial_audit_suite.py",
            "mcp/agent_runway_runtime/adversarial_audit.py",
            "mcp/agent_runway_runtime/adversarial_audit_plan_edges.py",
            "mcp/agent_runway_runtime/adversarial_audit_reading.py",
            "mcp/tests/test_adversarial_audit.py",
            "mcp/tests/test_adversarial_audit_plan_edges.py",
            "mcp/tests/test_adversarial_audit_direct_helper_edges.py",
            "mcp/tests/test_adversarial_audit_read_errors.py",
            "mcp/tests/test_adversarial_audit_type_edges.py",
        ]:
            if not (root / rel).exists():
                issues.append(f"missing adversarial audit artifact: {rel}")
        policy = read(root / "references" / "adversarial-audit.md")
        for needle in ["bounded falsification", "never proves absence of bugs", "No full multi-agent scheduler"]:
            if needle not in policy:
                issues.append(f"adversarial audit policy missing {needle!r}")
    elif name == "project_learning_valid":
        for rel in [
            "references/project-learning-ledger.jsonl",
            "references/project-learning-ledger.schema.json",
            "references/project-learning-ledger-policy.md",
            "scripts/project_learning_lint.py",
            "scripts/project_learning_query.py",
        ]:
            if not (root / rel).exists():
                issues.append(f"missing project learning artifact: {rel}")
        policy = read(root / "references" / "project-learning-ledger-policy.md")
        for needle in ["Memory is not evidence", "Preference is not authorization", "Memory Routing", "Non-Goals"]:
            if needle not in policy:
                issues.append(f"project learning policy missing {needle!r}")
    else:
        issues.append(f"unknown release static check: {name}")
    return not issues, issues


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root")
    parser.add_argument("check_name")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    passed, issues = check(root, args.check_name)
    print(json.dumps({"check": args.check_name, "issues": issues, "passed": passed}, indent=2, ensure_ascii=False))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
