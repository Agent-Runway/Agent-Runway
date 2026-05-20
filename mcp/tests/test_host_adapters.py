from __future__ import annotations

import importlib
import os
import tempfile
import unittest
from pathlib import Path


class HostAdapterTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        os.environ["ILH_DB_PATH"] = str(Path(self.temp_dir.name) / "state.db")
        os.environ["ILH_SECRET_PATH"] = str(Path(self.temp_dir.name) / "secret.key")

        import sys

        mcp_root = str(Path(__file__).resolve().parents[1])
        if mcp_root not in sys.path:
            sys.path.insert(0, mcp_root)

        self.host_adapters = importlib.import_module("agent_runway_runtime.host_adapters")
        self.host_adapters = importlib.reload(self.host_adapters)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()
        os.environ.pop("ILH_DB_PATH", None)
        os.environ.pop("ILH_SECRET_PATH", None)

    def test_resolve_event_host_preserves_raw_host_value(self) -> None:
        resolved = self.host_adapters.resolve_event_host(
            {"host": "codex-cli", "client_name": "ignored-client"}
        )
        self.assertEqual(resolved, "codex-cli")

    def test_resolve_event_host_uses_client_name_and_runtime_name_fallbacks(self) -> None:
        self.assertEqual(
            self.host_adapters.resolve_event_host({"client_name": "Cursor IDE"}),
            "Cursor IDE",
        )
        self.assertEqual(
            self.host_adapters.resolve_event_host({"runtime_name": "OpenCode TUI"}),
            "OpenCode TUI",
        )
        self.assertEqual(self.host_adapters.resolve_event_host({}), "unknown")

    def test_classify_host_key_maps_known_hosts(self) -> None:
        self.assertEqual(self.host_adapters.classify_host_key("claude-code"), "claude-code")
        self.assertEqual(self.host_adapters.classify_host_key("codex-cli"), "codex")
        self.assertEqual(self.host_adapters.classify_host_key("OpenCode TUI"), "opencode")
        self.assertEqual(self.host_adapters.classify_host_key("Pi CLI"), "pi-cli")
        self.assertEqual(self.host_adapters.classify_host_key("pi-coding-agent"), "pi-cli")
        self.assertEqual(self.host_adapters.classify_host_key("VSCode MCP"), "vscode")
        self.assertEqual(self.host_adapters.classify_host_key("Cursor IDE"), "cursor")
        self.assertEqual(self.host_adapters.classify_host_key("mystery host"), "unknown")

    def test_classify_host_key_rejects_loose_substring_false_positives(self) -> None:
        self.assertEqual(
            self.host_adapters.classify_host_key("my-vscode-extension"),
            "unknown",
        )
        self.assertEqual(
            self.host_adapters.classify_host_key("custom-claude-wrapper"),
            "unknown",
        )
        self.assertEqual(self.host_adapters.classify_host_key("codexify"), "unknown")
        self.assertEqual(self.host_adapters.classify_host_key("opencodeish"), "unknown")

    def test_get_host_adapter_exposes_configuration_mode(self) -> None:
        claude = self.host_adapters.get_host_adapter("claude-code")
        codex = self.host_adapters.get_host_adapter("codex")
        opencode = self.host_adapters.get_host_adapter("opencode")
        pi_cli = self.host_adapters.get_host_adapter("pi-cli")
        unknown = self.host_adapters.get_host_adapter("unknown")

        self.assertEqual(claude.key, "claude-code")
        self.assertEqual(claude.config_mode, "hosted_installer")
        self.assertTrue(claude.hosted_hooks_supported)
        self.assertTrue(claude.native_mcp_config_supported)
        self.assertTrue(claude.stop_blocking_supported)

        self.assertEqual(codex.key, "codex")
        self.assertEqual(codex.config_mode, "instructions_only")
        self.assertFalse(codex.hosted_hooks_supported)
        self.assertFalse(codex.native_mcp_config_supported)
        self.assertFalse(codex.stop_blocking_supported)

        self.assertEqual(opencode.key, "opencode")
        self.assertEqual(opencode.config_mode, "host_native_config")
        self.assertFalse(opencode.hosted_hooks_supported)
        self.assertTrue(opencode.native_mcp_config_supported)
        self.assertFalse(opencode.stop_blocking_supported)

        self.assertEqual(pi_cli.key, "pi-cli")
        self.assertEqual(pi_cli.config_mode, "extension_only")
        self.assertTrue(pi_cli.hosted_hooks_supported)
        self.assertFalse(pi_cli.native_mcp_config_supported)
        self.assertFalse(pi_cli.stop_blocking_supported)

        self.assertEqual(unknown.key, "unknown")
        self.assertEqual(unknown.config_mode, "instructions_only")

    def test_host_adapter_is_single_source_for_tool_taxonomy(self) -> None:
        claude = self.host_adapters.get_host_adapter("claude-code")
        codex = self.host_adapters.get_host_adapter("codex")
        unknown = self.host_adapters.get_host_adapter("unknown")

        self.assertIn("Bash", claude.execution_tools)
        self.assertIn("PowerShell", claude.execution_tools)
        self.assertIn("Shell", claude.execution_tools)
        self.assertIn("Codex", codex.execution_tools)
        self.assertIn("OpenCode", self.host_adapters.get_host_adapter("opencode").execution_tools)
        self.assertIn("bash", self.host_adapters.get_host_adapter("pi-cli").execution_tools)
        self.assertEqual(unknown.execution_tools, frozenset())
        self.assertIn("Read", claude.observation_tools)
        self.assertIn("Edit", claude.mutation_tools)

    def test_aggregate_execution_tools_match_adapter_registry(self) -> None:
        expected = frozenset(
            tool
            for adapter in self.host_adapters.HOST_ADAPTERS.values()
            for tool in adapter.execution_tools
        )
        self.assertEqual(self.host_adapters.EXECUTION_TOOLS, expected)
        self.assertEqual(self.host_adapters.SHELL_LIKE_TOOLS, expected)
        self.assertIn("Bash", expected)
        self.assertIn("Codex", expected)
        self.assertIn("OpenCode", expected)
        self.assertNotIn("Read", expected)
        self.assertNotIn("Edit", expected)

    def test_known_non_execution_tools_match_adapter_registry_union(self) -> None:
        expected_observation = frozenset(
            tool
            for adapter in self.host_adapters.HOST_ADAPTERS.values()
            for tool in adapter.observation_tools
        )
        expected_mutation = frozenset(
            tool
            for adapter in self.host_adapters.HOST_ADAPTERS.values()
            for tool in adapter.mutation_tools
        )
        expected = expected_observation | expected_mutation

        self.assertEqual(self.host_adapters.OBSERVATION_TOOLS, expected_observation)
        self.assertEqual(self.host_adapters.MUTATION_TOOLS, expected_mutation)
        self.assertEqual(self.host_adapters.KNOWN_NON_EXECUTION_TOOLS, expected)
        self.assertTrue(
            self.host_adapters.EXECUTION_TOOLS.isdisjoint(
                self.host_adapters.KNOWN_NON_EXECUTION_TOOLS
            )
        )

    def test_supported_host_keys_are_derived_from_adapter_registry(self) -> None:
        self.assertIn("claude-code", self.host_adapters.SUPPORTED_HOST_KEYS)
        self.assertIn("codex", self.host_adapters.SUPPORTED_HOST_KEYS)
        self.assertIn("opencode", self.host_adapters.SUPPORTED_HOST_KEYS)
        self.assertIn("pi-cli", self.host_adapters.SUPPORTED_HOST_KEYS)
        self.assertIn("vscode", self.host_adapters.SUPPORTED_HOST_KEYS)
        self.assertIn("cursor", self.host_adapters.SUPPORTED_HOST_KEYS)
        self.assertNotIn("unknown", self.host_adapters.SUPPORTED_HOST_KEYS)
        self.assertEqual(len(self.host_adapters.SUPPORTED_HOST_KEYS), 6)

    def test_classify_host_key_empty_or_none_is_unknown(self) -> None:
        self.assertEqual(self.host_adapters.classify_host_key(""), "unknown")
        self.assertEqual(self.host_adapters.classify_host_key("   "), "unknown")

    def test_unknown_host_adapter_has_no_execution_or_stop_blocking(self) -> None:
        unknown = self.host_adapters.get_host_adapter("unknown")
        self.assertEqual(unknown.execution_tools, frozenset())
        self.assertFalse(unknown.stop_blocking_supported)
        self.assertFalse(unknown.hosted_hooks_supported)


if __name__ == "__main__":
    unittest.main()
