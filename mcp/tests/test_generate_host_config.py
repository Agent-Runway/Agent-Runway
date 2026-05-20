from __future__ import annotations

import json
import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def load_claude_hooks_module():
    module_path = REPO_ROOT / "scripts" / "claude_hooks.py"
    spec = importlib.util.spec_from_file_location("claude_hooks", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class GenerateHostConfigTestCase(unittest.TestCase):
    def test_pi_cli_config_is_extension_only_without_mcp_or_stop_parity(self) -> None:
        script = REPO_ROOT / "scripts" / "generate_host_config.py"
        proc = subprocess.run(
            [sys.executable, str(script), "--host", "pi-cli", "--agent-runway-dir", str(REPO_ROOT)],
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

    def test_configure_script_marks_non_claude_hosts_as_instructions_only(self) -> None:
        script = REPO_ROOT / "scripts" / "generate_host_config.py"
        proc = subprocess.run(
            [sys.executable, str(script), "--host", "codex", "--agent-runway-dir", str(REPO_ROOT)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["mode"], "instructions_only")
        self.assertEqual(payload["host"], "codex")
        self.assertEqual(payload["host_display_name"], "Codex")
        self.assertIn("not a host-native installer", payload["note"])
        self.assertNotIn("hooks", payload)

    def test_configure_script_marks_vscode_and_cursor_as_instructions_only(self) -> None:
        script = REPO_ROOT / "scripts" / "generate_host_config.py"
        for host, display_name in (("vscode", "VSCode"), ("cursor", "Cursor")):
            with self.subTest(host=host):
                proc = subprocess.run(
                    [sys.executable, str(script), "--host", host, "--agent-runway-dir", str(REPO_ROOT)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    check=False,
                )
                self.assertEqual(proc.returncode, 0)
                payload = json.loads(proc.stdout)
                self.assertEqual(payload["mode"], "instructions_only")
                self.assertEqual(payload["host"], host)
                self.assertEqual(payload["host_display_name"], display_name)
                self.assertIn("env", payload)
                self.assertNotIn("hooks", payload)

    def test_configure_script_emits_claude_code_hosted_settings(self) -> None:
        script = REPO_ROOT / "scripts" / "generate_host_config.py"
        proc = subprocess.run(
            [sys.executable, str(script), "--host", "claude-code", "--agent-runway-dir", str(REPO_ROOT)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload.get("mode", ""), "")
        self.assertIn("hooks", payload)
        self.assertIn("Stop", payload["hooks"])
        self.assertIn("SessionStart", payload["hooks"])
        self.assertIn("PreToolUse", payload["hooks"])
        self.assertIn("PostToolUse", payload["hooks"])
        self.assertIn("SubagentStart", payload["hooks"])
        self.assertIn("SubagentStop", payload["hooks"])
        self.assertIn("permissions", payload)
        self.assertIn("env", payload)
        self.assertNotIn("ILH_DB_PATH", payload["env"])
        self.assertTrue(payload["env"]["ILH_SECRET_PATH"].endswith("secret.key"))
        stop_command = payload["hooks"]["Stop"][0]["hooks"][0]["command"]
        self.assertIn("python", stop_command)
        self.assertIn("claude_hooks.py", stop_command)
        self.assertTrue(stop_command.endswith(" stop"))
        subagent_start_command = payload["hooks"]["SubagentStart"][0]["hooks"][0]["command"]
        subagent_stop_command = payload["hooks"]["SubagentStop"][0]["hooks"][0]["command"]
        self.assertTrue(subagent_start_command.endswith(" subagent-start"))
        self.assertTrue(subagent_stop_command.endswith(" subagent-stop"))
        self.assertIn(
            f"Read({payload['env']['ILH_SECRET_PATH']})",
            payload["permissions"]["deny"],
        )

    def test_configure_script_claude_permissions_cover_all_hook_risky_bash_patterns(self) -> None:
        script = REPO_ROOT / "scripts" / "generate_host_config.py"
        hooks = load_claude_hooks_module()
        proc = subprocess.run(
            [sys.executable, str(script), "--host", "claude-code", "--agent-runway-dir", str(REPO_ROOT)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0)
        payload = json.loads(proc.stdout)
        expected = {
            f"Bash({' '.join(pattern.split())}:*)"
            for pattern in hooks.DANGEROUS_BASH_PATTERNS
        }
        self.assertEqual(set(payload["permissions"]["ask"]), expected)

    def test_configure_script_quotes_hook_paths_for_windows_shells(self) -> None:
        script = REPO_ROOT / "scripts" / "generate_host_config.py"
        agent_runway_dir = "C:\\Users\\Example User\\Agent-Runway"
        proc = subprocess.run(
            [sys.executable, str(script), "--host", "claude-code", "--agent-runway-dir", agent_runway_dir],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0)
        payload = json.loads(proc.stdout)
        stop_command = payload["hooks"]["Stop"][0]["hooks"][0]["command"]
        self.assertIn('"C:/Users/Example User/Agent-Runway/scripts/claude_hooks.py"', stop_command)
        self.assertNotIn("C:\\Users\\Example User", stop_command)
        self.assertNotIn("'C:\\Users\\Example User", stop_command)

    def test_configure_script_emits_native_opencode_config(self) -> None:
        script = REPO_ROOT / "scripts" / "generate_host_config.py"
        proc = subprocess.run(
            [sys.executable, str(script), "--host", "opencode", "--agent-runway-dir", str(REPO_ROOT)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["mode"], "host_native_config")
        self.assertEqual(payload["host"], "opencode")
        self.assertEqual(payload["host_display_name"], "OpenCode")
        self.assertIn("$schema", payload)
        self.assertIn("mcp", payload)
        self.assertIn("agent-runway", payload["mcp"])
        server = payload["mcp"]["agent-runway"]
        self.assertEqual(server["type"], "local")
        self.assertIsInstance(server["command"], list)
        self.assertEqual(server["command"][0], "python")
        self.assertIn("environment", server)
        self.assertNotIn("ILH_DB_PATH", server["environment"])
        self.assertIn("ILH_SECRET_PATH", server["environment"])
        self.assertEqual(server["environment"]["ILH_OPENCODE_BRIDGE"], "0")
        self.assertEqual(server["command"][1], str(REPO_ROOT / "mcp" / "server.py"))
        self.assertIn("project-local .agent-runway/state.db", payload["note"])
        self.assertIn("falls back to OpenCode config content or config files", payload["note"])
        self.assertIn("shim or symlink", payload["note"])
        self.assertIn("permission", payload)
        self.assertIn("bash", payload["permission"])
        self.assertIn("read", payload["permission"])
        self.assertIn("edit", payload["permission"])
        self.assertIn("task", payload["permission"])
        self.assertIn("doom_loop", payload["permission"])
        self.assertEqual(payload["permission"]["bash"]["*"], "ask")
        self.assertEqual(payload["permission"]["task"]["*"], "ask")
        self.assertEqual(payload["permission"]["doom_loop"], "ask")
        self.assertEqual(payload["permission"]["read"]["*"], "allow")
        secret_path = payload["mcp"]["agent-runway"]["environment"]["ILH_SECRET_PATH"]
        self.assertEqual(payload["permission"]["read"][secret_path], "deny")
        self.assertNotIn("plugin", payload)
        self.assertNotIn("hooks", payload)

    def test_configure_script_supported_hosts_come_from_adapter_registry(self) -> None:
        script_text = (REPO_ROOT / "scripts" / "generate_host_config.py").read_text(encoding="utf-8")
        self.assertIn("SUPPORTED_HOST_KEYS", script_text)
        self.assertNotIn('SUPPORTED_HOSTS = ("claude-code", "codex", "opencode", "vscode", "cursor")', script_text)



if __name__ == "__main__":
    unittest.main()
