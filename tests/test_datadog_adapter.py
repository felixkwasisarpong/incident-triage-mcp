from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from incident_triage_mcp.adapters.datadog_real import DatadogAPI
from incident_triage_mcp.secrets.loader import EnvSecretsLoader


class _ResponseStub:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class TestDatadogAdapter(unittest.TestCase):
    def test_fetch_active_alerts_requires_api_credentials(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            adapter = DatadogAPI(EnvSecretsLoader())
            with self.assertRaises(RuntimeError) as ctx:
                adapter.fetch_active_alerts(["payments-api"], since_minutes=30, max_alerts=10)

        self.assertIn("DATADOG_API_KEY", str(ctx.exception))
        self.assertIn("DATADOG_APP_KEY", str(ctx.exception))

    def test_fetch_active_alerts_normalizes_monitor_results(self) -> None:
        payload = {
            "monitors": [
                {
                    "id": 101,
                    "name": "5xx rate high",
                    "overall_state": "Alert",
                    "priority": 1,
                    "tags": ["service:payments-api", "env:prod"],
                    "last_triggered_ts": 1760000000,
                },
                {
                    "id": 102,
                    "name": "queue lag high",
                    "overall_state": "Warn",
                    "priority": 2,
                    "tags": ["service:orders-api"],
                    "last_triggered_ts": 1760000300,
                },
                {
                    "id": 103,
                    "name": "recovered monitor",
                    "overall_state": "OK",
                    "priority": 3,
                    "tags": ["service:payments-api"],
                    "last_triggered_ts": 1760000600,
                },
            ]
        }
        with patch.dict(
            os.environ,
            {
                "DATADOG_API_KEY": "api-key",
                "DATADOG_APP_KEY": "app-key",
                "DATADOG_SITE": "datadoghq.com",
            },
            clear=True,
        ), patch(
            "incident_triage_mcp.adapters.datadog_real.requests.get",
            return_value=_ResponseStub(payload),
        ) as get_mock:
            adapter = DatadogAPI(EnvSecretsLoader())
            alerts = adapter.fetch_active_alerts(["payments-api"], since_minutes=30, max_alerts=10)

        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["alert_id"], "dd_101")
        self.assertEqual(alerts[0]["provider"], "datadog")
        self.assertEqual(alerts[0]["service"], "payments-api")
        self.assertEqual(alerts[0]["status"], "triggered")
        self.assertEqual(alerts[0]["priority"], "P1")
        self.assertIn("started_at_iso", alerts[0])
        self.assertTrue(get_mock.call_args.args[0].endswith("/api/v1/monitor/search"))
        self.assertIn("tag:service:payments-api", get_mock.call_args.kwargs["params"]["query"])

    def test_health_snapshot_aggregates_datadog_query_series(self) -> None:
        error_rate_resp = _ResponseStub({"series": [{"pointlist": [[1760000000000, 0.09]]}]})
        latency_resp = _ResponseStub({"series": [{"pointlist": [[1760000000000, 920.0]]}]})
        rps_resp = _ResponseStub({"series": [{"pointlist": [[1760000000000, 2100.0]]}]})
        with patch.dict(
            os.environ,
            {
                "DATADOG_API_KEY": "api-key",
                "DATADOG_APP_KEY": "app-key",
            },
            clear=True,
        ), patch(
            "incident_triage_mcp.adapters.datadog_real.requests.get",
            side_effect=[error_rate_resp, latency_resp, rps_resp],
        ) as get_mock:
            adapter = DatadogAPI(EnvSecretsLoader())
            snapshot = adapter.health_snapshot(
                "payments-api",
                "2026-01-01T00:00:00Z",
                "2026-01-01T00:30:00Z",
            )

        self.assertEqual(get_mock.call_count, 3)
        self.assertEqual(snapshot["provider"], "datadog")
        self.assertEqual(snapshot["service"], "payments-api")
        self.assertEqual(snapshot["status"], "degraded")
        self.assertEqual(snapshot["indicators"]["error_rate"]["value"], 0.09)
        self.assertEqual(snapshot["indicators"]["latency_p95_ms"]["value"], 920.0)
        self.assertEqual(snapshot["indicators"]["rps"]["value"], 2100.0)
        for call in get_mock.call_args_list:
            self.assertTrue(call.args[0].endswith("/api/v1/query"))
            self.assertIn("query", call.kwargs["params"])


if __name__ == "__main__":
    unittest.main()
