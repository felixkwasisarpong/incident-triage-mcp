from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
import unittest
from unittest.mock import patch

from incident_triage_mcp.adapters.opsgenie_real import OpsgenieAPI
from incident_triage_mcp.secrets.loader import EnvSecretsLoader


class _ResponseStub:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class TestOpsgenieAdapter(unittest.TestCase):
    def test_fetch_active_alerts_requires_api_key(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            adapter = OpsgenieAPI(EnvSecretsLoader())
            with self.assertRaises(RuntimeError) as ctx:
                adapter.fetch_active_alerts(["payments-api"], since_minutes=30, max_alerts=10)

        self.assertIn("OPSGENIE_API_KEY", str(ctx.exception))

    def test_fetch_active_alerts_normalizes_alerts(self) -> None:
        recent = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
        payload = {
            "data": [
                {
                    "id": "OG-1",
                    "tinyId": "101",
                    "message": "Payments API elevated 5xx",
                    "status": "open",
                    "priority": "P1",
                    "createdAt": recent,
                    "tags": ["service:payments-api"],
                },
                {
                    "id": "OG-2",
                    "message": "Orders API warning",
                    "status": "acknowledged",
                    "priority": "P3",
                    "createdAt": recent,
                    "tags": ["service:orders-api"],
                },
                {
                    "id": "OG-3",
                    "message": "Recovered",
                    "status": "closed",
                    "priority": "P2",
                    "createdAt": recent,
                    "tags": ["service:payments-api"],
                },
            ]
        }
        with patch.dict(
            os.environ,
            {
                "OPSGENIE_API_KEY": "key-abc",
                "OPSGENIE_BASE_URL": "https://api.opsgenie.com",
            },
            clear=True,
        ), patch(
            "incident_triage_mcp.adapters.opsgenie_real.requests.get",
            return_value=_ResponseStub(payload),
        ) as get_mock:
            adapter = OpsgenieAPI(EnvSecretsLoader())
            alerts = adapter.fetch_active_alerts(["payments-api"], since_minutes=30, max_alerts=10)

        self.assertEqual(len(alerts), 1)
        alert = alerts[0]
        self.assertEqual(alert["provider"], "opsgenie")
        self.assertEqual(alert["alert_id"], "OG-1")
        self.assertEqual(alert["service"], "payments-api")
        self.assertEqual(alert["status"], "triggered")
        self.assertEqual(alert["priority"], "P1")
        self.assertEqual(alert["signal"]["key"], "priority")
        self.assertTrue(get_mock.call_args.args[0].endswith("/v2/alerts"))
        self.assertEqual(get_mock.call_args.kwargs["headers"]["Authorization"], "GenieKey key-abc")

    def test_health_snapshot_not_supported(self) -> None:
        with patch.dict(os.environ, {"OPSGENIE_API_KEY": "key-abc"}, clear=True):
            adapter = OpsgenieAPI(EnvSecretsLoader())
            with self.assertRaises(RuntimeError) as ctx:
                adapter.health_snapshot(
                    "payments-api",
                    "2026-01-01T00:00:00Z",
                    "2026-01-01T00:30:00Z",
                )

        self.assertIn("does not implement health_snapshot", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
