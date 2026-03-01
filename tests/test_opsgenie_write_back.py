from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from incident_triage_mcp.adapters.opsgenie_real import OpsgenieAPI
from incident_triage_mcp.secrets.loader import SecretsLoader


def _secrets(**kwargs: str) -> SecretsLoader:
    defaults = {
        "OPSGENIE_API_KEY": "test-key",
        "OPSGENIE_BASE_URL": "https://api.opsgenie.com",
    }
    defaults.update(kwargs)
    loader = MagicMock(spec=SecretsLoader)
    loader.get = lambda key, default=None: defaults.get(key, default)
    return loader


class TestOpsgenieAcknowledge(unittest.TestCase):
    def test_acknowledge_posts_to_correct_url(self) -> None:
        api = OpsgenieAPI(_secrets())
        mock_response = MagicMock()
        mock_response.content = b'{"requestId": "req-1"}'
        mock_response.json.return_value = {"requestId": "req-1"}

        with patch("requests.post", return_value=mock_response) as mock_post:
            result = api.acknowledge_alert("OG-123")

        call_url = mock_post.call_args[0][0]
        assert "OG-123" in call_url
        assert "acknowledge" in call_url

        headers = mock_post.call_args[1]["headers"]
        assert "GenieKey test-key" in headers["Authorization"]

        assert result["acknowledged"] is True
        assert result["alert_id"] == "OG-123"
        assert result["request_id"] == "req-1"

    def test_acknowledge_missing_api_key_raises(self) -> None:
        api = OpsgenieAPI(_secrets(OPSGENIE_API_KEY=""))
        with self.assertRaises(RuntimeError) as ctx:
            api.acknowledge_alert("OG-123")
        assert "OPSGENIE_API_KEY" in str(ctx.exception)


class TestOpsgenieClose(unittest.TestCase):
    def test_close_posts_to_correct_url(self) -> None:
        api = OpsgenieAPI(_secrets())
        mock_response = MagicMock()
        mock_response.content = b'{"requestId": "req-2"}'
        mock_response.json.return_value = {"requestId": "req-2"}

        with patch("requests.post", return_value=mock_response) as mock_post:
            result = api.close_alert("OG-456", note="Resolved by oncall")

        call_url = mock_post.call_args[0][0]
        assert "OG-456" in call_url
        assert "close" in call_url

        body = mock_post.call_args[1]["json"]
        assert body.get("note") == "Resolved by oncall"

        assert result["closed"] is True
        assert result["alert_id"] == "OG-456"

    def test_close_without_note_sends_empty_body(self) -> None:
        api = OpsgenieAPI(_secrets())
        mock_response = MagicMock()
        mock_response.content = b"{}"
        mock_response.json.return_value = {}

        with patch("requests.post", return_value=mock_response) as mock_post:
            result = api.close_alert("OG-789")

        body = mock_post.call_args[1]["json"]
        assert "note" not in body
        assert result["closed"] is True


class TestOpsgenieAcknowledgeToolDryRun(unittest.TestCase):
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
                def __init__(self, *a, **kw):
                    pass

                def tool(self):
                    def d(fn):
                        return fn

                    return d

                def run(self, transport="stdio"):
                    return None

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

        with patch("requests.post") as mock_post:
            result = server.opsgenie_acknowledge_alert(alert_id="OG-999", dry_run=True)

        mock_post.assert_not_called()
        assert result["dry_run"] is True
        assert result["acknowledged"] is False
        assert result["alert_id"] == "OG-999"
