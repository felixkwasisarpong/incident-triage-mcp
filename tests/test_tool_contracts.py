from __future__ import annotations

import importlib
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


CORE_TOOLS = {
    "incident_triage_run",
    "alerts_fetch_active",
    "service_health_snapshot",
    "logs_fetch_recent",
    "traces_fetch_recent",
    "runbooks_search",
    "ping",
    "slack_post_update",
    "evidence_get_bundle",
    "evidence_wait_for_bundle",
    "evidence_seed_sample",
    "incident_triage_summary",
    "jira_draft_ticket",
    "jira_create_ticket",
    "jira_list_projects",
    "jira_list_issue_types",
    "jira_validate_credentials",
}

AIRFLOW_TOOLS = {
    "airflow_trigger_incident_dag",
    "airflow_get_incident_artifact",
}


def _ensure_mcp_registry_stub() -> None:
    mcp_module = types.ModuleType("mcp")
    server_module = types.ModuleType("mcp.server")
    fastmcp_module = types.ModuleType("mcp.server.fastmcp")

    class _ToolManager:
        def __init__(self) -> None:
            self._tools: dict[str, object] = {}

    class FastMCP:
        def __init__(self, *args, **kwargs):
            self._tool_manager = _ToolManager()

        def tool(self):
            def decorator(fn):
                self._tool_manager._tools[fn.__name__] = fn
                return fn

            return decorator

        def run(self, transport: str = "stdio") -> None:  # pragma: no cover
            return None

    fastmcp_module.FastMCP = FastMCP
    server_module.fastmcp = fastmcp_module
    mcp_module.server = server_module

    sys.modules["mcp"] = mcp_module
    sys.modules["mcp.server"] = server_module
    sys.modules["mcp.server.fastmcp"] = fastmcp_module


def _reload_server():
    _ensure_mcp_registry_stub()
    import incident_triage_mcp.policy.rbac as rbac
    import incident_triage_mcp.policy.safe_actions as safe_actions
    import incident_triage_mcp.server as server

    importlib.reload(rbac)
    importlib.reload(safe_actions)
    return importlib.reload(server)


class TestToolContracts(unittest.TestCase):
    def _load_tool_names(self, env: dict[str, str]) -> set[str]:
        with patch.dict(os.environ, env, clear=True):
            server = _reload_server()
            return set(server.mcp._tool_manager._tools.keys())

    def test_core_tools_are_registered_in_fs_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tools = self._load_tool_names(
                {
                    "MCP_TRANSPORT": "stdio",
                    "RUNBOOKS_DIR": tmpdir,
                    "EVIDENCE_BACKEND": "fs",
                    "EVIDENCE_DIR": tmpdir,
                }
            )

        self.assertTrue(CORE_TOOLS.issubset(tools))
        self.assertTrue(AIRFLOW_TOOLS.isdisjoint(tools))

    def test_core_tools_are_registered_in_none_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tools = self._load_tool_names(
                {
                    "MCP_TRANSPORT": "stdio",
                    "RUNBOOKS_DIR": tmpdir,
                    "EVIDENCE_BACKEND": "none",
                    "EVIDENCE_DIR": tmpdir,
                }
            )

        self.assertTrue(CORE_TOOLS.issubset(tools))
        self.assertTrue(AIRFLOW_TOOLS.isdisjoint(tools))

    def test_airflow_tools_are_registered_only_in_airflow_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tools = self._load_tool_names(
                {
                    "MCP_TRANSPORT": "stdio",
                    "RUNBOOKS_DIR": tmpdir,
                    "EVIDENCE_BACKEND": "airflow",
                    "EVIDENCE_DIR": tmpdir,
                }
            )

        self.assertTrue(CORE_TOOLS.issubset(tools))
        self.assertTrue(AIRFLOW_TOOLS.issubset(tools))


if __name__ == "__main__":
    unittest.main()
