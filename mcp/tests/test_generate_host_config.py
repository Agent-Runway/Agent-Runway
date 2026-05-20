from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


class GenerateHostConfigTestCase(unittest.TestCase):
    def test_pi_cli_config_is_extension_only_without_mcp_or_stop_parity(self) -> None:
        script = REPO_ROOT / "scripts" / "generate_host_config.py"
        proc = subprocess.run(
            [sys.executable, str(script), "--host", "pi-cli", "--project-dir", str(REPO_ROOT)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )

        self.assertEqual(proc.returncode, 0, proc.stdout)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["mode"], "extension_only")
        self.assertEqual(payload["host"], "pi-cli")
        self.assertEqual(payload["host_display_name"], "Pi CLI")
        self.assertIn("tool_call", payload["note"])
        self.assertIn("not native MCP", payload["note"])
        self.assertIn("no Stop hook parity", payload["note"])
        self.assertNotIn("mcp", payload)
        self.assertNotIn("env", payload)
        self.assertNotIn("hooks", payload)


if __name__ == "__main__":
    unittest.main()
