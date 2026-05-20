from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


class ClaimParityAuditTestCase(unittest.TestCase):
    def test_claim_parity_fails_when_required_mode_only_appears_in_prose(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "references").mkdir(parents=True)
            (root / "mcp").mkdir(parents=True)
            (root / "scripts").mkdir(parents=True)

            (root / "references" / "runtime-claim-manifest.json").write_text(
                json.dumps(
                    {
                        "claims": [
                            {
                                "id": "hosted-claim",
                                "enforcement": "hook+tests",
                                "required_files": [],
                                "required_tools": [],
                                "required_scripts": [],
                                "required_hooks": [],
                                "min_mode": "hosted-hook",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (root / "references" / "runtime-capability-matrix.md").write_text(
                "This document warns that hosted-hook claims should be described carefully.\n"
                "But it does not declare hosted-hook mode in the capability table.\n"
                "| Capability | soft mode | mcp mode |\n"
                "|---|---|---|\n"
                "| stop gating | advisory only | runtime-backed |\n",
                encoding="utf-8",
            )
            (root / "mcp" / "server.py").write_text("def mission_lock():\n    pass\n", encoding="utf-8")
            (root / "scripts" / "claude_hooks.py").write_text("def pre_tool_use():\n    pass\n", encoding="utf-8")

            proc = subprocess.run(
                [sys.executable, str(REPO_ROOT / "scripts" / "claim_parity_audit.py"), str(root)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )

        self.assertNotEqual(proc.returncode, 0)
        payload = json.loads(proc.stdout)
        self.assertFalse(payload["passed"])
        self.assertFalse(payload["results"][0]["mode_declared_in_matrix"])

    def test_claim_parity_fails_when_required_bridge_hook_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "references").mkdir(parents=True)
            (root / "mcp").mkdir(parents=True)
            (root / "scripts").mkdir(parents=True)

            (root / "references" / "runtime-claim-manifest.json").write_text(
                json.dumps(
                    {
                        "claims": [
                            {
                                "id": "opencode-plugin-bridge",
                                "enforcement": "plugin+bridge+tests",
                                "required_files": ["scripts/opencode_plugin_bridge.py"],
                                "required_tools": [],
                                "required_scripts": ["scripts/opencode_plugin_bridge.py"],
                                "required_hooks": ["pre_tool_use"],
                                "min_mode": "host-assisted",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (root / "references" / "runtime-capability-matrix.md").write_text(
                "| Capability | soft mode | host-assisted mode |\n"
                "|---|---|---|\n"
                "| bridge gate | advisory | enforced |\n",
                encoding="utf-8",
            )
            (root / "mcp" / "server.py").write_text("def mission_lock():\n    pass\n", encoding="utf-8")
            (root / "scripts" / "claude_hooks.py").write_text(
                "def pre_tool_use():\n    pass\n",
                encoding="utf-8",
            )
            (root / "scripts" / "opencode_plugin_bridge.py").write_text(
                "def post_tool_use():\n    pass\n",
                encoding="utf-8",
            )

            proc = subprocess.run(
                [sys.executable, str(REPO_ROOT / "scripts" / "claim_parity_audit.py"), str(root)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )

        self.assertNotEqual(proc.returncode, 0)
        payload = json.loads(proc.stdout)
        self.assertFalse(payload["passed"])
        self.assertEqual(payload["results"][0]["id"], "opencode-plugin-bridge")
        self.assertEqual(payload["results"][0]["missing_hooks"], ["pre_tool_use"])


if __name__ == "__main__":
    unittest.main()
