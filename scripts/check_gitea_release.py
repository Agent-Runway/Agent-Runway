#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from release_files import collect_release_files, find_forbidden_release_files, is_release_excluded

DEFAULT_GITEA_URL = "http://10.0.1.17:3003/yeats/Agent-Runway.git"


def is_probably_text(data: bytes) -> bool:
    if b"\0" in data:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def get_file_hash(path: Path) -> str:
    with path.open("rb") as handle:
        data = handle.read()
    if is_probably_text(data):
        normalized = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        return hashlib.sha256(normalized).hexdigest()
    return hashlib.sha256(data).hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare release root with Gitea")
    parser.add_argument("--source", type=Path)
    parser.add_argument("--gitea-url", default=DEFAULT_GITEA_URL)
    parser.add_argument("--proxy", default="")
    parser.add_argument("--no-proxy", action="store_true")
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


def collect_files(root: Path) -> dict[Path, str]:
    return {rel_path: get_file_hash(root / rel_path) for rel_path in collect_release_files(root)}


def find_non_release_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel_path = path.relative_to(root)
        if ".git" in rel_path.parts:
            continue
        if is_release_excluded(path, root):
            files.append(rel_path)
    return sorted(files)


def clone_gitea_repo(url: str, dest: Path, proxy: str) -> bool:
    env = os.environ.copy()
    if proxy:
        env.update({"ALL_PROXY": proxy, "HTTPS_PROXY": proxy, "HTTP_PROXY": proxy})
    result = subprocess.run(
        ["git", "clone", "--depth", "1", url, str(dest)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    if result.returncode == 0:
        return True
    print(f"Error cloning repository: {result.stderr}", file=sys.stderr)
    return False


def compare_files(source: Path, gitea: Path) -> dict[str, list[Path]]:
    source_files = collect_files(source)
    gitea_files = collect_files(gitea)
    common = set(source_files) & set(gitea_files)
    return {
        "only_in_source": sorted(set(source_files) - set(gitea_files)),
        "only_in_gitea": sorted(set(gitea_files) - set(source_files)),
        "modified": sorted(path for path in common if source_files[path] != gitea_files[path]),
        "non_release_in_gitea": find_non_release_files(gitea),
        "forbidden_in_source": find_forbidden_release_files(source),
        "forbidden_in_gitea": find_forbidden_release_files(gitea),
    }


def print_group(title: str, prefix: str, items: list[Path]) -> bool:
    if not items:
        return False
    print(f"{title} ({len(items)}):")
    for item in items:
        print(f"  [{prefix}] {item}")
    print()
    return True


def print_diff(diff: dict[str, list[Path]]) -> bool:
    has_diff = False
    has_diff |= print_group("Forbidden files in source", "!", diff["forbidden_in_source"])
    has_diff |= print_group("Forbidden files in Gitea", "!", diff["forbidden_in_gitea"])
    has_diff |= print_group("Non-release files in Gitea", "x", diff["non_release_in_gitea"])
    has_diff |= print_group("Files only in source", "+", diff["only_in_source"])
    has_diff |= print_group("Files only in Gitea", "-", diff["only_in_gitea"])
    has_diff |= print_group("Modified files", "M", diff["modified"])
    return has_diff


def main() -> int:
    args = parse_args()
    source = resolve_source(args.source)
    try:
        validate_source(source)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Source: {source}")
    print(f"Gitea: {args.gitea_url}\n")
    with tempfile.TemporaryDirectory() as tmpdir:
        gitea_dir = Path(tmpdir) / "gitea-repo"
        proxy = "" if args.no_proxy else args.proxy
        if not clone_gitea_repo(args.gitea_url, gitea_dir, proxy):
            return 1
        print("Comparing files...\n")
        if not print_diff(compare_files(source, gitea_dir)):
            print("[OK] Source and Gitea are in sync!")
            return 0
    print("[DIFF] Source and Gitea have differences. Sync before release.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
