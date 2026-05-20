from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))


class OpenCodeBridgeJsoncParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        os.environ["ILH_DB_PATH"] = str(Path(self.temp_dir.name) / "state.db")
        os.environ["ILH_SECRET_PATH"] = str(Path(self.temp_dir.name) / "secret.key")
        self.bridge = importlib.reload(importlib.import_module("opencode_plugin_bridge"))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()
        os.environ.pop("ILH_DB_PATH", None)
        os.environ.pop("ILH_SECRET_PATH", None)

    def parse(self, config_text: str) -> dict[str, object]:
        parsed = self.bridge._parse_config_text(config_text)
        self.assertIsInstance(parsed, dict)
        return parsed

    def test_parser_preserves_comment_markers_inside_strings(self) -> None:
        config = self.parse(
            '{"value":"https://example.test/a//b/*c*/d","mcp":{'
            '"agent-runway":{"environment":{"ILH_OPENCODE_BRIDGE":"1"}}}}'
        )

        self.assertEqual(config["value"], "https://example.test/a//b/*c*/d")

    def test_parser_allows_trailing_comma_before_comments(self) -> None:
        config = self.parse(
            '{"mcp":{"agent-runway":{"environment":{'
            '"ILH_OPENCODE_BRIDGE":"1", // trailing env value\n'
            '}, /* trailing server value */ }}}'
        )

        environment = config["mcp"]["agent-runway"]["environment"]
        self.assertEqual(environment["ILH_OPENCODE_BRIDGE"], "1")

    def test_parser_rejects_unterminated_block_comment(self) -> None:
        with self.assertRaises(json.JSONDecodeError):
            self.bridge._parse_config_text('{"mcp":{}} /* unterminated')

    def test_bridge_environment_ignores_non_string_and_empty_keys(self) -> None:
        environment = self.bridge._agent_runway_environment(
            {
                "mcp": {
                    "agent-runway": {
                        "environment": {
                            "ILH_DB_PATH": "state.db",
                            "": "empty-key",
                            0: "numeric-key",
                            "NULL_VALUE": None,
                        }
                    }
                }
            }
        )

        self.assertEqual({"ILH_DB_PATH": "state.db"}, environment)


if __name__ == "__main__":
    unittest.main()
