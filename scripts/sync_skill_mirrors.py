#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
from pathlib import Path

from release_files import collect_release_files, is_forbidden_release_file, is_release_excluded


def get_file_hash(path: Path) -> str:
    sha256 = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def default_mirrors() -> dict[str, Path]:
    home = Path.home()
    return {
        "opencode": home / ".config" / "opencode" / "skills" / "agent-runway",
        "codex": home / ".codex" / "skills" / "agent-runway",
        "claude": home / ".claude" / "skills" / "agent-runway",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync local skill mirrors")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--source", type=Path)
    parser.add_argument("--mirrors", nargs="+", choices=sorted(default_mirrors()))
    return parser.parse_args()


def resolve_source(source_arg: Path | None) -> Path:
    if source_arg is not None:
        return source_arg.resolve()
    return Path(__file__).resolve().parent.parent


def validate_source(source: Path) -> None:
    required = ["SKILL.md", "README.md", "mcp/server.py"]
    missing = [item for item in required if not (source / item).exists()]
    if missing:
        raise ValueError(f"source missing required files: {missing}")


def copy_release_file(source: Path, dest: Path, rel_path: Path, dry_run: bool) -> str | None:
    source_file = source / rel_path
    dest_file = dest / rel_path
    if not dest_file.exists():
        if not dry_run:
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, dest_file)
        return "NEW"
    if get_file_hash(source_file) == get_file_hash(dest_file):
        return None
    if not dry_run:
        shutil.copy2(source_file, dest_file)
    return "UPD"


def delete_stale_files(dest: Path, source_files: set[Path], dry_run: bool) -> int:
    deleted = 0
    if not dest.exists():
        return deleted
    for root, dirs, files in os.walk(dest):
        root_path = Path(root)
        dirs[:] = [name for name in dirs if not is_release_excluded(root_path / name, dest)]
        for name in files:
            file_path = root_path / name
            rel_path = file_path.relative_to(dest)
            if rel_path in source_files:
                continue
            if is_release_excluded(file_path, dest) and not is_forbidden_release_file(file_path):
                continue
            if not dry_run:
                file_path.unlink()
            print(f"  [DEL] {rel_path}")
            deleted += 1
    return deleted


def sync_directory(source: Path, dest: Path, dry_run: bool) -> tuple[int, int, int]:
    copied = updated = 0
    source_files = set(collect_release_files(source))
    for rel_path in source_files:
        action = copy_release_file(source, dest, rel_path, dry_run)
        if action is None:
            continue
        print(f"  [{action}] {rel_path}")
        copied += int(action == "NEW")
        updated += int(action == "UPD")
    deleted = delete_stale_files(dest, source_files, dry_run)
    return copied, updated, deleted


def main() -> int:
    args = parse_args()
    source = resolve_source(args.source)
    try:
        validate_source(source)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    mirrors = default_mirrors()
    if args.mirrors:
        mirrors = {name: mirrors[name] for name in args.mirrors}
    print(f"Source: {source}")
    if args.dry_run:
        print("DRY RUN MODE - no changes will be made")
    totals = [0, 0, 0]
    for name, dest in mirrors.items():
        print(f"\nSyncing to {name}: {dest}")
        result = sync_directory(source, dest, args.dry_run)
        totals = [current + item for current, item in zip(totals, result)]
        if result == (0, 0, 0):
            print("  [OK] Already in sync")
    print(f"\nSummary:\n  Files copied:  {totals[0]}\n  Files updated: {totals[1]}\n  Files deleted: {totals[2]}")
    print("\nDRY RUN - no changes were made." if args.dry_run else "\nSync complete!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
