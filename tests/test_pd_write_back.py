from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from incident_triage_mcp.adapters.pagerduty_real import PagerDutyAPI
from incident_triage_mcp.secrets.loader import SecretsLoader


def _secrets(**kwargs: str) -> SecretsLoader:
    defaults = {
        "PAGERDUTY_API_TOKEN": "test-token",
        "PAGERDUTY_FROM_EMAIL": "oncall@example.com",
        "PAGERDUTY_BASE_URL": "https://api.pagerduty.com",
    }
    defaults.update(kwargs)
    loader = MagicMock(spec=SecretsLoader)
    loader.get = lambda key, default=None: defaults.get(key, default)
    return loader


class TestPagerDutyAcknowledge(unittest.TestCase):
    def test_acknowledge_sends_correct_payload(self) -> None:
        api = PagerDutyAPI(_secrets())
        mock_response = MagicMock()
        mock_response.json.return_value = {}

        with patch("requests.put", return_value=mock_response) as mock_put:
            result = api.acknowledge_alert("PD123")

        mock_put.assert_called_once()
        call_url = mock_put.call_args[0][0]
        assert "PD123" in call_url

        body = mock_put.call_args[1]["json"]
        assert body["incident"]["status"] == "acknowledged"

        headers = mock_put.call_args[1]["headers"]
        assert headers["From"] == "oncall@example.com"

        assert result["acknowledged"] is True
        assert result["incident_id"] == "PD123"

    def test_acknowledge_missing_from_email_raises(self) -> None:
        api = PagerDutyAPI(_secrets(PAGERDUTY_FROM_EMAIL=""))
        mock_response = MagicMock()

        with self.assertRaises(RuntimeError) as ctx:
            api.acknowledge_alert("PD123")

        assert "PAGERDUTY_FROM_EMAIL" in str(ctx.exception)


class TestPagerDutyResolve(unittest.TestCase):
    def test_resolve_sends_correct_payload(self) -> None:
        api = PagerDutyAPI(_secrets())
        mock_response = MagicMock()

        with patch("requests.put", return_value=mock_response) as mock_put:
            result = api.resolve_alert("PD456")

        body = mock_put.call_args[1]["json"]
        assert body["incident"]["status"] == "resolved"
        assert result["resolved"] is True
        assert result["incident_id"] == "PD456"


class TestPdAcknowledgeToolDryRun(unittest.TestCase):
    """Verify the MCP tool enforces dry_run by default."""

    def test_dry_run_does_not_call_api(self) -> None:
        import sys
        import types
        import importlib
        from pathlib import Path

        SRC = Path(__file__).resolve().parents[1] / "src"
        if str(SRC) not in sys.path:
            sys.path.insert(0, str(SRC))

        if "mcp" not in sys.modules:
            mcp_module = types.ModuleType("mcp")
            server_module = types.ModuleType("mcp.server")
            fastmcp_module = types.ModuleType("mcp.server.fastmcp")

            class FastMCP:
                def __init__(self, *a, **kw): pass
                def tool(self):
                    def d(fn): return fn
                    return d
                def run(self, transport="stdio"): return None

            fastmcp_module.FastMCP = FastMCP
            server_module.fastmcp = fastmcp_module
            mcp_module.server = server_module
            sys.modules["mcp"] = mcp_module
            sys.modules["mcp.server"] = server_module
            sys.modules["mcp.server.fastmcp"] = fastmcp_module

        import os
        os.environ["MCP_ROLE"] = "admin"
        import incident_triage_mcp.policy.rbac as rbac
        importlib.reload(rbac)
        import incident_triage_mcp.server as server
        importlib.reload(server)

        with patch("requests.put") as mock_put:
            result = server.pd_acknowledge_alert(incident_id="PD789", dry_run=True)

        mock_put.assert_not_called()
        assert result["dry_run"] is True
        assert result["acknowledged"] is False
        assert result["incident_id"] == "PD789"
