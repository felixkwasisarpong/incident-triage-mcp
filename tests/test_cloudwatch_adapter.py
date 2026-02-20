from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
import unittest
from unittest.mock import patch

from incident_triage_mcp.adapters.cloudwatch_real import CloudWatchAPI
from incident_triage_mcp.secrets.loader import EnvSecretsLoader


class _CloudWatchClientStub:
    def __init__(self, alarms_pages: list[dict], metric_values: dict[str, float | None]) -> None:
        self._alarms_pages = alarms_pages
        self._metric_values = metric_values
        self._page_index = 0
        self.metric_calls: list[dict] = []
        self.describe_calls: list[dict] = []

    def describe_alarms(self, **kwargs):
        self.describe_calls.append(kwargs)
        if self._page_index >= len(self._alarms_pages):
            return {"MetricAlarms": []}
        page = self._alarms_pages[self._page_index]
        self._page_index += 1
        return page

    def get_metric_statistics(self, **kwargs):
        self.metric_calls.append(kwargs)
        metric_name = kwargs.get("MetricName")
        value = self._metric_values.get(metric_name)
        if value is None:
            return {"Datapoints": []}
        ts = datetime.now(timezone.utc) - timedelta(minutes=1)
        if kwargs.get("ExtendedStatistics"):
            stat = kwargs["ExtendedStatistics"][0]
        else:
            stat = kwargs["Statistics"][0]
        return {"Datapoints": [{"Timestamp": ts, stat: value}]}


class TestCloudWatchAdapter(unittest.TestCase):
    def test_fetch_active_alerts_filters_service_and_window(self) -> None:
        now = datetime.now(timezone.utc)
        old = now - timedelta(hours=3)
        recent = now - timedelta(minutes=5)
        client = _CloudWatchClientStub(
            alarms_pages=[
                {
                    "MetricAlarms": [
                        {
                            "AlarmName": "payments-api critical errors",
                            "AlarmArn": "arn:aws:cloudwatch:alarm/payments-errors",
                            "StateValue": "ALARM",
                            "StateUpdatedTimestamp": recent,
                            "MetricName": "ErrorRate",
                            "Dimensions": [{"Name": "Service", "Value": "payments-api"}],
                        },
                        {
                            "AlarmName": "orders-api critical errors",
                            "AlarmArn": "arn:aws:cloudwatch:alarm/orders-errors",
                            "StateValue": "ALARM",
                            "StateUpdatedTimestamp": recent,
                            "MetricName": "ErrorRate",
                            "Dimensions": [{"Name": "Service", "Value": "orders-api"}],
                        },
                        {
                            "AlarmName": "payments-api stale alarm",
                            "AlarmArn": "arn:aws:cloudwatch:alarm/payments-stale",
                            "StateValue": "ALARM",
                            "StateUpdatedTimestamp": old,
                            "MetricName": "ErrorRate",
                            "Dimensions": [{"Name": "Service", "Value": "payments-api"}],
                        },
                    ]
                }
            ],
            metric_values={},
        )
        adapter = CloudWatchAPI(EnvSecretsLoader(), cloudwatch_client=client)

        alerts = adapter.fetch_active_alerts(["payments-api"], since_minutes=30, max_alerts=10)

        self.assertEqual(len(alerts), 1)
        alert = alerts[0]
        self.assertEqual(alert["provider"], "cloudwatch")
        self.assertEqual(alert["service"], "payments-api")
        self.assertEqual(alert["status"], "triggered")
        self.assertEqual(alert["priority"], "P1")
        self.assertEqual(client.describe_calls[0]["StateValue"], "ALARM")

    def test_fetch_active_alerts_respects_max_alerts(self) -> None:
        now = datetime.now(timezone.utc) - timedelta(minutes=2)
        client = _CloudWatchClientStub(
            alarms_pages=[
                {
                    "MetricAlarms": [
                        {
                            "AlarmName": "payments-api critical one",
                            "AlarmArn": "arn:1",
                            "StateValue": "ALARM",
                            "StateUpdatedTimestamp": now,
                            "MetricName": "ErrorRate",
                            "Dimensions": [{"Name": "Service", "Value": "payments-api"}],
                        },
                        {
                            "AlarmName": "payments-api critical two",
                            "AlarmArn": "arn:2",
                            "StateValue": "ALARM",
                            "StateUpdatedTimestamp": now,
                            "MetricName": "ErrorRate",
                            "Dimensions": [{"Name": "Service", "Value": "payments-api"}],
                        },
                    ]
                }
            ],
            metric_values={},
        )
        adapter = CloudWatchAPI(EnvSecretsLoader(), cloudwatch_client=client)

        alerts = adapter.fetch_active_alerts(["payments-api"], since_minutes=30, max_alerts=1)

        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["alert_id"], "arn:1")

    def test_health_snapshot_builds_indicators_and_status(self) -> None:
        client = _CloudWatchClientStub(
            alarms_pages=[{"MetricAlarms": []}],
            metric_values={
                "ErrorRate": 0.08,
                "LatencyP95": 920.0,
                "RequestsPerSecond": 1800.0,
            },
        )
        adapter = CloudWatchAPI(EnvSecretsLoader(), cloudwatch_client=client)

        snapshot = adapter.health_snapshot(
            "payments-api",
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:30:00Z",
        )

        self.assertEqual(snapshot["provider"], "cloudwatch")
        self.assertEqual(snapshot["service"], "payments-api")
        self.assertEqual(snapshot["status"], "degraded")
        self.assertEqual(snapshot["indicators"]["error_rate"]["value"], 0.08)
        self.assertEqual(snapshot["indicators"]["latency_p95_ms"]["value"], 920.0)
        self.assertEqual(snapshot["indicators"]["rps"]["value"], 1800.0)
        self.assertEqual(len(client.metric_calls), 3)
        for call in client.metric_calls:
            self.assertEqual(call["Namespace"], "IncidentTriage")
            self.assertEqual(call["Dimensions"], [{"Name": "Service", "Value": "payments-api"}])

    def test_client_rejects_partial_static_credentials(self) -> None:
        with patch.dict(os.environ, {"AWS_ACCESS_KEY_ID": "only-key"}, clear=True):
            adapter = CloudWatchAPI(EnvSecretsLoader())
            with self.assertRaises(RuntimeError) as ctx:
                adapter.fetch_active_alerts([], since_minutes=30, max_alerts=1)

        self.assertIn("set both AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
