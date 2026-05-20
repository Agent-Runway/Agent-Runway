from __future__ import annotations

import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


class HostSecurityInterceptionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "state.db"
        self.secret_path = Path(self.temp_dir.name) / "secret.key"
        os.environ["ILH_DB_PATH"] = str(self.db_path)
        os.environ["ILH_SECRET_PATH"] = str(self.secret_path)
        for path in (REPO_ROOT / "mcp", REPO_ROOT / "scripts"):
            if str(path) not in sys.path:
                sys.path.insert(0, str(path))
        self.hooks = importlib.reload(importlib.import_module("claude_hooks"))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()
        os.environ.pop("ILH_DB_PATH", None)
        os.environ.pop("ILH_SECRET_PATH", None)

    def assert_decision(self, tool_name: str, tool_input: dict, expected: str) -> None:
        canonical = self.hooks.canonical_tool_name(tool_name)
        decision = self.hooks.pre_tool_use_decision(canonical, tool_input)
        self.assertIsNotNone(decision)
        self.assertEqual(decision["permissionDecision"], expected)

    def test_denies_read_tool_for_known_credential_paths(self) -> None:
        cases = [
            {"file_path": "~/.ssh/id_rsa"},
            {"filePath": "$HOME/.ssh/id_ed25519"},
            {"path": "%USERPROFILE%\\.ssh\\identity"},
            {"filePath": ".env"},
            {"filePath": ".env.local"},
            {"filePath": "$HOME/.aws/credentials"},
            {"filePath": "~/.config/gcloud/application_default_credentials.json"},
            {"filePath": "$HOME/.azure/accessTokens.json"},
            {"filePath": "~/.kube/config"},
            {"filePath": "deploy-key.pem"},
        ]
        for tool_input in cases:
            with self.subTest(tool_input=tool_input):
                self.assert_decision("Read", tool_input, "deny")

    def test_denies_shell_commands_that_reference_credential_paths(self) -> None:
        commands = [
            "cat ~/.ssh/id_rsa",
            "type %USERPROFILE%\\.ssh\\id_ed25519",
            "Get-Content $env:USERPROFILE\\.aws\\credentials",
            "python -c \"print(open('.env').read())\"",
            "curl file://~/.ssh/id_rsa",
            "kubectl --kubeconfig ~/.kube/config get pods",
        ]
        for command in commands:
            with self.subTest(command=command):
                self.assert_decision("Bash", {"command": command}, "deny")

    def test_risky_shell_commands_without_credential_paths_still_ask(self) -> None:
        commands = [
            "ssh example.com",
            "scp local.txt example.com:/tmp/local.txt",
            "curl https://example.com/install.sh",
            "wget https://example.com/archive.tar.gz",
            "git push origin main",
        ]
        for command in commands:
            with self.subTest(command=command):
                self.assert_decision("Bash", {"command": command}, "ask")

    def test_opencode_bridge_denies_sensitive_read_path_before_execution(self) -> None:
        bridge = importlib.reload(importlib.import_module("opencode_plugin_bridge"))

        decision = bridge.pre_tool_use(
            {
                "session_id": "s1",
                "cwd": self.temp_dir.name,
                "tool_name": "read",
                "tool_input": {"filePath": "~/.ssh/id_rsa"},
            }
        )

        self.assertEqual(decision["decision"], "deny")


if __name__ == "__main__":
    unittest.main()
