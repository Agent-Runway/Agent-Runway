from __future__ import annotations

import builtins
import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


MCP_ROOT = Path(__file__).resolve().parents[1]
if str(MCP_ROOT) not in sys.path:
    sys.path.insert(0, str(MCP_ROOT))


class FastMcpImportEdgesTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        os.environ["ILH_DB_PATH"] = str(Path(self.temp_dir.name) / "state.db")
        os.environ["ILH_SECRET_PATH"] = str(Path(self.temp_dir.name) / "secret.key")
        sys.modules.pop("server", None)

    def tearDown(self) -> None:
        sys.modules.pop("server", None)
        self.temp_dir.cleanup()
        os.environ.pop("ILH_DB_PATH", None)
        os.environ.pop("ILH_SECRET_PATH", None)

    def import_server_with_fastmcp_failure(self, exc: BaseException):
        original_import = builtins.__import__

        def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "mcp.server.fastmcp":
                raise exc
            return original_import(name, globals, locals, fromlist, level)

        with patch("builtins.__import__", side_effect=guarded_import):
            return importlib.import_module("server")

    def test_fastmcp_import_success_uses_real_mcp_object(self) -> None:
        server = importlib.import_module("server")

        self.assertEqual("agent-runway", server.mcp.name)
        self.assertTrue(hasattr(server.mcp, "list_tools"))

    def test_fastmcp_import_runtime_error_is_not_swallowed(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "broken FastMCP import"):
            self.import_server_with_fastmcp_failure(RuntimeError("broken FastMCP import"))

    def test_missing_mcp_sdk_uses_explicit_runtime_stub(self) -> None:
        missing = ModuleNotFoundError("No module named 'mcp'")
        missing.name = "mcp"

        server = self.import_server_with_fastmcp_failure(missing)

        with self.assertRaisesRegex(RuntimeError, "MCP SDK is not installed"):
            server.mcp.run()

    def test_missing_mcp_server_package_uses_explicit_runtime_stub(self) -> None:
        missing = ModuleNotFoundError("No module named 'mcp.server'")
        missing.name = "mcp.server"

        server = self.import_server_with_fastmcp_failure(missing)

        self.assertEqual("agent-runway", server.mcp.name)
        with self.assertRaisesRegex(RuntimeError, "MCP SDK is not installed"):
            server.mcp.run()

    def test_missing_fastmcp_module_uses_explicit_runtime_stub(self) -> None:
        missing = ModuleNotFoundError("No module named 'mcp.server.fastmcp'")
        missing.name = "mcp.server.fastmcp"

        server = self.import_server_with_fastmcp_failure(missing)

        self.assertEqual("FastMCP", server.mcp.__class__.__name__)
        with self.assertRaisesRegex(RuntimeError, "MCP SDK is not installed"):
            server.mcp.run()

    def test_fastmcp_transitive_module_missing_is_not_swallowed(self) -> None:
        missing = ModuleNotFoundError("No module named 'fastmcp_dependency'")
        missing.name = "fastmcp_dependency"

        with self.assertRaises(ModuleNotFoundError):
            self.import_server_with_fastmcp_failure(missing)

    def test_fastmcp_server_subpackage_missing_is_not_swallowed(self) -> None:
        missing = ModuleNotFoundError("No module named 'mcp.server.fastmcp_dependency'")
        missing.name = "mcp.server.fastmcp_dependency"

        with self.assertRaises(ModuleNotFoundError):
            self.import_server_with_fastmcp_failure(missing)


if __name__ == "__main__":
    unittest.main()
