from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
import unittest
from unittest.mock import patch

from incident_triage_mcp.adapters.prometheus_real import PrometheusAPI
from incident_triage_mcp.secrets.loader import EnvSecretsLoader


class _ResponseStub:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class TestPrometheusAdapter(unittest.TestCase):
    def test_fetch_active_alerts_normalizes_and_filters(self) -> None:
        now = datetime.now(timezone.utc)
        recent_1 = (now - timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
        recent_2 = (now - timedelta(minutes=4)).isoformat().replace("+00:00", "Z")
        recent_3 = (now - timedelta(minutes=3)).isoformat().replace("+00:00", "Z")
        recent_4 = (now - timedelta(minutes=2)).isoformat().replace("+00:00", "Z")
        payload = {
            "status": "success",
            "data": {
                "alerts": [
                    {
                        "state": "firing",
                        "activeAt": recent_1,
                        "fingerprint": "fp-1",
                        "labels": {
                            "alertname": "High5xxRate",
                            "service": "payments-api",
                            "severity": "critical",
                        },
                        "annotations": {"summary": "Payments 5xx high"},
                    },
                    {
                        "state": "pending",
                        "activeAt": recent_2,
                        "fingerprint": "fp-2",
                        "labels": {
                            "alertname": "LatencyWarning",
                            "service": "payments-api",
                            "severity": "warning",
                        },
                    },
                    {
                        "state": "inactive",
                        "activeAt": recent_3,
                        "fingerprint": "fp-3",
                        "labels": {
                            "alertname": "Recovered",
                            "service": "payments-api",
                        },
                    },
                    {
                        "state": "firing",
                        "activeAt": recent_4,
                        "fingerprint": "fp-4",
                        "labels": {
                            "alertname": "OrdersErrorSpike",
                            "service": "orders-api",
                            "severity": "critical",
                        },
                    },
                ]
            },
        }
        with patch.dict(
            os.environ,
            {
                "PROMETHEUS_BASE_URL": "http://prometheus:9090",
                "PROMETHEUS_BEARER_TOKEN": "token-123",
            },
            clear=True,
        ), patch(
            "incident_triage_mcp.adapters.prometheus_real.requests.get",
            return_value=_ResponseStub(payload),
        ) as get_mock:
            adapter = PrometheusAPI(EnvSecretsLoader())
            alerts = adapter.fetch_active_alerts(["payments-api"], since_minutes=30, max_alerts=10)

        self.assertEqual(len(alerts), 2)
        self.assertEqual(alerts[0]["provider"], "prometheus")
        self.assertEqual(alerts[0]["alert_id"], "fp-1")
        self.assertEqual(alerts[0]["priority"], "P1")
        self.assertEqual(alerts[0]["status"], "triggered")
        self.assertEqual(alerts[1]["status"], "warning")
        self.assertTrue(get_mock.call_args.args[0].endswith("/api/v1/alerts"))
        self.assertEqual(get_mock.call_args.kwargs["headers"]["Authorization"], "Bearer token-123")

    def test_fetch_active_alerts_limit_zero_skips_requests(self) -> None:
        with patch.dict(
            os.environ,
            {"PROMETHEUS_BASE_URL": "http://prometheus:9090"},
            clear=True,
        ), patch("incident_triage_mcp.adapters.prometheus_real.requests.get") as get_mock:
            adapter = PrometheusAPI(EnvSecretsLoader())
            alerts = adapter.fetch_active_alerts(["payments-api"], since_minutes=30, max_alerts=0)

        self.assertEqual(alerts, [])
        get_mock.assert_not_called()

    def test_health_snapshot_aggregates_query_range_results(self) -> None:
        responses = [
            _ResponseStub(
                {
                    "status": "success",
                    "data": {"result": [{"values": [[1760000000, "0.06"], [1760000060, "0.08"]]}]},
                }
            ),
            _ResponseStub(
                {
                    "status": "success",
                    "data": {"result": [{"values": [[1760000000, "850"], [1760000060, "920"]]}]},
                }
            ),
            _ResponseStub(
                {
                    "status": "success",
                    "data": {"result": [{"values": [[1760000000, "1500"], [1760000060, "1900"]]}]},
                }
            ),
        ]
        with patch.dict(
            os.environ,
            {"PROMETHEUS_BASE_URL": "http://prometheus:9090"},
            clear=True,
        ), patch(
            "incident_triage_mcp.adapters.prometheus_real.requests.get",
            side_effect=responses,
        ) as get_mock:
            adapter = PrometheusAPI(EnvSecretsLoader())
            snapshot = adapter.health_snapshot(
                "payments-api",
                "2026-01-01T00:00:00Z",
                "2026-01-01T00:30:00Z",
            )

        self.assertEqual(get_mock.call_count, 3)
        self.assertEqual(snapshot["provider"], "prometheus")
        self.assertEqual(snapshot["status"], "degraded")
        self.assertEqual(snapshot["indicators"]["error_rate"]["value"], 0.08)
        self.assertEqual(snapshot["indicators"]["latency_p95_ms"]["value"], 920.0)
        self.assertEqual(snapshot["indicators"]["rps"]["value"], 1900.0)
        for call in get_mock.call_args_list:
            self.assertTrue(call.args[0].endswith("/api/v1/query_range"))
            self.assertIn("query", call.kwargs["params"])

    def test_basic_auth_requires_both_username_and_password(self) -> None:
        with patch.dict(
            os.environ,
            {
                "PROMETHEUS_BASE_URL": "http://prometheus:9090",
                "PROMETHEUS_USERNAME": "alice",
            },
            clear=True,
        ):
            adapter = PrometheusAPI(EnvSecretsLoader())
            with self.assertRaises(RuntimeError) as ctx:
                adapter.fetch_active_alerts([], since_minutes=30, max_alerts=1)

        self.assertIn("PROMETHEUS_USERNAME", str(ctx.exception))
        self.assertIn("PROMETHEUS_PASSWORD", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
