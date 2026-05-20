#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

MARKDOWN_LINK_RE = re.compile(r'\[[^\]]+\]\(([^)]+)\)')
REFERENCE_NEEDLES = [
    'runtime-capability-matrix.md',
    'runtime-claim-manifest.json',
    'generation-4-scorecards.md',
    'current-release.md',
    'project-learning-ledger-policy.md',
    'adversarial-audit.md',
]


def read(path: Path) -> str:
    return path.read_text(encoding='utf-8') if path.exists() else ''


def parse_server_tools(server_text: str) -> set[str]:
    return set(re.findall(r'^def\s+([a-zA-Z_][a-zA-Z0-9_]*)\(', server_text, flags=re.MULTILINE))


def parse_hook_functions(hook_text: str) -> set[str]:
    return set(re.findall(r'^def\s+([a-zA-Z_][a-zA-Z0-9_]*)\(', hook_text, flags=re.MULTILINE))


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
        hooks.update(parse_hook_functions(read(path)))
    return hooks


def resolve_links(root: Path, path: Path) -> list[str]:
    failures: list[str] = []
    for link in MARKDOWN_LINK_RE.findall(read(path)):
        if '://' in link or link.startswith('mailto:') or link.startswith('#'):
            continue
        target = (path.parent / link).resolve()
        try:
            target.relative_to(root.resolve())
        except ValueError:
            failures.append(f'{path.relative_to(root)} -> {link} escapes skill root')
            continue
        if not target.exists():
            failures.append(f'{path.relative_to(root)} -> {link} missing')
    return failures


def validate_project_learning_contract(root: Path, issues: list[str]) -> None:
    required = [
        'references/project-learning-ledger.jsonl',
        'references/project-learning-ledger.schema.json',
        'references/project-learning-ledger-policy.md',
        'scripts/project_learning_lint.py',
        'scripts/project_learning_query.py',
    ]
    for rel in required:
        if not (root / rel).exists():
            issues.append(f'project learning artifact missing: {rel}')
    policy = read(root / 'references' / 'project-learning-ledger-policy.md')
    for phrase in ['Memory is not evidence', 'Preference is not authorization', 'Memory Routing', 'Non-Goals', 'Threat Model']:
        if phrase not in policy:
            issues.append(f'project learning policy missing phrase: {phrase}')
    server_text = read(root / 'mcp' / 'server.py')
    for forbidden in ['def record_project_learning', 'def query_project_learning']:
        if forbidden in server_text:
            issues.append(f'mcp server must not expose {forbidden}')
    readme = read(root / 'README.md').lower() + read(root / 'README_cn.md').lower()
    if 'project learning ledger' not in readme:
        issues.append('readme missing Project Learning Ledger terminology')
    if 'project pitfall ledger' in readme:
        issues.append('readme uses deprecated Project Pitfall Ledger terminology')
    for forbidden in ['completion evidence via project learning', 'runtime-enforced memory', 'rag-backed memory']:
        if forbidden in readme:
            issues.append(f'readme overclaims project learning: {forbidden}')
    if 'project learning ledger is a global memory authority' in readme or 'project learning ledger 是全局记忆权威' in readme:
        issues.append('readme overclaims project learning: global memory authority')
    if 'chroma' in readme or 'faiss' in readme:
        issues.append('readme introduces vector-store terminology outside documented non-goals')
    misleading_opencode_bridge = [
        'set `ilh_opencode_bridge=1` in the generated `mcp.agent-runway.environment` block',
        'change `ilh_opencode_bridge` from `"0"` to `"1"` inside the generated `mcp.agent-runway.environment` block',
        '把生成配置里 `mcp.agent-runway.environment` 下的 `ilh_opencode_bridge` 从 `"0"` 改成 `"1"`',
    ]
    for phrase in misleading_opencode_bridge:
        if phrase in readme:
            issues.append('readme preserves the old misleading ILH_OPENCODE_BRIDGE MCP-environment-only guidance')
            break
    required_opencode_bridge_guidance = [
        '.opencode/plugins/',
        '~/.config/opencode/plugins/',
        '%userprofile%\\.config\\opencode\\plugins\\',
        'shim',
    ]
    for phrase in required_opencode_bridge_guidance:
        if phrase not in readme:
            issues.append(f'readme missing OpenCode bridge discovery guidance: {phrase}')
    skill = read(root / 'SKILL.md').lower()
    if 'project learning ledger' not in skill:
        issues.append('SKILL.md missing Project Learning Ledger terminology')
    if 'project pitfall ledger' in skill:
        issues.append('SKILL.md uses deprecated Project Pitfall Ledger terminology')
    for deferred in ['read-only mcp query', 'controlled mcp write tools', 'sqlite index cache', 'markdown export', 'cross-project import']:
        if deferred not in policy.lower():
            issues.append(f'project learning future-work missing deferred item: {deferred}')
    examples = read(root / 'references' / 'examples.md')
    for phrase in ['Example 3: project learning ledger JSONL snippets', '`pitfall`', '`runbook`', '`preference`', '`invariant`']:
        if phrase not in examples:
            issues.append(f'references/examples.md missing phrase: {phrase}')


