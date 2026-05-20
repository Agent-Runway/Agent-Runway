#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run pre-release checks")
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument("--skip-gitea", action="store_true")
    parser.add_argument("--source", type=Path)
    return parser.parse_args()


def resolve_source(source_arg: Path | None) -> Path:
    if source_arg is not None:
        return source_arg.resolve()
    return Path(__file__).resolve().parent.parent


def run_command(cmd: list[str], cwd: Path, timeout: int) -> tuple[bool, str]:
    try:
        result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, f"Command timed out after {timeout} seconds"
    return result.returncode == 0, result.stdout + result.stderr


def print_section(title: str) -> None:
    print(f"\n{'=' * 70}\n  {title}\n{'=' * 70}\n")


def check_tests(source: Path, skip: bool) -> tuple[str, bool | None]:
    print_section("Check 1: Full Test Suite" + (" [SKIPPED]" if skip else ""))
    if skip:
        return "tests", None
    cmd = [sys.executable, "-m", "unittest", "discover", "-s", "mcp/tests", "-p", "test_*.py"]
    success, output = run_command(cmd, source, 120)
    if success:
        print(next((line for line in output.splitlines() if line.startswith("Ran ")), "tests passed"))
        print("[PASS] All tests passed")
    else:
        print("[FAIL] Tests failed")
        print(output[-500:])
    return "tests", success


def check_smoke(source: Path) -> tuple[str, bool | None]:
    print_section("Check 2: Smoke Test")
    script = source / "scripts" / "smoke_test.py"
    if not script.exists():
        print("[SKIP] Smoke test script not found")
        return "smoke", None
    success, output = run_command([sys.executable, str(script)], source, 30)
    print("[PASS] Smoke test passed" if success else "[FAIL] Smoke test failed")
    if not success:
        print(output[-500:])
    return "smoke", success


def check_mirrors(source: Path) -> tuple[str, bool | None]:
    print_section("Check 3: Skill Mirror Sync Check")
    script = source / "scripts" / "sync_skill_mirrors.py"
    if not script.exists():
        print("[SKIP] Sync script not found")
        return "mirrors", None
    success, output = run_command([sys.executable, str(script), "--dry-run"], source, 30)
    in_sync = all(text in output for text in ("Files copied:  0", "Files updated: 0", "Files deleted: 0"))
    if success and in_sync:
        print("[PASS] All skill mirrors are in sync")
        return "mirrors", True
    print("[WARN] Skill mirrors have differences")
    print("\n".join(line for line in output.splitlines() if "Files " in line))
    return "mirrors", False


def check_gitea(source: Path, skip: bool) -> tuple[str, bool | None]:
    print_section("Check 4: Gitea Release Repository Diff" + (" [SKIPPED]" if skip else ""))
    if skip:
        return "gitea", None
    script = source / "scripts" / "check_gitea_release.py"
    if not script.exists():
        print("[SKIP] Gitea check script not found")
        return "gitea", None
    success, output = run_command([sys.executable, str(script)], source, 60)
    print("[PASS] Source and Gitea are in sync" if success else "[WARN] Source and Gitea differ")
    if not success:
        print(output[-1200:])
    return "gitea", success


def print_summary(results: list[tuple[str, bool | None]]) -> int:
    print_section("Summary")
    passed = sum(result is True for _, result in results)
    failed = sum(result is False for _, result in results)
    skipped = sum(result is None for _, result in results)
    print(f"Total checks: {len(results)}\n  Passed:  {passed}\n  Failed:  {failed}\n  Skipped: {skipped}\n")
    print("[OK] All checks passed! Ready for release." if failed == 0 else "[FAIL] Some checks failed.")
    return 0 if failed == 0 else 1


def main() -> int:
    args = parse_args()
    source = resolve_source(args.source)
    print(f"Source: {source}")
    results = [
        check_tests(source, args.skip_tests),
        check_smoke(source),
        check_mirrors(source),
        check_gitea(source, args.skip_gitea),
    ]
    return print_summary(results)


if __name__ == "__main__":
    sys.exit(main())
