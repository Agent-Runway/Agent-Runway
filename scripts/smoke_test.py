#!/usr/bin/env python3
from __future__ import annotations

import importlib
import json
import os
import tempfile
from pathlib import Path


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    temp_dir = tempfile.TemporaryDirectory()
    os.environ['ILH_DB_PATH'] = str(Path(temp_dir.name) / 'state.db')
    os.environ['ILH_SECRET_PATH'] = str(Path(temp_dir.name) / 'secret.key')

    import sys
    mcp_root = str(repo_root / 'mcp')
    if mcp_root not in sys.path:
        sys.path.insert(0, mcp_root)

    server = importlib.import_module('server')
    server = importlib.reload(server)
    store = server.store

    session_id = 'smoke-session'
    task_id = 'smoke-task'
    print(server.mission_lock(
        session_id,
        task_id,
        'verify the generation-4 control loop',
        ['gate approves a verified receipt'],
        verification_plan=['record a receipt', 'verify integrity', 'record counterexample', 'record decision'],
        evidence_map=[{'criterion': 'gate approves a verified receipt', 'evidence': ['fresh receipt']}],
        counterexample_required=True,
        decision_records_required=True,
        time_budget_minutes=15,
        risk_budget='local reversible checks only',
    ))
    receipt = store.record_receipt(
        session_id=session_id,
        task_id=task_id,
        source='smoke-test',
        tool_name='Bash',
        command_text='python -m unittest',
        exit_code=0,
        metadata={'stdout_sha256': 'ok'},
    )
    print(server.verify_receipt_integrity(session_id, [receipt.receipt_id], task_id))
    print(server.record_decision_record(
        session_id,
        task_id,
        'use direct receipt verification',
        'verify integrity before gating',
        ['skip integrity check'],
        [receipt.receipt_id],
        'reversible',
        ['integrity mismatch'],
    ))
    print(server.record_counterexample_check(
        session_id,
        task_id,
        'receipt might be malformed',
        ['recompute signature'],
        'signature matched the stored receipt',
        [receipt.receipt_id],
        'host-side provenance still depends on runtime configuration',
    ))
    print(server.turn_end_gate(
        session_id=session_id,
        task_id=task_id,
        stop_condition='slice_verified',
        work_summary='Recorded and verified a fresh receipt, then documented the decision and counterexample result.',
        receipt_ids=[receipt.receipt_id],
    ))
    print(server.completion_gate(
        session_id=session_id,
        task_id=task_id,
        criterion_receipt_map=[{'criterion': 'gate approves a verified receipt', 'receipt_ids': [receipt.receipt_id]}],
        completion_summary='Recorded a fresh receipt, verified its integrity, and satisfied the required decision and counterexample checks.',
        known_risks=['host-side provenance still depends on runtime configuration'],
        unverified_items=['no hosted hook exercised in smoke test'],
    ))
    print(server.budget_status(session_id, task_id))
    handoff = json.loads(server.export_handoff_packet(session_id, task_id))
    print(json.dumps({'handoff_keys': sorted(handoff.keys())}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