def validate_adversarial_audit_contract(root: Path, issues: list[str]) -> None:
    required = [
        'references/adversarial-audit.md',
        'references/adversarial-audit-rubric.md',
        'references/adversarial-audit-threat-model.md',
        'references/adversarial-audit-schema.json',
        'references/adversarial-audit-examples.md',
        'references/adversarial-audit-profiles.json',
        'scripts/adversarial_audit_lint.py',
        'scripts/adversarial_audit_suite.py',
        'mcp/tests/test_adversarial_audit.py',
    ]
    for rel in required:
        if not (root / rel).exists():
            issues.append(f'adversarial audit artifact missing: {rel}')
    docs = read(root / 'references' / 'adversarial-audit.md')
    for phrase in ['bounded falsification', 'never proves absence of bugs', 'No full multi-agent scheduler']:
        if phrase not in docs:
            issues.append(f'adversarial audit docs missing phrase: {phrase}')
    release_gate = read(root / 'scripts' / 'release_gate.py')
    if 'adversarial_audit_suite' not in release_gate:
        issues.append('release gate missing adversarial_audit_suite')
    readme_text = (read(root / 'README.md') + read(root / 'README_cn.md')).lower()
    for forbidden in ['proved safe', 'all vulnerabilities eliminated', 'guaranteed secure', '证明安全', '不存在漏洞']:
        if forbidden in readme_text:
            issues.append(f'readme overclaims adversarial audit: {forbidden}')


def main() -> int:
    if len(sys.argv) != 2:
        print('usage: python scripts/consistency_lint.py <skill-root>')
        return 1
    root = Path(sys.argv[1]).resolve()
    issues: list[str] = []

    markdown_files = [root / 'SKILL.md', root / 'mcp' / 'README.md', *sorted((root / 'references').glob('*.md'))]
    for path in markdown_files:
        if path.exists():
            issues.extend(resolve_links(root, path))

    skill_md = read(root / 'SKILL.md')
    for needle in REFERENCE_NEEDLES:
        if needle not in skill_md:
            issues.append(f'SKILL.md does not mention {needle}')

    release_text = read(root / 'references' / 'release-gates.md').lower()
    for phrase in ['consistency lint', 'claim-parity audit', 'ledger guard', 'package validation gate', 'project_learning_lint', 'adversarial_audit_suite']:
        if phrase not in release_text:
            issues.append(f'references/release-gates.md missing phrase: {phrase}')


    release_gate_script = read(root / 'scripts' / 'release_gate.py')
    release_gate_markers = [
        'scripts/consistency_lint.py',
        'scripts/claim_parity_audit.py',
        'scripts/project_learning_lint.py',
        'scripts/adversarial_audit_suite.py',
        'scripts/ledger_guard.py',
        'scripts/package_skill_check.py',
        'scripts/release_static_checks.py',
    ]
    for needle in release_gate_markers:
        if needle not in release_gate_script:
            issues.append(f'scripts/release_gate.py missing gate invocation: {needle}')

    quickstart_text = read(root / 'references' / 'quickstart.md').lower()
    for phrase in ['consistency lint', 'claim-parity audit', 'project learning lint', 'adversarial audit suite', 'ledger guard', 'package validation gate']:
        if phrase not in quickstart_text:
            issues.append(f'references/quickstart.md missing phrase: {phrase}')

    current_release_text = read(root / 'references' / 'current-release.md').lower()
    if 'v0.36' not in current_release_text:
        issues.append('references/current-release.md missing v0.36 marker')
    for phrase in ['16-gate', 'package_skill_validation', 'project_learning_lint', 'adversarial_audit_suite', 'receipt nonce']:
        if phrase not in current_release_text:
            issues.append(f'references/current-release.md missing phrase: {phrase}')

    validate_project_learning_contract(root, issues)
    validate_adversarial_audit_contract(root, issues)

    server_tools = parse_server_tools(read(root / 'mcp' / 'server.py'))
    manifest_path = root / 'references' / 'runtime-claim-manifest.json'
    if not manifest_path.exists():
        issues.append('references/runtime-claim-manifest.json missing')
    else:
        manifest = json.loads(read(manifest_path))
        for claim in manifest.get('claims', []):
            claim_id = claim.get('id', 'unknown-claim')
            hooks = claim_hook_functions(root, claim)
            for rel in claim.get('required_files', []):
                if not (root / rel).exists():
                    issues.append(f'claim {claim_id} references missing file: {rel}')
            for tool in claim.get('required_tools', []):
                if tool not in server_tools:
                    issues.append(f'claim {claim_id} references missing tool: {tool}')
            for hook in claim.get('required_hooks', []):
                if hook not in hooks:
                    issues.append(f'claim {claim_id} references missing hook: {hook}')

    payload = {'issues': issues, 'passed': not issues}
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if payload['passed'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
