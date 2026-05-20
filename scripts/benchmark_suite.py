#!/usr/bin/env python3
from __future__ import annotations

import importlib
import json
import os
import subprocess
import tempfile
from pathlib import Path


def read(path: Path) -> str:
    return path.read_text(encoding='utf-8') if path.exists() else ''


def run_json(cmd: list[str], root: Path) -> tuple[int, dict]:
    proc = subprocess.run(cmd, cwd=str(root), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        payload = {'raw_output': proc.stdout}
    return proc.returncode, payload


def main() -> int:
    if len(os.sys.argv) != 2:
        print('usage: python scripts/benchmark_suite.py <skill-root>')
        return 1
    root = Path(os.sys.argv[1]).resolve()
    temp_dir = tempfile.TemporaryDirectory()
    os.environ['ILH_DB_PATH'] = str(Path(temp_dir.name) / 'state.db')
    os.environ['ILH_SECRET_PATH'] = str(Path(temp_dir.name) / 'secret.key')

    import sys
    mcp_root = str(root / 'mcp')
    if mcp_root not in sys.path:
        sys.path.insert(0, mcp_root)

    server = importlib.import_module('server')
    server = importlib.reload(server)
    store = server.store

    cases = {}

    session_id = 'bench-session'
    task_id = 'bench-task'
    server.mission_lock(
        session_id,
        task_id,
        'verify the generation-4 control loop',
        ['validated receipt exists'],
        verification_plan=['record a receipt', 'verify integrity', 'record decision', 'record counterexample'],
        evidence_map=[{'criterion': 'validated receipt exists', 'evidence': ['fresh verified receipt']}],
        counterexample_required=True,
        decision_records_required=True,
        time_budget_minutes=20,
        risk_budget='local reversible checks only',
    )
    receipt = store.record_receipt(
        session_id=session_id,
        task_id=task_id,
        source='benchmark',
        tool_name='Bash',
        command_text='python -m unittest',
        exit_code=0,
        metadata={'stdout_sha256': 'ok'},
    )

    integrity = json.loads(server.verify_receipt_integrity(session_id, [receipt.receipt_id], task_id))
    cases['receipt_integrity_case'] = integrity['all_valid']

    rejected = server.completion_gate(
        session_id=session_id,
        task_id=task_id,
        criterion_receipt_map=[{'criterion': 'validated receipt exists', 'receipt_ids': [receipt.receipt_id]}],
        completion_summary='Recorded the required receipt, but did not yet add all required governance artifacts.',
    )
    cases['negative_missing_required_records_case'] = 'REJECTED' in rejected and 'counterexample' in rejected.lower() and 'decision record' in rejected.lower()

    cases['decision_record_case'] = 'DECISION RECORDED' in server.record_decision_record(
        session_id,
        task_id,
        'verify receipt before completion',
        'run integrity check first',
        ['skip integrity check'],
        [receipt.receipt_id],
        'reversible',
        ['integrity mismatch'],
    )
    cases['counterexample_case'] = 'COUNTEREXAMPLE CHECK RECORDED' in server.record_counterexample_check(
        session_id,
        task_id,
        'receipt might not verify',
        ['recompute signature'],
        'signature verified successfully',
        [receipt.receipt_id],
        'host provenance still depends on runtime configuration',
    )
    turn = server.turn_end_gate(
        session_id=session_id,
        task_id=task_id,
        stop_condition='slice_verified',
        work_summary='Recorded a fresh receipt, validated its integrity, and documented the decision plus counterexample result.',
        receipt_ids=[receipt.receipt_id],
    )
    cases['positive_turn_gate_case'] = 'APPROVED' in turn

    stale_receipt = store.record_receipt(
        session_id=session_id,
        task_id=task_id,
        source='benchmark',
        tool_name='Bash',
        command_text='python stale_check.py',
        exit_code=0,
        metadata={'stdout_sha256': 'new'},
    )
    packet_after_new_receipt = json.loads(server.export_handoff_packet(session_id, task_id))
    cases['stale_turn_gate_case'] = packet_after_new_receipt['latest_turn_gate'] is not None and packet_after_new_receipt['latest_turn_gate']['fresh'] is False

    completion = server.completion_gate(
        session_id=session_id,
        task_id=task_id,
        criterion_receipt_map=[{'criterion': 'validated receipt exists', 'receipt_ids': [receipt.receipt_id]}],
        completion_summary='Recorded a fresh receipt, verified it, and satisfied the required decision and counterexample records.',
        known_risks=['hosted enforcement still depends on configured hooks'],
        unverified_items=['no live hosted hook was exercised in this benchmark'],
    )
    cases['positive_completion_case'] = 'APPROVED' in completion
    packet = json.loads(server.export_handoff_packet(session_id, task_id))
    cases['handoff_packet_case'] = all(key in packet for key in ['mission', 'latest_receipts', 'decision_records', 'counterexample_checks', 'budget_status', 'recommended_next_action'])
    criterion_coverage = packet.get('criterion_coverage', [])
    cases['handoff_criterion_coverage_case'] = bool(criterion_coverage) and criterion_coverage[0]['criterion'] == 'validated receipt exists'
    cases['handoff_known_risks_case'] = 'hosted enforcement still depends on configured hooks' in packet.get('known_risks', [])
    cases['handoff_unverified_items_case'] = 'no live hosted hook was exercised in this benchmark' in packet.get('unverified_items', [])

    budget_status = json.loads(server.budget_status(session_id, task_id))
    cases['budget_status_case'] = budget_status['slices_remaining'] >= 0 and 'time_pressure' in budget_status and 'latest_completion_gate_fresh' in budget_status

    auth_session = 'auth-session'
    auth_task = 'auth-task'
    server.mission_lock(auth_session, auth_task, 'perform authorized external action', ['approval recorded'])
    auth_receipt = store.record_receipt(
        session_id=auth_session,
        task_id=auth_task,
        source='benchmark',
        tool_name='Bash',
        command_text='python prepare.py',
        exit_code=0,
        metadata={'stdout_sha256': 'prep'},
    )
    auth_record = server.record_user_authorization(
        auth_session,
        auth_task,
        action_scope='send one outbound status email to the approved recipient',
        approval_scope='single outbound email only',
        user_statement_excerpt='Yes, send that one status email.',
        irreversible=True,
        ttl_seconds=900,
    )
    auth_status = json.loads(server.authorization_status(auth_session, auth_task))
    cases['authorization_record_case'] = 'USER AUTHORIZATION RECORDED' in auth_record
    cases['authorization_status_case'] = auth_status['authorization'] is not None and auth_status['authorization']['fresh'] is True and auth_status['authorization']['irreversible'] is True
    store.record_receipt(
        session_id=auth_session,
        task_id=auth_task,
        source='benchmark',
        tool_name='Bash',
        command_text='python after_auth.py',
        exit_code=0,
        metadata={'stdout_sha256': 'after'},
    )
    auth_status_stale = json.loads(server.authorization_status(auth_session, auth_task))
    auth_packet = json.loads(server.export_handoff_packet(auth_session, auth_task))
    cases['authorization_staleness_case'] = auth_status_stale['authorization'] is not None and auth_status_stale['authorization']['fresh'] is False
    cases['authorization_handoff_case'] = auth_packet.get('latest_user_authorization') is not None and auth_packet['latest_user_authorization']['action_scope'].startswith('send one outbound status email')

    fail_session = 'fail-session'
    fail_task = 'fail-task'
    server.mission_lock(fail_session, fail_task, 'reject failed receipt', ['tests pass'])
    failed_receipt = store.record_receipt(
        session_id=fail_session,
        task_id=fail_task,
        source='benchmark',
        tool_name='Bash',
        command_text='pytest -q',
        exit_code=1,
        metadata={'stdout_sha256': 'bad'},
    )
    failed_completion = server.completion_gate(
        session_id=fail_session,
        task_id=fail_task,
        criterion_receipt_map=[{'criterion': 'tests pass', 'receipt_ids': [failed_receipt.receipt_id]}],
        completion_summary='Attempted to map a failing test receipt to completion.',
    )
    cases['failed_bash_receipt_rejected_case'] = 'REJECTED' in failed_completion and 'failed execution receipt' in failed_completion

    codex_session = 'codex-session'
    codex_task = 'codex-task'
    server.mission_lock(codex_session, codex_task, 'codex execution receipt', ['tests pass'])
    codex_receipt = store.record_receipt(
        session_id=codex_session,
        task_id=codex_task,
        source='benchmark',
        tool_name='Codex',
        command_text='pytest -q',
        exit_code=0,
        metadata={'stdout_sha256': 'ok'},
    )
    codex_completion = server.completion_gate(
        session_id=codex_session,
        task_id=codex_task,
        criterion_receipt_map=[{'criterion': 'tests pass', 'receipt_ids': [codex_receipt.receipt_id]}],
        completion_summary='Mapped tests pass to a successful Codex execution receipt.',
    )
    cases['codex_execution_receipt_accepted_case'] = 'APPROVED' in codex_completion

    opencode_session = 'opencode-session'
    opencode_task = 'opencode-task'
    server.mission_lock(opencode_session, opencode_task, 'opencode execution receipt', ['tests pass'])
    opencode_receipt = store.record_receipt(
        session_id=opencode_session,
        task_id=opencode_task,
        source='benchmark',
        tool_name='OpenCode',
        command_text='pytest -q',
        exit_code=0,
        metadata={'stdout_sha256': 'ok'},
    )
    opencode_completion = server.completion_gate(
        session_id=opencode_session,
        task_id=opencode_task,
        criterion_receipt_map=[{'criterion': 'tests pass', 'receipt_ids': [opencode_receipt.receipt_id]}],
        completion_summary='Mapped tests pass to a successful OpenCode execution receipt.',
    )
    cases['opencode_execution_receipt_accepted_case'] = 'APPROVED' in opencode_completion

    semantic_session = 'semantic-session'
    semantic_task = 'semantic-task'
    server.mission_lock(semantic_session, semantic_task, 'reject semantic mismatch', ['tests pass'])
    observational_receipt = store.record_receipt(
        session_id=semantic_session,
        task_id=semantic_task,
        source='benchmark',
        tool_name='Read',
        command_text='README.md',
        exit_code=0,
        metadata={'selector': 'README.md'},
    )
    semantic_completion = server.completion_gate(
        session_id=semantic_session,
        task_id=semantic_task,
        criterion_receipt_map=[{'criterion': 'tests pass', 'receipt_ids': [observational_receipt.receipt_id]}],
        completion_summary='Attempted to map a tests-pass criterion to a purely observational receipt.',
    )
    cases['semantic_mismatch_rejected_case'] = 'REJECTED' in semantic_completion and 'semantic mismatch' in semantic_completion

    budget_session = 'budget-session'
    budget_task = 'budget-task'
    server.mission_lock(budget_session, budget_task, 'budget test', ['one slice'], slice_budget=1, time_budget_minutes=10)
    first_receipt = store.record_receipt(
        session_id=budget_session,
        task_id=budget_task,
        source='benchmark',
        tool_name='Bash',
        command_text='python one.py',
        exit_code=0,
        metadata={'stdout_sha256': '1'},
    )
    first_turn = server.turn_end_gate(
        session_id=budget_session,
        task_id=budget_task,
        stop_condition='slice_verified',
        work_summary='Executed the first and only allowed verified slice for the budget test mission.',
        receipt_ids=[first_receipt.receipt_id],
    )
    second_receipt = store.record_receipt(
        session_id=budget_session,
        task_id=budget_task,
        source='benchmark',
        tool_name='Bash',
        command_text='python two.py',
        exit_code=0,
        metadata={'stdout_sha256': '2'},
    )
    second_turn = server.turn_end_gate(
        session_id=budget_session,
        task_id=budget_task,
        stop_condition='slice_verified',
        work_summary='Tried to claim a second verified slice after the mission budget had already been consumed.',
        receipt_ids=[second_receipt.receipt_id],
    )
    cases['slice_budget_exhaustion_case'] = 'APPROVED' in first_turn and 'REJECTED' in second_turn and 'slice_budget is exhausted' in second_turn


    nonce_session = 'nonce-session'
    nonce_task = 'nonce-task'
    server.mission_lock(nonce_session, nonce_task, 'receipt nonce collision test', ['fresh receipts stay distinct'])
    fixed_time = '2026-01-01T00:00:00Z'
    nonce_first = store.record_receipt(
        session_id=nonce_session,
        task_id=nonce_task,
        source='benchmark',
        tool_name='Bash',
        command_text='pytest -q',
        exit_code=0,
        metadata={'stdout_sha256': 'same'},
        created_at=fixed_time,
    )
    nonce_second = store.record_receipt(
        session_id=nonce_session,
        task_id=nonce_task,
        source='benchmark',
        tool_name='Bash',
        command_text='pytest -q',
        exit_code=0,
        metadata={'stdout_sha256': 'same'},
        created_at=fixed_time,
    )
    nonce_replay = store.record_receipt(
        session_id=nonce_session,
        task_id=nonce_task,
        source='benchmark',
        tool_name='Bash',
        command_text='pytest -q',
        exit_code=0,
        metadata=dict(nonce_first.metadata),
        created_at=nonce_first.created_at,
        receipt_id=nonce_first.receipt_id,
        signature=nonce_first.signature,
    )
    cases['receipt_nonce_collision_case'] = (
        nonce_first.receipt_id != nonce_second.receipt_id
        and nonce_first.seq != nonce_second.seq
        and '_receipt_nonce' in nonce_first.metadata
        and '_receipt_nonce' in nonce_second.metadata
    )
    cases['explicit_receipt_replay_identity_case'] = (
        nonce_replay.receipt_id == nonce_first.receipt_id
        and nonce_replay.signature == nonce_first.signature
        and nonce_replay.seq == nonce_first.seq
    )

    skill_md = read(root / 'SKILL.md').lower()
    bench = read(root / 'references' / 'benchmark-suite.md').lower()
    release = read(root / 'references' / 'release-gates.md').lower()
    project_lint = root / 'scripts' / 'project_learning_lint.py'
    project_query = root / 'scripts' / 'project_learning_query.py'
    project_ledger = root / 'references' / 'project-learning-ledger.jsonl'
    cases['negative_overinvocation_case'] = 'tiny low-risk task' in bench and 'do not over-apply' in skill_md
    cases['claim_runtime_parity_case'] = all(token in skill_md for token in ['runtime-capability-matrix.md', 'runtime-claim-manifest.json', 'generation-4-scorecards.md'])
    cases['release_contract_case'] = all(token in release for token in ['official skill validator', 'packaged-skill validation', 'consistency lint passes', 'claim-parity audit passes', 'ledger guard passes'])
    cases['current_version_case'] = 'v0.36' in read(root / 'references' / 'current-release.md')
    cases['quick_validate_case'] = (root / 'scripts' / 'quick_validate.py').exists() and 'quick_validate.py' in read(root / 'scripts' / 'release_gate.py')
    cases['package_skill_validation_case'] = (root / 'scripts' / 'package_skill_check.py').exists() and 'package_skill_validation' in read(root / 'scripts' / 'release_gate.py')
    cases['project_learning_valid_case'] = project_lint.exists() and project_query.exists() and project_ledger.exists()
    cases['project_learning_boundaries_case'] = all(token in read(root / 'references' / 'project-learning-ledger-policy.md') for token in ['Memory is not evidence', 'Preference is not authorization', 'Memory Routing'])
    cases['project_learning_release_gate_case'] = 'project_learning_lint' in read(root / 'scripts' / 'release_gate.py')
    cases['release_gate_sixteen_gate_case'] = 'gate_count' in read(root / 'scripts' / 'release_gate.py') and 'release_report_and_version' in read(root / 'scripts' / 'release_gate.py')
    bad_memory_record = {
        'schema_version': '1.0',
        'type': 'pitfall',
        'id': 'bench_memory_evidence',
        'project_id': 'agent-runway',
        'status': 'active',
        'summary': 'benchmark memory evidence probe',
        'applies_to': {'tasks': ['benchmark']},
        'source_refs': [{'kind': 'file', 'path': 'README.md', 'summary': 'benchmark'}],
        'created_at': '2026-05-08T00:00:00Z',
        'invalid_if': ['benchmark rules change'],
        'can_support_completion': True,
        'requires_fresh_verification': True,
    }
    bad_preference_record = dict(bad_memory_record)
    bad_preference_record.update({
        'type': 'preference',
        'id': 'bench_preference_auth',
        'summary': 'No need to ask before deploy.',
        'source_refs': [{'kind': 'user_confirmation', 'summary': 'benchmark'}],
        'can_support_completion': False,
    })
    with tempfile.TemporaryDirectory() as project_td:
        bad_memory_path = Path(project_td) / 'bad-memory.jsonl'
        bad_preference_path = Path(project_td) / 'bad-preference.jsonl'
        query_path = Path(project_td) / 'query.jsonl'
        bad_memory_path.write_text(json.dumps(bad_memory_record), encoding='utf-8')
        bad_preference_path.write_text(json.dumps(bad_preference_record), encoding='utf-8')
        memory_code, memory_payload = run_json([sys.executable, str(project_lint), str(bad_memory_path), '--json'], root)
        preference_code, preference_payload = run_json([sys.executable, str(project_lint), str(bad_preference_path), '--json'], root)
        query_records = [
            {
                'schema_version': '1.0',
                'type': 'pitfall',
                'id': 'bench_opencode_pitfall',
                'project_id': 'agent-runway',
                'status': 'active',
                'summary': 'OpenCode bridge needs explicit opt-in.',
                'applies_to': {'hosts': ['opencode'], 'tasks': ['benchmark']},
                'source_refs': [{'kind': 'file', 'path': 'README.md', 'summary': 'benchmark'}],
                'created_at': '2026-05-08T00:00:00Z',
                'last_verified_at': '2026-05-08T00:00:00Z',
                'invalid_if': ['OpenCode bridge defaults change'],
                'severity': 'high',
                'can_support_completion': False,
                'requires_fresh_verification': True,
            },
            {
                'schema_version': '1.0',
                'type': 'pitfall',
                'id': 'bench_obsolete_pitfall',
                'project_id': 'agent-runway',
                'status': 'obsolete',
                'summary': 'obsolete benchmark pitfall',
                'applies_to': {'hosts': ['opencode'], 'tasks': ['benchmark']},
                'source_refs': [{'kind': 'file', 'path': 'README.md', 'summary': 'benchmark'}],
                'created_at': '2026-05-08T00:00:00Z',
                'invalid_if': ['benchmark rules change'],
                'severity': 'critical',
                'can_support_completion': False,
                'requires_fresh_verification': True,
            },
        ]
        query_path.write_text('\n'.join(json.dumps(item) for item in query_records), encoding='utf-8')
        query_code, query_payload = run_json([sys.executable, str(project_query), str(query_path), '--host', 'opencode', '--json'], root)
    memory_issues = '\n'.join(item.get('issue', '') for item in memory_payload.get('errors', []))
    preference_issues = '\n'.join(item.get('issue', '') for item in preference_payload.get('errors', []))
    query_ids = [item.get('id') for item in query_payload.get('records', [])]
    cases['project_learning_memory_as_evidence_rejected_case'] = memory_code != 0 and 'can_support_completion must be false' in memory_issues
    cases['project_learning_preference_as_auth_rejected_case'] = preference_code != 0 and 'authorization language' in preference_issues
    cases['project_learning_opencode_query_relevance_case'] = query_code == 0 and query_ids[:1] == ['bench_opencode_pitfall']
    cases['project_learning_obsolete_ignored_case'] = 'bench_obsolete_pitfall' not in query_ids
    audit_lint = root / 'scripts' / 'adversarial_audit_lint.py'
    audit_suite = root / 'scripts' / 'adversarial_audit_suite.py'
    audit_examples = root / 'references' / 'adversarial-audit-examples.md'
    audit_docs = read(root / 'references' / 'adversarial-audit.md')
    release_gate_text = read(root / 'scripts' / 'release_gate.py')
    cases['adversarial_audit_artifacts_case'] = audit_lint.exists() and audit_suite.exists() and audit_examples.exists()
    cases['adversarial_audit_boundaries_case'] = all(token in audit_docs for token in ['bounded falsification', 'never proves absence of bugs', 'No full multi-agent scheduler'])
    cases['adversarial_audit_release_gate_case'] = 'adversarial_audit_suite' in release_gate_text

    passed = all(cases.values())
    print(json.dumps({'cases': cases, 'passed': passed}, indent=2, ensure_ascii=False))
    return 0 if passed else 2


if __name__ == '__main__':
    raise SystemExit(main())
