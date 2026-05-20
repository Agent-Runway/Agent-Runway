#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SUBCHECK_TIMEOUT_SECONDS = 20


def run(cmd: list[str], cwd: Path) -> tuple[int, str, float]:
    started = time.time()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=SUBCHECK_TIMEOUT_SECONDS,
        )
        return proc.returncode, proc.stdout, round(time.time() - started, 3)
    except subprocess.TimeoutExpired as exc:
        output = (exc.stdout or '')
        output += f'\n[TIMEOUT] mutation subcheck exceeded {SUBCHECK_TIMEOUT_SECONDS} seconds'
        return 124, output, round(time.time() - started, 3)


def mutate_remove_consistency_script(root: Path) -> None:
    path = root / 'scripts' / 'consistency_lint.py'
    if path.exists():
        path.unlink()


def mutate_corrupt_manifest_tool(root: Path) -> None:
    path = root / 'references' / 'runtime-claim-manifest.json'
    text = path.read_text(encoding='utf-8').replace('"budget_status"', '"budget_status_removed"', 1)
    path.write_text(text, encoding='utf-8')


def mutate_remove_budget_tool(root: Path) -> None:
    server_path = root / 'mcp' / 'server.py'
    text = server_path.read_text(encoding='utf-8').replace('def budget_status', 'def budget_status_removed')
    server_path.write_text(text, encoding='utf-8')


def mutate_remove_budget_status_from_handoff(root: Path) -> None:
    server_path = root / 'mcp' / 'server.py'
    text = server_path.read_text(encoding='utf-8').replace(
        '"budget_status": _budget_snapshot(session_id, task_scope, mission),',
        '"budget_status_removed": _budget_snapshot(session_id, task_id, mission),',
    )
    server_path.write_text(text, encoding='utf-8')


def mutate_remove_authorization_tool(root: Path) -> None:
    server_path = root / 'mcp' / 'server.py'
    text = server_path.read_text(encoding='utf-8').replace('def record_user_authorization', 'def record_user_authorization_removed')
    server_path.write_text(text, encoding='utf-8')


def mutate_remove_authorization_handoff(root: Path) -> None:
    server_path = root / 'mcp' / 'server.py'
    text = server_path.read_text(encoding='utf-8')
    text = text.replace(
        '"latest_user_authorization": _authorization_payload(',
        '"latest_user_authorization_removed": _authorization_payload(',
        1,
    )
    server_path.write_text(text, encoding='utf-8')


def mutate_remove_generation4_scorecards(root: Path) -> None:
    path = root / 'references' / 'generation-4-scorecards.md'
    if path.exists():
        path.unlink()


def mutate_remove_runtime_matrix(root: Path) -> None:
    path = root / 'references' / 'runtime-capability-matrix.md'
    if path.exists():
        path.unlink()


def mutate_remove_ledger_guard_script(root: Path) -> None:
    path = root / 'scripts' / 'ledger_guard.py'
    if path.exists():
        path.unlink()


def mutate_release_gate_without_parity(root: Path) -> None:
    path = root / 'scripts' / 'release_gate.py'
    text = path.read_text(encoding='utf-8')
    lines = [line for line in text.splitlines(keepends=True) if 'claim_parity_audit' not in line]
    path.write_text(''.join(lines), encoding='utf-8')


def mutate_disable_project_learning_completion_guard(root: Path) -> None:
    path = root / 'scripts' / 'project_learning_lint.py'
    text = path.read_text(encoding='utf-8').replace(
        'if record.get("can_support_completion") is not False:',
        'if False and record.get("can_support_completion") is not False:',
    )
    path.write_text(text, encoding='utf-8')
    write_project_learning_probe(root, {'can_support_completion': True})


