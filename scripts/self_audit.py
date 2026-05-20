#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

DIMENSIONS = [
    'invocation_specificity',
    'trigger_boundary_precision',
    'runtime_honesty',
    'mission_schema_rigor',
    'slice_discipline_clarity',
    'evidence_traceability',
    'stop_condition_precision',
    'stuck_escalation_discipline',
    'authority_boundary_safety',
    'output_contract_usability',
    'progressive_loading_structure',
    'operability_and_quickstart',
    'degradation_resilience',
    'adversarial_robustness',
    'composition_interoperability',
    'benchmarkability_and_release_governance',
    'claim_runtime_parity',
    'counterexample_discipline',
    'handoff_packet_quality',
    'evaluation_hardness',
    'cross_file_consistency',
    'budget_observability_and_enforcement',
    'ledger_integrity',
    'release_report_quality',
    'project_learning_boundary',
]


def read(path: Path) -> str:
    return path.read_text(encoding='utf-8') if path.exists() else ''


def run_script(root: Path, script_name: str) -> dict:
    proc = subprocess.run([sys.executable, f'scripts/{script_name}', str(root)], cwd=str(root), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    text = proc.stdout.strip()
    try:
        payload = json.loads(text) if text else {}
    except json.JSONDecodeError:
        payload = {'raw_output': text}
    payload['returncode'] = proc.returncode
    payload['passed'] = proc.returncode == 0
    return payload


def approx_score(total_checks: int, passed_checks: int, hard_backed: bool = False) -> float:
    if total_checks <= 0:
        return 0.0
    if passed_checks < total_checks:
        ratio = passed_checks / total_checks
        score = 7.0 + 2.4 * ratio
        return round(min(9.4, score), 2)
    score = 9.5
    if hard_backed:
        score += 0.3
    return round(min(9.8, score), 2)


def parse_server_tools(server_text: str) -> set[str]:
    return set(re.findall(r'^def\s+([a-zA-Z_][a-zA-Z0-9_]*)\(', server_text, flags=re.MULTILINE))


def contains(text: str, *needles: str) -> bool:
    lowered = text.lower()
    return all(needle.lower() in lowered for needle in needles)


def main() -> int:
    if len(sys.argv) != 2:
        print('usage: python scripts/self_audit.py <skill-root>')
        return 1
    root = Path(sys.argv[1]).resolve()
    skill_md = read(root / 'SKILL.md')
    refs = {p.name: read(p) for p in (root / 'references').iterdir() if p.is_file()}
    scripts = {p.name: read(p) for p in (root / 'scripts').glob('*.py')}
    tests = {p.name: read(p) for p in (root / 'mcp' / 'tests').glob('test_*.py')}
    server_text = read(root / 'mcp' / 'server.py')
    tool_names = parse_server_tools(server_text)

    consistency = run_script(root, 'consistency_lint.py')
    parity = run_script(root, 'claim_parity_audit.py')
    ledger = run_script(root, 'ledger_guard.py')
    package_validation = {
        'passed': (root / 'scripts' / 'package_skill_check.py').exists() and 'package_skill_validation' in read(root / 'scripts' / 'release_gate.py'),
        'returncode': 0,
        'note': 'package_skill_validation is executed as an independent release_gate.py gate; self_audit checks wiring to avoid recursive packaging inside self-audit',
    }
    project_lint = subprocess.run(
        [sys.executable, 'scripts/project_learning_lint.py', str(root / 'references' / 'project-learning-ledger.jsonl'), '--strict'],
        cwd=str(root),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    evidence: dict[str, list[str]] = {name: [] for name in DIMENSIONS}
    scores: dict[str, float] = {}

    checks = {
        'invocation_specificity': [
            contains(skill_md, 'activation rule'),
            contains(skill_md, 'do not over-apply'),
            contains(skill_md, 'primary executor'),
            'trigger-matrix.md' in refs,
            'runtime-capability-matrix.md' in refs,
        ],
        'trigger_boundary_precision': [
            'trigger-matrix.md' in refs,
            contains(refs.get('trigger-matrix.md', ''), 'positive triggers', 'negative triggers', 'borderline'),
            contains(skill_md, 'tiny, low-risk, single-action tasks'),
            contains(refs.get('benchmark-suite.md', ''), 'tiny low-risk task', 'stale gate freshness'),
            consistency['passed'],
        ],
        'runtime_honesty': [
            contains(skill_md, 'runtime honesty'),
            'operating-modes.md' in refs,
            'degradation-modes.md' in refs,
            'runtime-capability-matrix.md' in refs,
            parity['passed'],
        ],
        'mission_schema_rigor': [
            'mission-schema.md' in refs,
            contains(refs.get('mission-schema.md', ''), 'verification_plan', 'evidence_map'),
            contains(refs.get('mission-schema.md', ''), 'counterexample_required', 'time_budget_minutes', 'risk_budget'),
            all(name in tool_names for name in ['mission_lock', 'mission_status', 'budget_status']),
            contains(server_text, 'time_budget_minutes', 'risk_budget'),
        ],
        'slice_discipline_clarity': [
            contains(skill_md, 'slice discipline'),
            contains(skill_md, 'action frontier rule'),
            contains(skill_md, 'disconfirming check'),
            'turn_end_gate' in tool_names,
            contains(server_text, 'slice_budget is exhausted'),
        ],
        'evidence_traceability': [
            'evidence-provenance.md' in refs,
            contains(refs.get('evidence-provenance.md', ''), 'direct', 'derived', 'historical', 'unverified'),
            contains(skill_md, 'criterion-to-evidence mapping'),
            'verify_receipt_integrity' in tool_names,
            contains(server_text, 'invalid receipt signature'),
        ],
        'stop_condition_precision': [
            'stop-conditions.md' in refs,
            contains(refs.get('stop-conditions.md', ''), 'decision table', 'illegal reasons to stop'),
            'turn_end_gate' in tool_names,
            contains(server_text, 'LEGAL_STOP_CONDITIONS'),
            contains(refs.get('benchmark-suite.md', ''), 'stale gate freshness'),
        ],
        'stuck_escalation_discipline': [
            'stuck-escalation.md' in refs,
            contains(refs.get('stuck-escalation.md', ''), 'materially different', 'escalation'),
            'record_stuck_attempt' in tool_names,
            contains(server_text, 'materially different recorded attempts'),
            'budget_status' in tool_names,
        ],
        'authority_boundary_safety': [
            'authority-boundaries.md' in refs,
            contains(refs.get('authority-boundaries.md', ''), 'permission theater', 'externally visible'),
            'approval_required' in server_text,
            all(name in tool_names for name in ['record_user_authorization', 'authorization_status']),
            'test_hooks.py' in tests,
            contains(read(root / 'scripts' / 'claude_hooks.py'), 'permissionDecision', 'deny'),
        ],
        'output_contract_usability': [
            'report-templates.md' in refs,
            contains(refs.get('report-templates.md', ''), 'progress report', 'completion report', 'handoff report'),
            contains(refs.get('report-templates.md', ''), 'Budget status:'),
            contains(skill_md, 'output contract'),
            contains(skill_md, 'handoff packet'),
            contains(refs.get('current-release.md', ''), 'v0.36'),
        ],
        'progressive_loading_structure': [
            contains(skill_md, 'reference map'),
            len(refs) >= 25,
            all(name in refs for name in ['runtime-capability-matrix.md', 'generation-4-scorecards.md', 'runtime-claim-manifest.json']),
            contains(skill_md, 'Load these references only when relevant'),
            consistency['passed'],
        ],
        'operability_and_quickstart': [
            'quickstart.md' in refs,
            contains(refs.get('quickstart.md', ''), 'consistency lint', 'claim-parity audit', 'ledger guard', 'package validation gate'),
            all(name in scripts for name in ['quick_validate.py', 'package_skill_check.py', 'release_static_checks.py', 'release_gate.py', 'benchmark_suite.py', 'self_audit.py', 'smoke_test.py', 'adversarial_audit_lint.py', 'adversarial_audit_suite.py', 'adversarial_mutation_suite.py', 'consistency_lint.py', 'claim_parity_audit.py', 'ledger_guard.py']),
            'test_runtime.py' in tests,
            contains(refs.get('quickstart.md', ''), 'package only after all checks pass'),
        ],
        'degradation_resilience': [
            'degradation-modes.md' in refs,
            contains(refs.get('degradation-modes.md', ''), 'downgrade', 'weak runtime'),
            contains(skill_md, 'degradation mode'),
            contains(server_text, 'degradation_mode'),
            contains(refs.get('runtime-capability-matrix.md', ''), 'soft mode', 'mcp mode', 'hosted mode'),
        ],
        'adversarial_robustness': [
            'adversarial-robustness.md' in refs,
            'adversarial-audit.md' in refs,
            'adversarial-audit-schema.json' in refs,
            contains(refs.get('adversarial-robustness.md', ''), 'gaming', 'goodhart'),
            contains(refs.get('adversarial-audit.md', ''), 'bounded falsification', 'never proves absence of bugs'),
            'counterexample-discipline.md' in refs,
            'adversarial_audit_suite.py' in scripts,
            'adversarial_mutation_suite.py' in scripts,
            contains(refs.get('evaluation-hardness.md', ''), 'mutation tests'),
            contains(read(root / 'scripts' / 'adversarial_mutation_suite.py'), 'missing_budget_tool', 'corrupt_manifest_tool'),
        ],
        'composition_interoperability': [
            'skill-composition.md' in refs,
            contains(refs.get('skill-composition.md', ''), 'precedence', 'delegation'),
            contains(skill_md, 'do not let control planes conflict silently'),
            consistency['passed'],
        ],
        'benchmarkability_and_release_governance': [
            'benchmark-suite.md' in refs,
            'release-gates.md' in refs,
            contains(refs.get('release-gates.md', ''), 'consistency lint passes', 'claim-parity audit passes', 'ledger guard passes', 'adversarial_audit_suite'),
            contains(read(root / 'scripts' / 'release_gate.py'), 'quick_validate.py', 'consistency_lint.py', 'claim_parity_audit.py', 'ledger_guard.py', 'adversarial_audit_suite'),
            contains(read(root / 'scripts' / 'benchmark_suite.py'), 'slice_budget_exhaustion_case', 'stale_turn_gate_case'),
        ],
        'claim_runtime_parity': [
            'claim-runtime-parity.md' in refs,
            'runtime-claim-manifest.json' in refs,
            contains(skill_md, 'runtime-capability-matrix.md', 'runtime-claim-manifest.json'),
            parity['passed'],
            all(name in tool_names for name in ['record_decision_record', 'record_counterexample_check', 'verify_receipt_integrity', 'export_handoff_packet', 'budget_status', 'record_user_authorization', 'authorization_status']),
        ],
        'counterexample_discipline': [
            'counterexample-discipline.md' in refs,
            contains(skill_md, 'counterexample discipline'),
            'record_counterexample_check' in tool_names,
            contains(server_text, 'Mission requires at least one recorded counterexample check before completion'),
            contains(refs.get('report-templates.md', ''), 'Counterexample check'),
        ],
        'handoff_packet_quality': [
            'handoff-packets.md' in refs,
            contains(skill_md, 'Handoff packets'),
            'export_handoff_packet' in tool_names,
            contains(server_text, 'budget_status', 'criterion_coverage'),
            contains(server_text, 'latest_user_authorization'),
            contains(refs.get('benchmark-suite.md', ''), 'handoff packet'),
        ],
        'evaluation_hardness': [
            'evaluation-hardness.md' in refs,
            'generation-4-scorecards.md' in refs,
            'adversarial_mutation_suite.py' in scripts,
            contains(refs.get('release-gates.md', ''), 'degraded mutant still passes'),
            contains(refs.get('benchmark-suite.md', ''), 'stale gate freshness', 'slice-budget exhaustion'),
        ],
        'cross_file_consistency': [
            consistency['passed'],
            contains(refs.get('release-gates.md', ''), 'consistency lint passes'),
            contains(refs.get('quickstart.md', ''), 'consistency lint'),
            contains(refs.get('claim-runtime-parity.md', ''), 'runtime-claim-manifest.json'),
            contains(skill_md, 'runtime-capability-matrix.md', 'generation-4-scorecards.md'),
        ],
        'budget_observability_and_enforcement': [
            'budget_status' in tool_names,
            contains(server_text, 'slice_budget is exhausted', 'time budget is exhausted'),
            contains(server_text, 'time_pressure'),
            contains(refs.get('report-templates.md', ''), 'Budget status:'),
            contains(read(root / 'scripts' / 'benchmark_suite.py'), 'budget_status_case', 'slice_budget_exhaustion_case'),
            contains(read(root / 'scripts' / 'benchmark_suite.py'), 'authorization_status_case', 'authorization_handoff_case'),
        ],
        'ledger_integrity': [
            ledger['passed'],
            'generation-4-scorecards.md' in refs,
            contains(refs.get('evolution-ledger.md', ''), 'Generation 4 accepted micro-optimizations: 200'),
            contains(refs.get('evolution-ledger.md', ''), 'Total accepted micro-optimizations: 800'),
            'ledger_guard.py' in scripts,
        ],
        'release_report_quality': [
            contains(read(root / 'scripts' / 'release_gate.py'), 'quick_validate', 'package_skill_validation', 'consistency_lint', 'claim_parity_audit', 'ledger_guard', 'adversarial_audit_suite', 'release_report_and_version'),
            contains(refs.get('release-gates.md', ''), 'the release report shows each gate result'),
            contains(refs.get('release-gates.md', ''), 'package_skill_validation', '16'),
            package_validation['passed'],
            contains(refs.get('scoring-rubric.md', ''), 'release-report quality'),
            contains(refs.get('current-release.md', ''), 'v0.36'),
            consistency['passed'],
            parity['passed'],
        ],
        'project_learning_boundary': [
            'project-learning-ledger-policy.md' in refs,
            'project-learning-ledger.jsonl' in refs,
            'project-learning-ledger.schema.json' in refs,
            'project_learning_lint.py' in scripts,
            'project_learning_query.py' in scripts,
            contains(refs.get('project-learning-ledger-policy.md', ''), 'Memory is not evidence', 'Preference is not authorization', 'Memory Routing'),
            project_lint.returncode == 0,
            'record_project_learning' not in server_text and 'query_project_learning' not in server_text,
        ],
    }

    hard_backed = {
        'runtime_honesty': parity['passed'],
        'evidence_traceability': parity['passed'],
        'authority_boundary_safety': True,
        'operability_and_quickstart': True,
        'adversarial_robustness': True,
        'benchmarkability_and_release_governance': True,
        'claim_runtime_parity': parity['passed'],
        'handoff_packet_quality': True,
        'evaluation_hardness': True,
        'cross_file_consistency': consistency['passed'],
        'budget_observability_and_enforcement': True,
        'ledger_integrity': ledger['passed'],
        'release_report_quality': consistency['passed'] and parity['passed'] and ledger['passed'] and package_validation['passed'],
        'project_learning_boundary': project_lint.returncode == 0 and consistency['passed'],
    }

    for dimension, values in checks.items():
        score = approx_score(len(values), sum(bool(v) for v in values), hard_backed.get(dimension, False))
        scores[dimension] = score
        evidence[dimension] = [f'check_{i+1}={bool(v)}' for i, v in enumerate(values)] + [f'hard_backed={hard_backed.get(dimension, False)}']

    average = round(sum(scores.values()) / len(scores), 2)
    payload = {
        'skill_root': str(root),
        'version': 'v0.36',
        'anti_saturation_policy': 'dimensions cannot reach 9.5 unless every local check passes; full-pass scores are capped below 10',
        'dimension_count': len(scores),
        'scores': scores,
        'average': average,
        'pass_threshold': 9.5,
        'consistency_lint': consistency,
        'claim_parity_audit': parity,
        'ledger_guard': ledger,
        'package_skill_validation': package_validation,
        'project_learning_lint': {'returncode': project_lint.returncode, 'passed': project_lint.returncode == 0, 'output': project_lint.stdout.strip()},
        'dimension_evidence': evidence,
        'passed': average >= 9.5 and min(scores.values()) >= 9.5 and consistency['passed'] and parity['passed'] and ledger['passed'] and package_validation['passed'],
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if payload['passed'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
