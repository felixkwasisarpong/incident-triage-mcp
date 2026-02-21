from __future__ import annotations

import time
from dataclasses import dataclass
from threading import Lock
from typing import Any


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
    def __init__(self, service_name: str) -> None:
        self._service_name = service_name
        self._started_at = time.time()
        self._lock = Lock()
        self._tool_stats: dict[str, _Stats] = {}
        self._adapter_stats: dict[str, _Stats] = {}
        self._auth_denied_total = 0

    def observe_tool(self, tool_name: str, *, ok: bool, latency_ms: float) -> None:
        with self._lock:
            stats = self._tool_stats.setdefault(tool_name, _Stats())
            stats.observe(ok=ok, latency_ms=max(0.0, latency_ms))

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

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            tool_calls = sum(v.calls_total for v in self._tool_stats.values())
            tool_errors = sum(v.error_total for v in self._tool_stats.values())
            adapter_calls = sum(v.calls_total for v in self._adapter_stats.values())
            adapter_errors = sum(v.error_total for v in self._adapter_stats.values())
            tools = {name: stats.to_dict() for name, stats in sorted(self._tool_stats.items())}
            adapters = {name: stats.to_dict() for name, stats in sorted(self._adapter_stats.items())}
            auth_denied = self._auth_denied_total

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
