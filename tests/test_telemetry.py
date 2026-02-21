from __future__ import annotations

import unittest

from incident_triage_mcp.telemetry import ServiceTelemetry


class TestServiceTelemetry(unittest.TestCase):
    def test_snapshot_tracks_tool_and_adapter_stats(self) -> None:
        telemetry = ServiceTelemetry("incident-triage-mcp")
        telemetry.observe_tool("ping", ok=True, latency_ms=2.0)
        telemetry.observe_tool("ping", ok=False, latency_ms=4.0)
        telemetry.observe_adapter("mock", "health_snapshot", ok=True, latency_ms=10.0)

        snap = telemetry.snapshot()
        self.assertEqual(snap["service"], "incident-triage-mcp")
        self.assertEqual(snap["totals"]["tool_calls_total"], 2)
        self.assertEqual(snap["totals"]["tool_errors_total"], 1)
        self.assertEqual(snap["totals"]["adapter_calls_total"], 1)
        self.assertIn("ping", snap["tools"])
        self.assertIn("mock.health_snapshot", snap["adapters"])

    def test_health_reports_degraded_on_errors(self) -> None:
        telemetry = ServiceTelemetry("incident-triage-mcp")
        telemetry.observe_tool("jira_create_ticket", ok=False, latency_ms=15.0)

        health = telemetry.health()
        self.assertTrue(health["ok"])
        self.assertEqual(health["status"], "degraded")


if __name__ == "__main__":
    unittest.main()
