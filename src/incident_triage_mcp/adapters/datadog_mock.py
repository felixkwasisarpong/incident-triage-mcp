from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any
import random


class DatadogMock:
    def fetch_active_alerts(self, services: List[str], since_minutes: int, max_alerts: int) -> List[Dict[str, Any]]:
        now = datetime.now(timezone.utc)
        out = []
        for svc in services or ["payments-api"]:
            out.append({
                "alert_id": f"dd_{random.randint(100,999)}",
                "provider": "datadog",
                "service": svc,
                "name": "5xx rate high",
                "status": "triggered",
                "started_at": (now - timedelta(minutes=random.randint(1, since_minutes))).isoformat(),
                "priority": "P1",
                "signal": {"metric": "http.server.errors", "value": 0.12, "threshold": 0.05},
            })
        return out[:max_alerts]

    def health_snapshot(self, service: str, start_iso: str, end_iso: str) -> Dict[str, Any]:
        return {
            "service": service,
            "window": {"start": start_iso, "end": end_iso},
            "status": "degraded",
            "indicators": {
                "error_rate": {"value": 0.12, "unit": "ratio"},
                "latency_p95_ms": {"value": 840},
                "rps": {"value": 2100},
            },
            "top_endpoints": [{"route": "POST /checkout", "error_rate": 0.22, "latency_p95_ms": 1200}],
        }

    def fetch_logs(
        self, service: str, start_iso: str, end_iso: str, limit: int = 100
    ) -> List[Dict[str, Any]]:
        now = datetime.now(timezone.utc)
        size = max(0, min(limit, 100))
        out: List[Dict[str, Any]] = []
        for idx in range(size):
            ts = (now - timedelta(seconds=idx * 5)).isoformat()
            out.append(
                {
                    "timestamp": ts,
                    "service": service,
                    "level": "error" if idx % 3 == 0 else "info",
                    "message": "dependency timeout while calling checkout-db" if idx % 3 == 0 else "request handled",
                    "source": "datadog-mock",
                    "trace_id": f"trace-{idx:04d}",
                }
            )
        return out
