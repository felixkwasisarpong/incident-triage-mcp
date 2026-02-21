from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
import unittest
from unittest.mock import patch

from incident_triage_mcp.adapters.xray_real import XRayAPI
from incident_triage_mcp.secrets.loader import EnvSecretsLoader


class _XRayClientStub:
    def __init__(self) -> None:
        now = datetime.now(timezone.utc)
        self._summaries = [
            {
                "Id": "1-abcdef-0001",
                "StartTime": now - timedelta(minutes=3),
                "Duration": 0.82,
                "ResponseTime": 0.71,
                "HasError": True,
                "HasFault": False,
                "HasThrottle": False,
                "ServiceIds": [{"Name": "payments-api"}],
            },
            {
                "Id": "1-abcdef-0002",
                "StartTime": now - timedelta(minutes=2),
                "Duration": 0.21,
                "ResponseTime": 0.2,
                "HasError": False,
                "HasFault": False,
                "HasThrottle": False,
                "ServiceIds": [{"Name": "orders-api"}],
            },
        ]
        self.summary_calls: list[dict] = []
        self.batch_calls: list[dict] = []

    def get_trace_summaries(self, **kwargs):
        self.summary_calls.append(kwargs)
        return {"TraceSummaries": self._summaries}

    def batch_get_traces(self, **kwargs):
        self.batch_calls.append(kwargs)
        traces = []
        for trace_id in kwargs.get("TraceIds", []):
            doc = {
                "name": "payments-api",
                "http": {"request": {"method": "POST", "url": "https://payments.example/checkout"}},
            }
            traces.append({"Id": trace_id, "Segments": [{"Document": json.dumps(doc)}]})
        return {"Traces": traces}


class TestXRayAdapter(unittest.TestCase):
    def test_fetch_traces_filters_by_service_and_normalizes(self) -> None:
        client = _XRayClientStub()
        adapter = XRayAPI(EnvSecretsLoader(), xray_client=client)

        out = adapter.fetch_traces(
            "payments-api",
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:30:00Z",
            limit=10,
        )

        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["trace_id"], "1-abcdef-0001")
        self.assertEqual(out[0]["service"], "payments-api")
        self.assertEqual(out[0]["status"], "error")
        self.assertEqual(out[0]["http_method"], "POST")
        self.assertTrue(client.summary_calls)
        self.assertTrue(client.batch_calls)

    def test_fetch_traces_limit_zero_short_circuits(self) -> None:
        client = _XRayClientStub()
        adapter = XRayAPI(EnvSecretsLoader(), xray_client=client)
        out = adapter.fetch_traces(
            "payments-api",
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:30:00Z",
            limit=0,
        )
        self.assertEqual(out, [])
        self.assertEqual(client.summary_calls, [])

    def test_fetch_traces_rejects_invalid_window(self) -> None:
        adapter = XRayAPI(EnvSecretsLoader(), xray_client=_XRayClientStub())
        with self.assertRaises(RuntimeError) as ctx:
            adapter.fetch_traces(
                "payments-api",
                "2026-01-01T00:30:00Z",
                "2026-01-01T00:00:00Z",
                limit=5,
            )
        self.assertIn("end_iso must be after start_iso", str(ctx.exception))

    def test_partial_static_credentials_are_rejected(self) -> None:
        with patch.dict(os.environ, {"AWS_ACCESS_KEY_ID": "only-key"}, clear=True):
            adapter = XRayAPI(EnvSecretsLoader())
            with self.assertRaises(RuntimeError) as ctx:
                adapter.fetch_traces(
                    "payments-api",
                    "2026-01-01T00:00:00Z",
                    "2026-01-01T00:30:00Z",
                    limit=5,
                )

        self.assertIn("set both AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY", str(ctx.exception))

    def test_alert_and_health_methods_not_supported(self) -> None:
        adapter = XRayAPI(EnvSecretsLoader(), xray_client=_XRayClientStub())
        with self.assertRaises(RuntimeError):
            adapter.fetch_active_alerts(["payments-api"], since_minutes=30, max_alerts=10)
        with self.assertRaises(RuntimeError):
            adapter.health_snapshot("payments-api", "2026-01-01T00:00:00Z", "2026-01-01T00:30:00Z")


if __name__ == "__main__":
    unittest.main()
