from __future__ import annotations

import importlib
import sys
import types
import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _ensure_mcp_stub() -> None:
    if "mcp" in sys.modules:
        return
    mcp_module = types.ModuleType("mcp")
    server_module = types.ModuleType("mcp.server")
    fastmcp_module = types.ModuleType("mcp.server.fastmcp")

    class FastMCP:
        def __init__(self, *args, **kwargs):
            pass

        def tool(self):
            def decorator(fn):
                return fn
            return decorator

        def run(self, transport: str = "stdio") -> None:
            return None

    fastmcp_module.FastMCP = FastMCP
    server_module.fastmcp = fastmcp_module
    mcp_module.server = server_module
    sys.modules["mcp"] = mcp_module
    sys.modules["mcp.server"] = server_module
    sys.modules["mcp.server.fastmcp"] = fastmcp_module


def _load_server():
    _ensure_mcp_stub()
    import incident_triage_mcp.policy.rbac as rbac
    import incident_triage_mcp.policy.safe_actions as safe_actions
    import incident_triage_mcp.server as server
    importlib.reload(rbac)
    importlib.reload(safe_actions)
    return importlib.reload(server)


class TestSlackThreadTs(unittest.TestCase):
    def setUp(self) -> None:
        self.server = _load_server()

    def test_thread_ts_included_in_payload_when_provided(self) -> None:
        result = self.server.slack_post_update(
            incident_id="INC-1",
            dry_run=True,
            thread_ts="1234567890.123456",
        )
        assert result["dry_run"] is True
        payload = result["payload"]
        assert "thread_ts" in payload
        assert payload["thread_ts"] == "1234567890.123456"

    def test_thread_ts_absent_when_not_provided(self) -> None:
        result = self.server.slack_post_update(
            incident_id="INC-1",
            dry_run=True,
        )
        payload = result["payload"]
        assert "thread_ts" not in payload

    def test_thread_ts_none_not_included(self) -> None:
        result = self.server.slack_post_update(
            incident_id="INC-1",
            dry_run=True,
            thread_ts=None,
        )
        payload = result["payload"]
        assert "thread_ts" not in payload
