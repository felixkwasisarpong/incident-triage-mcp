from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from incident_triage_mcp.adapters.elk_logs_real import ElkLogsAPI
from incident_triage_mcp.secrets.loader import EnvSecretsLoader


class _ResponseStub:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class TestElkLogsAdapter(unittest.TestCase):
    def test_fetch_logs_normalizes_hits(self) -> None:
        payload = {
            "hits": {
                "hits": [
                    {
                        "_index": "logs-app-2026.01.01",
                        "_source": {
                            "@timestamp": "2026-01-01T00:05:00Z",
                            "service": {"name": "payments-api"},
                            "log": {"level": "error", "original": "timeout calling dependency"},
                            "trace": {"id": "trace-1"},
                        },
                    },
                    {
                        "_index": "logs-app-2026.01.01",
                        "_source": {
                            "@timestamp": "2026-01-01T00:04:00Z",
                            "service": {"name": "payments-api"},
                            "level": "warning",
                            "message": "retrying request",
                        },
                    },
                ]
            }
        }
        with patch.dict(
            os.environ,
            {
                "ELASTICSEARCH_BASE_URL": "http://localhost:9200",
                "ELASTICSEARCH_LOG_INDEX": "logs-*",
                "ELASTICSEARCH_SERVICE_FIELD": "service.name",
            },
            clear=True,
        ), patch(
            "incident_triage_mcp.adapters.elk_logs_real.requests.post",
            return_value=_ResponseStub(payload),
        ) as post_mock:
            adapter = ElkLogsAPI(EnvSecretsLoader())
            logs = adapter.fetch_logs(
                "payments-api",
                "2026-01-01T00:00:00Z",
                "2026-01-01T00:30:00Z",
                limit=25,
            )

        self.assertEqual(len(logs), 2)
        self.assertEqual(logs[0]["service"], "payments-api")
        self.assertEqual(logs[0]["level"], "error")
        self.assertEqual(logs[0]["trace_id"], "trace-1")
        self.assertEqual(logs[1]["message"], "retrying request")
        self.assertTrue(post_mock.call_args.args[0].endswith("/logs-*/_search"))
        query = post_mock.call_args.kwargs["json"]["query"]["bool"]["filter"]
        self.assertEqual(query[1]["bool"]["minimum_should_match"], 1)

    def test_fetch_logs_requires_both_basic_auth_values(self) -> None:
        with patch.dict(
            os.environ,
            {
                "ELASTICSEARCH_BASE_URL": "http://localhost:9200",
                "ELASTICSEARCH_USERNAME": "elastic",
            },
            clear=True,
        ):
            adapter = ElkLogsAPI(EnvSecretsLoader())
            with self.assertRaises(RuntimeError) as ctx:
                adapter.fetch_logs("payments-api", "2026-01-01T00:00:00Z", "2026-01-01T00:30:00Z")

        self.assertIn("ELASTICSEARCH_USERNAME", str(ctx.exception))
        self.assertIn("ELASTICSEARCH_PASSWORD", str(ctx.exception))

    def test_fetch_active_alerts_not_supported(self) -> None:
        adapter = ElkLogsAPI(EnvSecretsLoader())
        with self.assertRaises(RuntimeError) as ctx:
            adapter.fetch_active_alerts(["payments-api"], since_minutes=30, max_alerts=10)
        self.assertIn("does not implement fetch_active_alerts", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
