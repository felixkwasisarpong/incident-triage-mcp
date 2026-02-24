from __future__ import annotations

import importlib
import io
import os
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout
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


class TestServerCli(unittest.TestCase):
    def test_help_exits_without_starting_server(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
            os.environ,
            {
                "MCP_TRANSPORT": "stdio",
                "RUNBOOKS_DIR": tmpdir,
                "EVIDENCE_BACKEND": "fs",
                "EVIDENCE_DIR": tmpdir,
            },
            clear=True,
        ):
            server = _reload_server()

        buf = io.StringIO()
        with patch.object(server.mcp, "run") as run_mock, patch.object(
            sys, "argv", ["incident-triage-mcp", "--help"]
        ), redirect_stdout(buf):
            with self.assertRaises(SystemExit) as ctx:
                server.main()

        self.assertEqual(ctx.exception.code, 0)
        run_mock.assert_not_called()
        out = buf.getvalue()
        self.assertIn("usage:", out)
        self.assertIn("--transport", out)


if __name__ == "__main__":
    unittest.main()
