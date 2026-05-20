import json
import shutil
import tempfile
import unittest
from pathlib import Path

from test_opencode_plugin import (
    PLUGIN_PATH,
    clean_env,
    copy_bridge_runtime,
    require_node,
    run_process,
    write_plugin_session_runner,
)


class OpenCodePluginJsoncEdgesTests(unittest.TestCase):
    def run_config_case(self, config_template: str, expect_bridge_enabled: bool) -> None:
        require_node(self)
        with tempfile.TemporaryDirectory(prefix="agent-runway-opencode-jsonc-edge-") as raw:
            tmp = Path(raw)
            runtime_root = tmp / "runtime"
            project_dir = runtime_root / "project"
            config_dir = project_dir / ".opencode"
            config_dir.mkdir(parents=True)
            scripts_dir, mcp_dir = copy_bridge_runtime(runtime_root)
            plugin_dir = runtime_root / ".opencode" / "plugins"
            plugin_dir.mkdir(parents=True)
            shutil.copyfile(PLUGIN_PATH, plugin_dir / "agent-runway.js")
            configured_db = tmp / "configured-state.db"
            config_text = config_template.replace(
                "__CONFIGURED_DB_JSON__", json.dumps(str(configured_db))
            )
            config_dir.joinpath("opencode.json").write_text(config_text, encoding="utf-8")
            runner = tmp / "run-plugin.mjs"
            write_plugin_session_runner(runner)
            env = clean_env(
                "ILH_DB_PATH",
                "ILH_SECRET_PATH",
                "ILH_OPENCODE_BRIDGE",
                "OPENCODE_CONFIG_CONTENT",
            )
            env.update({
                "AGENT_RUNWAY_OPENCODE_PLUGIN": str(plugin_dir / "agent-runway.js"),
                "CONFIGURED_DB_PATH": str(configured_db),
                "PROJECT_CWD": str(project_dir),
                "PYTHONPATH": str(scripts_dir),
            })
            proc = run_process(["node", str(runner)], project_dir, env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["configuredStateExists"], expect_bridge_enabled)
            self.assertFalse(payload["defaultStateExists"])
        self.assertFalse((mcp_dir / "agent_runway_runtime" / "__pycache__").exists())

    def test_plugin_and_bridge_load_commented_opencode_config(self) -> None:
        self.run_config_case(
            '{\n'
            '  // OpenCode accepts commented config files in user setups.\n'
            '  "mcp": {\n'
            '    /* block comments outside strings should be ignored */\n'
            '    "agent-runway": {\n'
            '      "environment": {\n'
            '        "ILH_DB_PATH": __CONFIGURED_DB_JSON__,\n'
            '        "ILH_OPENCODE_BRIDGE": "1",\n'
            '        "COMMENT_LIKE_VALUE": "https://example.test/a/*not-comment*/b"\n'
            '      }\n'
            '    }\n'
            '  }\n'
            '}\n',
            True,
        )

    def test_plugin_and_bridge_load_config_with_trailing_comma_before_comment(self) -> None:
        self.run_config_case(
            '{\n'
            '  "mcp": {\n'
            '    "agent-runway": {\n'
            '      "environment": {\n'
            '        "ILH_DB_PATH": __CONFIGURED_DB_JSON__,\n'
            '        "ILH_OPENCODE_BRIDGE": "1", // final env value\n'
            '      }, /* final server value */\n'
            '    },\n'
            '  },\n'
            '}\n',
            True,
        )

    def test_plugin_does_not_enable_bridge_from_unterminated_block_comment_config(self) -> None:
        self.run_config_case(
            '{"mcp":{"agent-runway":{"environment":{'
            '"ILH_DB_PATH":__CONFIGURED_DB_JSON__,'
            '"ILH_OPENCODE_BRIDGE":"1"}}}} /* unterminated',
            False,
        )


if __name__ == "__main__":
    unittest.main()