def mutate_allow_preference_authorization(root: Path) -> None:
    path = root / 'scripts' / 'project_learning_lint.py'
    text = path.read_text(encoding='utf-8').replace('PREFERENCE_AUTH_PATTERNS = [', 'PREFERENCE_AUTH_PATTERNS = []\n_DISABLED_PATTERNS = [', 1)
    path.write_text(text, encoding='utf-8')
    write_project_learning_probe(root, {'type': 'preference', 'id': 'pref_mutant', 'summary': 'No need to ask before deploy.', 'source_refs': [{'kind': 'user_confirmation', 'summary': 'test'}]})


def mutate_disable_project_secret_scan(root: Path) -> None:
    path = root / 'scripts' / 'project_learning_lint.py'
    text = path.read_text(encoding='utf-8').replace('SECRET_PATTERNS = [', 'SECRET_PATTERNS = []\n_DISABLED_SECRET_PATTERNS = [', 1)
    path.write_text(text, encoding='utf-8')
    write_project_learning_probe(root, {'summary': 'Bearer abcdefghijklmnopqrstuvwxyz123456'})


def mutate_allow_project_learning_duplicate_ids(root: Path) -> None:
    path = root / 'scripts' / 'project_learning_lint.py'
    text = path.read_text(encoding='utf-8').replace(
        'if isinstance(record_id, str) and record_id in seen:',
        'if False and isinstance(record_id, str) and record_id in seen:',
    )
    path.write_text(text, encoding='utf-8')


def mutate_allow_project_learning_unknown_type(root: Path) -> None:
    path = root / 'scripts' / 'project_learning_lint.py'
    text = path.read_text(encoding='utf-8').replace(
        'if record_type not in ALL_TYPES:',
        'if False and record_type not in ALL_TYPES:',
    )
    path.write_text(text, encoding='utf-8')


def mutate_remove_project_learning_gate(root: Path) -> None:
    path = root / 'scripts' / 'release_gate.py'
    lines = [line for line in path.read_text(encoding='utf-8').splitlines(keepends=True) if 'project_learning_lint' not in line and 'project_learning_ledger' not in line]
    path.write_text(''.join(lines), encoding='utf-8')


def mutate_remove_adversarial_audit_gate(root: Path) -> None:
    path = root / 'scripts' / 'release_gate.py'
    lines = [line for line in path.read_text(encoding='utf-8').splitlines(keepends=True) if 'adversarial_audit_suite' not in line]
    path.write_text(''.join(lines), encoding='utf-8')


def mutate_remove_adversarial_audit_lint(root: Path) -> None:
    path = root / 'scripts' / 'adversarial_audit_lint.py'
    if path.exists():
        path.unlink()


def write_project_learning_probe(root: Path, overrides: dict[str, object]) -> None:
    record = {
        'schema_version': '1.0',
        'type': 'pitfall',
        'id': 'pitfall_mutant_probe',
        'project_id': 'agent-runway',
        'status': 'active',
        'summary': 'mutation probe',
        'applies_to': {'tasks': ['mutation']},
        'source_refs': [{'kind': 'file', 'path': 'README.md', 'summary': 'test'}],
        'created_at': '2026-05-08T00:00:00Z',
        'last_verified_at': '2026-05-08T00:00:00Z',
        'invalid_if': ['test changes'],
        'can_support_completion': False,
        'requires_fresh_verification': True,
    }
    record.update(overrides)
    target = root / 'references' / 'project-learning-ledger.jsonl'
    target.write_text(json.dumps(record, ensure_ascii=False), encoding='utf-8')


def command_for(expectation: str, mutant: Path) -> list[str]:
    if expectation == 'audit':
        return [sys.executable, 'scripts/self_audit.py', str(mutant)]
    if expectation == 'parity':
        return [sys.executable, 'scripts/claim_parity_audit.py', str(mutant)]
    if expectation == 'benchmark':
        return [sys.executable, 'scripts/benchmark_suite.py', str(mutant)]
    if expectation == 'ledger':
        return [sys.executable, 'scripts/ledger_guard.py', str(mutant)]
    if expectation == 'project_learning':
        return [sys.executable, '-m', 'unittest', 'discover', '-s', 'mcp/tests', '-p', 'test_project_learning.py']
    return [sys.executable, 'scripts/consistency_lint.py', str(mutant)]


