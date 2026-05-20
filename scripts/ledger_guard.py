#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROUND_RE = re.compile(r'^## Round\s+(\d+):', re.MULTILINE)
ROW_RE = re.compile(r'^\|\s*(\d+\.\d+)\s*\|\s*(.*?)\s*\|\s*(\d+\.\d)\s*\|$', re.MULTILINE)


def read(path: Path) -> str:
    return path.read_text(encoding='utf-8') if path.exists() else ''


def main() -> int:
    if len(sys.argv) != 2:
        print('usage: python scripts/ledger_guard.py <skill-root>')
        return 1
    root = Path(sys.argv[1]).resolve()
    scorecards = read(root / 'references' / 'generation-4-scorecards.md')
    ledger = read(root / 'references' / 'evolution-ledger.md')

    round_numbers = [int(x) for x in ROUND_RE.findall(scorecards)]
    rows = ROW_RE.findall(scorecards)
    per_round: dict[int, int] = {num: 0 for num in round_numbers}
    low_scores = []
    for loop_id, _label, score_text in rows:
        round_num = int(loop_id.split('.')[0])
        per_round[round_num] = per_round.get(round_num, 0) + 1
        if float(score_text) < 9.5:
            low_scores.append({'loop': loop_id, 'score': float(score_text)})

    issues = []
    expected_rounds = list(range(31, 41))
    if round_numbers != expected_rounds:
        issues.append(f'expected rounds {expected_rounds} but found {round_numbers}')
    for num in expected_rounds:
        if per_round.get(num, 0) != 20:
            issues.append(f'round {num} has {per_round.get(num, 0)} rows instead of 20')
    if len(rows) != 200:
        issues.append(f'expected 200 accepted rows but found {len(rows)}')
    if low_scores:
        issues.append(f'found scores below 9.5: {low_scores[:5]}')
    for needle in [
        'Generation 4 accepted micro-optimizations: 200',
        'Total accepted micro-optimizations: 800',
        'Acceptance threshold per micro-optimization: 9.5 / 10',
    ]:
        if needle not in ledger:
            issues.append(f'evolution-ledger.md missing: {needle}')

    payload = {
        'rounds': round_numbers,
        'rows': len(rows),
        'per_round': per_round,
        'issues': issues,
        'passed': not issues,
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if payload['passed'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
