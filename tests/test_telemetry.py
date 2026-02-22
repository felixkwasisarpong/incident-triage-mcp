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

    def test_recent_traces_tracks_latest_and_drop_count(self) -> None:
        telemetry = ServiceTelemetry("incident-triage-mcp", trace_enabled=True, trace_buffer_size=2)
        telemetry.observe_tool_with_trace(
            "ping",
            ok=True,
            latency_ms=1.0,
            trace_id="trace-1",
            span_id="span-1",
            request_id="req-1",
            transport="stdio",
        )
        telemetry.observe_tool_with_trace(
            "ping",
            ok=False,
            latency_ms=2.0,
            trace_id="trace-2",
            span_id="span-2",
            request_id="req-2",
            transport="stdio",
            error="RuntimeError: boom",
        )
        telemetry.observe_tool_with_trace(
            "ping",
            ok=True,
            latency_ms=3.0,
            trace_id="trace-3",
            span_id="span-3",
            request_id="req-3",
            transport="stdio",
        )

        traces = telemetry.recent_traces(limit=5)
        self.assertEqual(len(traces), 2)
        self.assertEqual(traces[0]["trace_id"], "trace-3")
        self.assertEqual(traces[1]["trace_id"], "trace-2")
        self.assertEqual(telemetry.snapshot()["tracing"]["dropped_total"], 1)

    def test_trace_sink_updates_export_counters(self) -> None:
        exported: list[dict[str, object]] = []

        def sink(event: dict[str, object]) -> None:
            exported.append(event)

        telemetry = ServiceTelemetry(
            "incident-triage-mcp",
            trace_enabled=True,
            trace_buffer_size=10,
            trace_event_sink=sink,
        )
        telemetry.observe_tool_with_trace(
            "ping",
            ok=True,
            latency_ms=1.5,
            trace_id="trace-a",
            span_id="span-a",
        )

        snap = telemetry.snapshot()
        self.assertEqual(len(exported), 1)
        self.assertTrue(snap["tracing"]["sink_configured"])
        self.assertEqual(snap["tracing"]["exported_total"], 1)
        self.assertEqual(snap["tracing"]["export_errors_total"], 0)

    def test_trace_sink_failures_are_counted(self) -> None:
        def sink(_event: dict[str, object]) -> None:
            raise RuntimeError("collector unavailable")

        telemetry = ServiceTelemetry(
            "incident-triage-mcp",
            trace_enabled=True,
            trace_buffer_size=10,
            trace_event_sink=sink,
        )
        telemetry.observe_tool_with_trace(
            "ping",
            ok=False,
            latency_ms=3.5,
            trace_id="trace-b",
            span_id="span-b",
            error="RuntimeError: boom",
        )

        snap = telemetry.snapshot()
        self.assertEqual(snap["tracing"]["exported_total"], 0)
        self.assertEqual(snap["tracing"]["export_errors_total"], 1)


if __name__ == "__main__":
    unittest.main()
