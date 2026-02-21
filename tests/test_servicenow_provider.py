from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from incident_triage_mcp.adapters.servicenow import ServiceNowProvider


class _ResponseStub:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class TestServiceNowProvider(unittest.TestCase):
    def test_constructor_requires_env(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError) as ctx:
                ServiceNowProvider()
        self.assertIn("SERVICENOW_BASE_URL", str(ctx.exception))

    def test_create_issue_maps_payload_and_response(self) -> None:
        payload = {"result": {"sys_id": "abc123", "number": "INC0012345"}}
        with patch.dict(
            os.environ,
            {
                "SERVICENOW_BASE_URL": "https://acme.service-now.com",
                "SERVICENOW_USERNAME": "bot_user",
                "SERVICENOW_PASSWORD": "bot_pass",
            },
            clear=True,
        ), patch(
            "incident_triage_mcp.adapters.servicenow.requests.post",
            return_value=_ResponseStub(payload),
        ) as post_mock:
            provider = ServiceNowProvider()
            out = provider.create_issue(
                {
                    "title": "P1 payments outage",
                    "priority": "P1",
                    "description_md": "summary",
                    "labels": ["incident", "payments-api"],
                    "idempotency_key": "INC-123-1",
                }
            )

        self.assertTrue(out["created"])
        self.assertEqual(out["provider"], "servicenow")
        self.assertEqual(out["issue_key"], "INC0012345")
        self.assertEqual(out["sys_id"], "abc123")
        self.assertIn("nav_to.do?uri=incident.do?sys_id=abc123", out["browse_url"])
        call = post_mock.call_args
        self.assertTrue(call.args[0].endswith("/api/now/table/incident"))
        self.assertEqual(call.kwargs["auth"], ("bot_user", "bot_pass"))
        self.assertEqual(call.kwargs["json"]["urgency"], "1")
        self.assertEqual(call.kwargs["json"]["impact"], "1")
        self.assertEqual(call.kwargs["json"]["u_idempotency_key"], "INC-123-1")

    def test_validate_returns_identity(self) -> None:
        payload = {
            "result": [
                {
                    "sys_id": "user-1",
                    "user_name": "incident.bot",
                    "name": "Incident Bot",
                    "email": "incident.bot@example.com",
                }
            ]
        }
        with patch.dict(
            os.environ,
            {
                "SERVICENOW_BASE_URL": "https://acme.service-now.com",
                "SERVICENOW_USERNAME": "bot_user",
                "SERVICENOW_PASSWORD": "bot_pass",
            },
            clear=True,
        ), patch(
            "incident_triage_mcp.adapters.servicenow.requests.get",
            return_value=_ResponseStub(payload),
        ) as get_mock:
            out = ServiceNowProvider().validate()

        self.assertEqual(out["accountId"], "user-1")
        self.assertEqual(out["displayName"], "Incident Bot")
        self.assertEqual(out["provider"], "servicenow")
        self.assertTrue(get_mock.call_args.args[0].endswith("/api/now/table/sys_user"))

    def test_list_methods_return_compatible_shapes(self) -> None:
        with patch.dict(
            os.environ,
            {
                "SERVICENOW_BASE_URL": "https://acme.service-now.com",
                "SERVICENOW_USERNAME": "bot_user",
                "SERVICENOW_PASSWORD": "bot_pass",
                "SERVICENOW_ISSUE_TYPES": "Incident,Problem,Request",
            },
            clear=True,
        ):
            provider = ServiceNowProvider()
            projects = provider.list_projects()
            issue_types = provider.list_issue_types("SNOW")

        self.assertEqual(len(projects), 1)
        self.assertEqual(projects[0]["key"], "SNOW")
        self.assertEqual([item["name"] for item in issue_types], ["Incident", "Problem", "Request"])


if __name__ == "__main__":
    unittest.main()
