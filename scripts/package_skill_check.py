#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from release_files import is_release_excluded


def run_cmd(cmd: list[str], cwd: Path | None = None, timeout: int = 120) -> dict:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=timeout,
        check=False,
    )
    return {"cmd": cmd, "returncode": proc.returncode, "output": proc.stdout.strip()}


def should_include(path: Path) -> bool:
    return not is_release_excluded(path, Path("."))


def create_internal_package(root: Path, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    archive = out_dir / "skill.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for file_path in sorted(root.rglob("*")):
            rel = file_path.relative_to(root)
            if should_include(rel) and file_path.is_file():
                zf.write(file_path, Path(root.name) / rel)
    return archive


def find_single_skill_root(extracted: Path) -> Path:
    skill_files = list(extracted.rglob("SKILL.md"))
    if len(skill_files) != 1:
        raise ValueError(f"expected exactly one SKILL.md in package, found {len(skill_files)}")
    return skill_files[0].parent


def official_package_script() -> Path | None:
    candidates = []
    env_value = os.environ.get("SKILL_CREATOR_PACKAGE_SCRIPT")
    if env_value:
        candidates.append(Path(env_value).expanduser())
    candidates.extend([
        Path("/home/oai/skills/skill-creator/scripts/package_skill.py"),
        Path.home() / ".local" / "share" / "openai" / "skills" / "skill-creator" / "scripts" / "package_skill.py",
    ])
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python scripts/package_skill_check.py <skill-root>")
        return 1
    root = Path(sys.argv[1]).resolve()
    quick_validate = root / "scripts" / "quick_validate.py"
    results: dict[str, object] = {"skill_root": str(root)}

    quick = run_cmd([sys.executable, str(quick_validate), str(root)], cwd=root)
    results["quick_validate_before_package"] = quick
    if quick["returncode"] != 0:
        results["passed"] = False
        print(json.dumps(results, indent=2, ensure_ascii=False))
        return 2

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        package_dir = td_path / "package"
        archive = create_internal_package(root, package_dir)
        results["internal_package"] = {
            "path_name": archive.name,
            "exists": archive.exists(),
            "size_bytes": archive.stat().st_size if archive.exists() else 0,
        }
        extract_dir = td_path / "extract"
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(extract_dir)
        extracted_root = find_single_skill_root(extract_dir)
        quick_after = run_cmd([sys.executable, str(quick_validate), str(extracted_root)], cwd=extracted_root)
        results["quick_validate_after_internal_package"] = quick_after

        official = official_package_script()
        results["official_package_script"] = str(official) if official else None
        if official is not None:
            official_out = td_path / "official"
            official_out.mkdir()
            official_run = run_cmd([sys.executable, str(official), str(root), str(official_out)], cwd=root, timeout=180)
            official_zip = official_out / "skill.zip"
            results["official_package_skill"] = {
                "available": True,
                "returncode": official_run["returncode"],
                "output": official_run["output"],
                "skill_zip_exists": official_zip.exists(),
                "skill_zip_size_bytes": official_zip.stat().st_size if official_zip.exists() else 0,
            }
        else:
            results["official_package_skill"] = {
                "available": False,
                "returncode": 0,
                "output": "official package_skill.py not available; self-contained package validation was used",
                "skill_zip_exists": False,
                "skill_zip_size_bytes": 0,
            }

    package_ok = bool(results["internal_package"]["exists"]) and results["internal_package"]["path_name"] == "skill.zip"
    official_result = results["official_package_skill"]
    passed = (
        quick["returncode"] == 0
        and package_ok
        and results["quick_validate_after_internal_package"]["returncode"] == 0
        and official_result["returncode"] == 0
    )
    results["official_package_validated"] = bool(official_result.get("available")) and official_result["returncode"] == 0
    results["passed"] = passed
    print(json.dumps(results, indent=2, ensure_ascii=False))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
