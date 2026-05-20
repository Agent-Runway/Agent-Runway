#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def parse_frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---\n"):
        raise ValueError("SKILL.md must start with YAML frontmatter")
    end = text.find("\n---", 4)
    if end == -1:
        raise ValueError("SKILL.md frontmatter must be closed with ---")
    data: dict[str, str] = {}
    for line in text[4:end].strip().splitlines():
        if not line.strip():
            continue
        if ":" not in line:
            raise ValueError(f"invalid frontmatter line: {line!r}")
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip().strip('"').strip("'")
    return data


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python scripts/quick_validate.py <skill-root>")
        return 1
    root = Path(sys.argv[1]).resolve()
    issues: list[str] = []
    skill_md = root / "SKILL.md"
    if not skill_md.exists():
        issues.append("SKILL.md missing")
    else:
        try:
            data = parse_frontmatter(skill_md.read_text(encoding="utf-8"))
            name = data.get("name", "")
            description = data.get("description", "")
            extra = sorted(set(data) - {"name", "description"})
            if extra:
                issues.append(f"unsupported frontmatter keys: {extra}")
            if not name:
                issues.append("frontmatter name missing")
            elif not NAME_RE.match(name):
                issues.append(f"name {name!r} must be lowercase hyphen-case")
            if not description:
                issues.append("frontmatter description missing")
            elif len(description.split()) < 12:
                issues.append("frontmatter description is too short to explain trigger conditions")
            if description != description.lower():
                issues.append("frontmatter description should be lowercase for trigger metadata consistency")
        except Exception as exc:
            issues.append(str(exc))
    if not (root / "agents" / "openai.yaml").exists():
        issues.append("agents/openai.yaml missing")
    if not (root / "scripts" / "release_gate.py").exists():
        issues.append("scripts/release_gate.py missing")
    payload = {"issues": issues, "passed": not issues}
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if not issues else 2


if __name__ == "__main__":
    raise SystemExit(main())
