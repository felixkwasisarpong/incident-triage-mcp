from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
import unittest
from unittest.mock import patch

from incident_triage_mcp.adapters.pagerduty_real import PagerDutyAPI
from incident_triage_mcp.secrets.loader import EnvSecretsLoader


class _ResponseStub:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class TestPagerDutyAdapter(unittest.TestCase):
    def test_fetch_active_alerts_requires_token(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            adapter = PagerDutyAPI(EnvSecretsLoader())
            with self.assertRaises(RuntimeError) as ctx:
                adapter.fetch_active_alerts(["payments-api"], since_minutes=30, max_alerts=10)

        self.assertIn("PAGERDUTY_API_TOKEN", str(ctx.exception))

    def test_fetch_active_alerts_normalizes_incidents(self) -> None:
        recent = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
        payload = {
            "incidents": [
                {
                    "id": "PD-1",
                    "title": "Payments API elevated 5xx",
                    "status": "triggered",
                    "urgency": "high",
                    "created_at": recent,
                    "service": {"summary": "payments-api"},
                    "html_url": "https://pagerduty.example/incidents/PD-1",
                    "body": {"details": {"severity": "critical"}},
                },
                {
                    "id": "PD-2",
                    "title": "Orders API latency warning",
                    "status": "acknowledged",
                    "urgency": "low",
                    "created_at": recent,
                    "service": {"summary": "orders-api"},
                    "body": {"details": {"severity": "warning"}},
                },
                {
                    "id": "PD-3",
                    "title": "Recovered alert",
                    "status": "resolved",
                    "urgency": "high",
                    "created_at": recent,
                    "service": {"summary": "payments-api"},
                },
            ]
        }
        with patch.dict(
            os.environ,
            {
                "PAGERDUTY_API_TOKEN": "token-abc",
                "PAGERDUTY_BASE_URL": "https://api.pagerduty.com",
            },
            clear=True,
        ), patch(
            "incident_triage_mcp.adapters.pagerduty_real.requests.get",
            return_value=_ResponseStub(payload),
        ) as get_mock:
            adapter = PagerDutyAPI(EnvSecretsLoader())
            alerts = adapter.fetch_active_alerts(["payments-api"], since_minutes=30, max_alerts=10)

        self.assertEqual(len(alerts), 1)
        alert = alerts[0]
        self.assertEqual(alert["provider"], "pagerduty")
        self.assertEqual(alert["alert_id"], "PD-1")
        self.assertEqual(alert["service"], "payments-api")
        self.assertEqual(alert["status"], "triggered")
        self.assertEqual(alert["priority"], "P1")
        self.assertEqual(alert["signal"]["key"], "urgency")
        self.assertTrue(get_mock.call_args.args[0].endswith("/incidents"))
        self.assertEqual(get_mock.call_args.kwargs["headers"]["Authorization"], "Token token=token-abc")

    def test_health_snapshot_not_supported(self) -> None:
        with patch.dict(os.environ, {"PAGERDUTY_API_TOKEN": "token-abc"}, clear=True):
            adapter = PagerDutyAPI(EnvSecretsLoader())
            with self.assertRaises(RuntimeError) as ctx:
                adapter.health_snapshot(
                    "payments-api",
                    "2026-01-01T00:00:00Z",
                    "2026-01-01T00:30:00Z",
                )

        self.assertIn("does not implement health_snapshot", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
