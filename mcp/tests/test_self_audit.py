from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


class SelfAuditTestCase(unittest.TestCase):
    def test_self_audit_accepts_current_host_mode_names(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "self_audit.py"), str(REPO_ROOT)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )

        payload = json.loads(proc.stdout)
        self.assertEqual(proc.returncode, 0)
        self.assertTrue(payload["passed"])
        self.assertEqual(payload["scores"]["degradation_resilience"], 9.5)


if __name__ == "__main__":
    unittest.main()