def build_mutants() -> list[tuple[str, object, str]]:
    return [
        ('missing_consistency_script', mutate_remove_consistency_script, 'parity'),
        ('corrupt_manifest_tool', mutate_corrupt_manifest_tool, 'parity'),
        ('missing_budget_tool', mutate_remove_budget_tool, 'benchmark'),
        ('missing_budget_handoff', mutate_remove_budget_status_from_handoff, 'benchmark'),
        ('missing_authorization_tool', mutate_remove_authorization_tool, 'parity'),
        ('missing_authorization_handoff', mutate_remove_authorization_handoff, 'benchmark'),
        ('missing_generation4_scorecards', mutate_remove_generation4_scorecards, 'ledger'),
        ('missing_runtime_matrix', mutate_remove_runtime_matrix, 'consistency'),
        ('missing_ledger_guard_script', mutate_remove_ledger_guard_script, 'parity'),
        ('release_gate_without_parity', mutate_release_gate_without_parity, 'consistency'),
        ('project_learning_completion_guard_removed', mutate_disable_project_learning_completion_guard, 'project_learning'),
        ('project_learning_preference_auth_allowed', mutate_allow_preference_authorization, 'project_learning'),
        ('project_learning_secret_scan_disabled', mutate_disable_project_secret_scan, 'project_learning'),
        ('project_learning_duplicate_ids_allowed', mutate_allow_project_learning_duplicate_ids, 'project_learning'),
        ('project_learning_unknown_type_allowed', mutate_allow_project_learning_unknown_type, 'project_learning'),
        ('project_learning_gate_removed', mutate_remove_project_learning_gate, 'consistency'),
        ('adversarial_audit_gate_removed', mutate_remove_adversarial_audit_gate, 'consistency'),
        ('adversarial_audit_lint_removed', mutate_remove_adversarial_audit_lint, 'parity'),
    ]


def preview(text: str, limit: int = 220) -> str:
    compact = ' | '.join(line.strip() for line in text.strip().splitlines()[:6])
    return compact[:limit]


def main() -> int:
    if len(sys.argv) != 2:
        print('usage: python scripts/adversarial_mutation_suite.py <skill-root>')
        return 1
    root = Path(sys.argv[1]).resolve()
    mutants = build_mutants()

    results: dict[str, dict[str, object]] = {}
    started = time.time()
    with tempfile.TemporaryDirectory() as td:
        temp_root = Path(td)
        for idx, (name, mutator, expectation) in enumerate(mutants, start=1):
            mutant = temp_root / name
            shutil.copytree(root, mutant)
            mutator(mutant)
            cmd = command_for(expectation, mutant)
            print(f'[{idx}/{len(mutants)}] running {name} via {expectation}', flush=True)
            code, output, elapsed = run(cmd, mutant)
            caught = code != 0
            results[name] = {
                'mode': expectation,
                'returncode': code,
                'caught': caught,
                'elapsed_seconds': elapsed,
                'output_preview': preview(output),
                'output': output.strip(),
            }
            status = 'CAUGHT' if caught else 'MISSED'
            print(f'[{idx}/{len(mutants)}] {name}: {status} rc={code} elapsed={elapsed}s', flush=True)

    passed = all(item['caught'] for item in results.values())
    payload = {
        'mutant_count': len(mutants),
        'elapsed_seconds': round(time.time() - started, 3),
        'subcheck_timeout_seconds': SUBCHECK_TIMEOUT_SECONDS,
        'mutants': results,
        'passed': passed,
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if passed else 2


if __name__ == '__main__':
    raise SystemExit(main())
