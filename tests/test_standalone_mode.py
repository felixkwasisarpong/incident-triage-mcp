from __future__ import annotations

import importlib
import os
import sys
import tempfile
import types
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _ensure_mcp_registry_stub() -> None:
    mcp_module = types.ModuleType("mcp")
    server_module = types.ModuleType("mcp.server")
    fastmcp_module = types.ModuleType("mcp.server.fastmcp")

    class _ToolManager:
        def __init__(self) -> None:
            self._tools: dict[str, object] = {}

    class FastMCP:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs
            self._tool_manager = _ToolManager()

        def tool(self):
            def decorator(fn):
                self._tool_manager._tools[fn.__name__] = fn
                return fn

            return decorator

        def run(self, transport: str = "stdio") -> None:  # pragma: no cover - tiny shim
            return None

    fastmcp_module.FastMCP = FastMCP
    server_module.fastmcp = fastmcp_module
    mcp_module.server = server_module

    sys.modules["mcp"] = mcp_module
    sys.modules["mcp.server"] = server_module
    sys.modules["mcp.server.fastmcp"] = fastmcp_module


def _reload_server_module():
    _ensure_mcp_registry_stub()
    import incident_triage_mcp.policy.rbac as rbac
    import incident_triage_mcp.policy.safe_actions as safe_actions
    import incident_triage_mcp.server as server

    importlib.reload(rbac)
    importlib.reload(safe_actions)
    return importlib.reload(server)


@contextmanager
def _without_boto3():
    blocked_prefixes = ("boto3", "botocore")
    removed: dict[str, object] = {}
    for name in list(sys.modules):
        if (
            name == blocked_prefixes[0]
            or name.startswith("boto3.")
            or name == blocked_prefixes[1]
            or name.startswith("botocore.")
        ):
            removed[name] = sys.modules.pop(name)

    real_import = __import__

    def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name in blocked_prefixes or name.startswith("boto3.") or name.startswith("botocore."):
            raise ModuleNotFoundError("No module named 'boto3'")
        return real_import(name, globals, locals, fromlist, level)

    try:
        with patch("builtins.__import__", side_effect=_guarded_import):
            yield
    finally:
        sys.modules.update(removed)


class TestStandaloneMode(unittest.TestCase):
    def test_server_boots_with_minimal_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
            os.environ,
            {
                "MCP_TRANSPORT": "stdio",
                "RUNBOOKS_DIR": tmpdir,
            },
            clear=True,
        ):
            server = _reload_server_module()

        self.assertIsNotNone(server.mcp)
        self.assertEqual(server._evidence_backend(), "fs")

    def test_server_boots_without_boto3_when_aws_provider_not_selected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
            os.environ,
            {
                "MCP_TRANSPORT": "stdio",
                "RUNBOOKS_DIR": tmpdir,
                "ALERTS_PROVIDER": "mock",
                "METRICS_PROVIDER": "mock",
                "LOGS_PROVIDER": "mock",
                "TRACES_PROVIDER": "mock",
            },
            clear=True,
        ), _without_boto3():
            server = _reload_server_module()

        self.assertIsNotNone(server.mcp)

    def test_tools_list_excludes_airflow_tools_when_not_airflow_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, tempfile.TemporaryDirectory() as idempotency_tmp, patch.dict(
            os.environ,
            {
                "MCP_TRANSPORT": "stdio",
                "RUNBOOKS_DIR": tmpdir,
                "EVIDENCE_BACKEND": "fs",
                "EVIDENCE_DIR": tmpdir,
                "IDEMPOTENCY_STORE_PATH": str(Path(idempotency_tmp) / "jira_idempotency.json"),
            },
            clear=True,
        ):
            server = _reload_server_module()

        tools = set(server.mcp._tool_manager._tools.keys())
        self.assertIn("runbooks_search", tools)
        self.assertIn("incident_triage_summary", tools)
        self.assertIn("evidence_get_bundle", tools)
        self.assertNotIn("airflow_trigger_incident_dag", tools)
        self.assertNotIn("airflow_get_incident_artifact", tools)

    def test_fs_backend_summary_works_with_seeded_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, tempfile.TemporaryDirectory() as idempotency_tmp, patch.dict(
            os.environ,
            {
                "MCP_TRANSPORT": "stdio",
                "RUNBOOKS_DIR": tmpdir,
                "EVIDENCE_BACKEND": "fs",
                "EVIDENCE_DIR": tmpdir,
                "IDEMPOTENCY_STORE_PATH": str(Path(idempotency_tmp) / "jira_idempotency.json"),
            },
            clear=True,
        ):
            server = _reload_server_module()
            seeded = server.evidence_seed_sample("INC-OFFLINE", "payments-api", window_minutes=30)
            summary = server.incident_triage_summary("INC-OFFLINE")

        self.assertTrue(seeded["seeded"])
        self.assertEqual(summary["incident_id"], "INC-OFFLINE")
        self.assertEqual(summary["service"], "payments-api")
        self.assertIn("headline", summary)

    def test_airflow_backend_missing_env_starts_and_returns_disabled_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, tempfile.TemporaryDirectory() as idempotency_tmp, patch.dict(
            os.environ,
            {
                "MCP_TRANSPORT": "stdio",
                "RUNBOOKS_DIR": tmpdir,
                "EVIDENCE_BACKEND": "airflow",
                "EVIDENCE_DIR": tmpdir,
                "IDEMPOTENCY_STORE_PATH": str(Path(idempotency_tmp) / "jira_idempotency.json"),
            },
            clear=True,
        ):
            server = _reload_server_module()
            tools = set(server.mcp._tool_manager._tools.keys())
            trigger = server.airflow_trigger_incident_dag("INC-501", "payments-api")
            artifact = server.airflow_get_incident_artifact("INC-501")

        self.assertIn("airflow_trigger_incident_dag", tools)
        self.assertIn("airflow_get_incident_artifact", tools)
        self.assertFalse(trigger["enabled"])
        self.assertIn("airflow_disabled", trigger["error"])
        self.assertFalse(artifact["enabled"])
        self.assertIn("airflow_disabled", artifact["error"])

    def test_workflow_airflow_with_fs_evidence_registers_airflow_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, tempfile.TemporaryDirectory() as idempotency_tmp, patch.dict(
            os.environ,
            {
                "MCP_TRANSPORT": "stdio",
                "RUNBOOKS_DIR": tmpdir,
                "WORKFLOW_BACKEND": "airflow",
                "EVIDENCE_BACKEND": "fs",
                "EVIDENCE_DIR": tmpdir,
                "IDEMPOTENCY_STORE_PATH": str(Path(idempotency_tmp) / "jira_idempotency.json"),
            },
            clear=True,
        ):
            server = _reload_server_module()
            tools = set(server.mcp._tool_manager._tools.keys())

        self.assertIn("airflow_trigger_incident_dag", tools)
        self.assertIn("airflow_get_incident_artifact", tools)


if __name__ == "__main__":
    unittest.main()
