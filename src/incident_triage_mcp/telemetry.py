from __future__ import annotations

from datetime import datetime, timezone
import secrets
import time
from collections import deque
from dataclasses import dataclass
from threading import Lock
from typing import Any, Callable


@dataclass
class _Stats:
    calls_total: int = 0
    success_total: int = 0
    error_total: int = 0
    latency_total_ms: float = 0.0
    latency_max_ms: float = 0.0

    def observe(self, *, ok: bool, latency_ms: float) -> None:
        self.calls_total += 1
        if ok:
            self.success_total += 1
        else:
            self.error_total += 1
        self.latency_total_ms += latency_ms
        if latency_ms > self.latency_max_ms:
            self.latency_max_ms = latency_ms

    def to_dict(self) -> dict[str, Any]:
        avg = (self.latency_total_ms / self.calls_total) if self.calls_total else 0.0
        return {
            "calls_total": self.calls_total,
            "success_total": self.success_total,
            "error_total": self.error_total,
            "latency_avg_ms": round(avg, 3),
            "latency_max_ms": round(self.latency_max_ms, 3),
        }


class ServiceTelemetry:
    def __init__(
        self,
        service_name: str,
        *,
        trace_enabled: bool = True,
        trace_buffer_size: int = 200,
        trace_event_sink: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._service_name = service_name
        self._started_at = time.time()
        self._lock = Lock()
        self._tool_stats: dict[str, _Stats] = {}
        self._adapter_stats: dict[str, _Stats] = {}
        self._auth_denied_total = 0
        self._trace_enabled = bool(trace_enabled)
        self._trace_buffer_size = max(1, int(trace_buffer_size))
        self._trace_event_sink = trace_event_sink
        self._trace_spans_total = 0
        self._trace_dropped_total = 0
        self._trace_exported_total = 0
        self._trace_export_errors_total = 0
        self._trace_events: deque[dict[str, Any]] = deque(maxlen=self._trace_buffer_size)

    def new_trace_id(self) -> str:
        # 16 bytes => 32 hex chars (trace-id style width)
        return secrets.token_hex(16)

    def new_span_id(self) -> str:
        # 8 bytes => 16 hex chars (span-id style width)
        return secrets.token_hex(8)

    def observe_tool(self, tool_name: str, *, ok: bool, latency_ms: float) -> None:
        with self._lock:
            stats = self._tool_stats.setdefault(tool_name, _Stats())
            stats.observe(ok=ok, latency_ms=max(0.0, latency_ms))

    def observe_tool_with_trace(
        self,
        tool_name: str,
        *,
        ok: bool,
        latency_ms: float,
        trace_id: str,
        span_id: str,
        request_id: str | None = None,
        transport: str | None = None,
        error: str | None = None,
    ) -> None:
        event = {
            "timestamp_iso": datetime.now(timezone.utc).isoformat(),
            "tool_name": tool_name,
            "ok": bool(ok),
            "latency_ms": round(max(0.0, latency_ms), 3),
            "trace_id": trace_id,
            "span_id": span_id,
            "request_id": request_id,
            "transport": transport,
            "error": error,
        }
        should_export = False
        sink: Callable[[dict[str, Any]], None] | None = None
        with self._lock:
            stats = self._tool_stats.setdefault(tool_name, _Stats())
            stats.observe(ok=ok, latency_ms=max(0.0, latency_ms))
            self._trace_spans_total += 1
            if self._trace_enabled:
                if len(self._trace_events) >= self._trace_buffer_size:
                    self._trace_dropped_total += 1
                self._trace_events.append(event)
                if self._trace_event_sink is not None:
                    should_export = True
                    sink = self._trace_event_sink

        if should_export and sink is not None:
            export_ok = True
            try:
                sink(event)
            except Exception:
                export_ok = False
            with self._lock:
                if export_ok:
                    self._trace_exported_total += 1
                else:
                    self._trace_export_errors_total += 1

    def observe_adapter(
        self,
        provider: str,
        operation: str,
        *,
        ok: bool,
        latency_ms: float,
    ) -> None:
        key = f"{provider}.{operation}"
        with self._lock:
            stats = self._adapter_stats.setdefault(key, _Stats())
            stats.observe(ok=ok, latency_ms=max(0.0, latency_ms))

    def observe_auth_denied(self) -> None:
        with self._lock:
            self._auth_denied_total += 1

    def recent_traces(self, limit: int = 25) -> list[dict[str, Any]]:
        cap = max(1, int(limit))
        with self._lock:
            rows = list(self._trace_events)[-cap:]
        # Return newest first.
        rows.reverse()
        return rows

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            tool_calls = sum(v.calls_total for v in self._tool_stats.values())
            tool_errors = sum(v.error_total for v in self._tool_stats.values())
            adapter_calls = sum(v.calls_total for v in self._adapter_stats.values())
            adapter_errors = sum(v.error_total for v in self._adapter_stats.values())
            tools = {name: stats.to_dict() for name, stats in sorted(self._tool_stats.items())}
            adapters = {name: stats.to_dict() for name, stats in sorted(self._adapter_stats.items())}
            auth_denied = self._auth_denied_total
            trace_spans_total = self._trace_spans_total
            trace_dropped_total = self._trace_dropped_total
            trace_exported_total = self._trace_exported_total
            trace_export_errors_total = self._trace_export_errors_total
            trace_sink_configured = self._trace_event_sink is not None

        uptime = max(0.0, time.time() - self._started_at)
        return {
            "service": self._service_name,
            "uptime_seconds": round(uptime, 3),
            "totals": {
                "tool_calls_total": tool_calls,
                "tool_errors_total": tool_errors,
                "adapter_calls_total": adapter_calls,
                "adapter_errors_total": adapter_errors,
                "auth_denied_total": auth_denied,
            },
            "tracing": {
                "enabled": self._trace_enabled,
                "buffer_size": self._trace_buffer_size,
                "sink_configured": trace_sink_configured,
                "spans_total": trace_spans_total,
                "dropped_total": trace_dropped_total,
                "exported_total": trace_exported_total,
                "export_errors_total": trace_export_errors_total,
            },
            "tools": tools,
            "adapters": adapters,
        }

    def health(self) -> dict[str, Any]:
        snap = self.snapshot()
        totals = snap["totals"]
        status = "healthy" if totals["adapter_errors_total"] == 0 and totals["tool_errors_total"] == 0 else "degraded"
        return {
            "ok": True,
            "status": status,
            "service": snap["service"],
            "uptime_seconds": snap["uptime_seconds"],
            "totals": totals,
        }
