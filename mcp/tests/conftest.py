from __future__ import annotations

import os
import subprocess
import sys
from functools import lru_cache

import pytest


_HARNESS_SECRET = "a" * 64
_ENV_KEYS = (
    "ILH_DB_PATH",
    "ILH_SECRET_PATH",
    "ILH_HARNESS_SECRET",
    "ILH_DEBUG",
    "ILH_DEBUG_LOG_PATH",
)
_MISSING = object()


@pytest.fixture(autouse=True)
def isolate_agent_runway_env():
    saved = {key: os.environ.get(key, _MISSING) for key in _ENV_KEYS}
    for key in _ENV_KEYS:
        os.environ.pop(key, None)
    os.environ.setdefault("ILH_HARNESS_SECRET", _HARNESS_SECRET)
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is _MISSING:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@lru_cache(maxsize=1)
def _node_can_spawn_python() -> tuple[bool, str]:
    script = """
const { spawnSync } = require('node:child_process');
const py = process.env.ILH_PYTHON;
const proc = spawnSync(py, ['-c', 'print(1)'], { encoding: 'utf8' });
if (proc.error) {
  console.log(String(proc.error.message || proc.error));
  process.exit(90);
}
process.exit(proc.status || 0);
"""
    try:
        proc = subprocess.run(
            ["node", "-e", script],
            env={**os.environ, "ILH_PYTHON": sys.executable},
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    if proc.returncode == 0:
        return True, ""
    return False, (proc.stdout or f"node returned {proc.returncode}").strip()


def pytest_runtest_setup(item):
    nodeid = item.nodeid
    needs_node_python_bridge = (
        "test_integration_workflows.py::IntegrationWorkflowTestCase::test_opencode" in nodeid
        or "test_opencode_plugin_duration_edges.py::" in nodeid
        or "test_opencode_plugin_jsonc_edges.py::" in nodeid
        or (
            "test_opencode_plugin.py::OpenCodePluginTests::test_" in nodeid
            and "test_python_bridge_" not in nodeid
        )
    )
    if not needs_node_python_bridge:
        return
    available, reason = _node_can_spawn_python()
    if not available:
        pytest.skip(f"node cannot spawn the Python OpenCode bridge in this environment: {reason}")
