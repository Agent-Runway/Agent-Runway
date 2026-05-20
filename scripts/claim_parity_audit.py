#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


SERVER_TOOL_RE = re.compile(r'^def\s+([a-zA-Z_][a-zA-Z0-9_]*)\(', re.MULTILINE)


def read(path: Path) -> str:
    return path.read_text(encoding='utf-8') if path.exists() else ''


def parse_functions(path: Path) -> set[str]:
    return set(SERVER_TOOL_RE.findall(read(path)))


def claim_hook_functions(root: Path, claim: dict) -> set[str]:
    candidate_paths: list[Path] = []
    for rel in [*claim.get('required_files', []), *claim.get('required_scripts', [])]:
        path = root / rel
        if path.suffix == '.py':
            candidate_paths.append(path)
    if not candidate_paths:
        candidate_paths.append(root / 'scripts' / 'claude_hooks.py')

    hooks: set[str] = set()
    for path in candidate_paths:
        hooks.update(parse_functions(path))
    return hooks


def declared_modes_in_matrix(matrix_text: str) -> set[str]:
    declared: set[str] = set()
    for line in matrix_text.splitlines():
        stripped = line.strip().lower()
        if not stripped.startswith('|'):
            continue
        cells = [cell.strip() for cell in stripped.strip('|').split('|')]
        if 'capability' not in cells:
            continue
        for cell in cells:
            if cell.endswith('mode'):
                declared.add(cell.replace(' mode', ''))
    return declared


def main() -> int:
    if len(sys.argv) != 2:
        print('usage: python scripts/claim_parity_audit.py <skill-root>')
        return 1
    root = Path(sys.argv[1]).resolve()
    manifest = json.loads(read(root / 'references' / 'runtime-claim-manifest.json'))
    server_tools = parse_functions(root / 'mcp' / 'server.py')

    results = []
    passed = True
    matrix_text = read(root / 'references' / 'runtime-capability-matrix.md').lower()
    declared_modes = declared_modes_in_matrix(matrix_text)
    for claim in manifest.get('claims', []):
        claim_id = claim['id']
        missing_files = [rel for rel in claim.get('required_files', []) if not (root / rel).exists()]
        missing_tools = [name for name in claim.get('required_tools', []) if name not in server_tools]
        missing_scripts = [rel for rel in claim.get('required_scripts', []) if not (root / rel).exists()]
        hook_functions = claim_hook_functions(root, claim)
        missing_hooks = [name for name in claim.get('required_hooks', []) if name not in hook_functions]
        mode_ok = claim.get('min_mode', 'soft') in declared_modes
        ok = not (missing_files or missing_tools or missing_scripts or missing_hooks) and mode_ok
        passed = passed and ok
        results.append({
            'id': claim_id,
            'enforcement': claim.get('enforcement'),
            'min_mode': claim.get('min_mode'),
            'passed': ok,
            'missing_files': missing_files,
            'missing_tools': missing_tools,
            'missing_scripts': missing_scripts,
            'missing_hooks': missing_hooks,
            'mode_declared_in_matrix': mode_ok,
        })

    payload = {'claim_count': len(results), 'results': results, 'passed': passed}
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if passed else 2


if __name__ == '__main__':
    raise SystemExit(main())
