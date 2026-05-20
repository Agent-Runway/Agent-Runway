#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path

EXCLUDED_DIR_NAMES = frozenset(
    {
        ".git",
        ".agent-runway",
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
        "archive",
    }
)
FORBIDDEN_RELEASE_FILE_NAMES = frozenset({"bug_report.md"})
EXCLUDED_FILE_NAMES = frozenset(
    {
        ".DS_Store",
        "Thumbs.db",
        "AGENTS.md",
        "agent-runway-rename-evaluation TO DO list.csv",
        *FORBIDDEN_RELEASE_FILE_NAMES,
    }
)
EXCLUDED_SUFFIXES = frozenset({".pyc", ".pyd", ".pyo"})
ALLOWED_DOT_DIRS = frozenset({".claude", ".opencode"})


def is_release_excluded(path: Path, root: Path) -> bool:
    """Return True when a path is not part of the published skill root."""
    try:
        rel_path = path.relative_to(root)
    except ValueError:
        rel_path = path
    if path.name in EXCLUDED_FILE_NAMES or path.suffix in EXCLUDED_SUFFIXES:
        return True
    if path.name.endswith(" TO DO list.csv"):
        return True
    for part in rel_path.parts:
        if part in EXCLUDED_DIR_NAMES:
            return True
        if part.startswith(".") and part not in ALLOWED_DOT_DIRS:
            return True
    return False


def collect_release_files(root: Path) -> list[Path]:
    """Return sorted relative file paths included in the published skill root."""
    files: list[Path] = []
    for current, dirs, names in os.walk(root):
        current_path = Path(current)
        dirs[:] = [name for name in dirs if not is_release_excluded(current_path / name, root)]
        for name in names:
            path = current_path / name
            if not is_release_excluded(path, root):
                files.append(path.relative_to(root))
    return sorted(files)


def find_forbidden_release_files(root: Path) -> list[Path]:
    """Return release-forbidden files that physically exist under root."""
    files: list[Path] = []
    for current, dirs, names in os.walk(root):
        current_path = Path(current)
        dirs[:] = [name for name in dirs if name not in EXCLUDED_DIR_NAMES]
        for name in names:
            if name in FORBIDDEN_RELEASE_FILE_NAMES:
                files.append((current_path / name).relative_to(root))
    return sorted(files)


def is_forbidden_release_file(path: Path) -> bool:
    """Return True for files that must be absent from release mirrors."""
    return path.name in FORBIDDEN_RELEASE_FILE_NAMES
