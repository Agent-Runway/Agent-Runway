from __future__ import annotations

import hashlib
import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class HookMemoryEdgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        os.environ["ILH_DB_PATH"] = str(Path(self.temp_dir.name) / "state.db")
        os.environ["ILH_SECRET_PATH"] = str(Path(self.temp_dir.name) / "secret.key")
        repo_root = Path(__file__).resolve().parents[2]
        for path in (repo_root / "mcp", repo_root / "scripts"):
            if str(path) not in sys.path:
                sys.path.insert(0, str(path))
        self.hooks = importlib.reload(importlib.import_module("claude_hooks"))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()
        os.environ.pop("ILH_DB_PATH", None)
        os.environ.pop("ILH_SECRET_PATH", None)

    def test_sha256_file_streams_without_reading_entire_file(self) -> None:
        target = Path(self.temp_dir.name) / "large-edit-output.bin"
        target.write_bytes(b"abc" * 1024)
        expected = hashlib.sha256(b"abc" * 1024).hexdigest()

        with patch.object(Path, "read_bytes", side_effect=AssertionError("read_bytes loads entire file")):
            digest = self.hooks.sha256_file(str(target))

        self.assertEqual(expected, digest)


if __name__ == "__main__":
    unittest.main()
