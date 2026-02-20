from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

import requests

from incident_triage_mcp.secrets.loader import SecretsLoader


class DatadogAPI:
    def __init__(self, secrets: SecretsLoader) -> None:
        self._secrets = secrets

    def _site_host(self) -> str:
        raw_site = (self._secrets.get("DATADOG_SITE", default="datadoghq.com") or "datadoghq.com").strip()
        parsed = urlparse(raw_site if "://" in raw_site else f"https://{raw_site}")
        host = (parsed.netloc or parsed.path or "datadoghq.com").strip().strip("/")
        return host if host.startswith("api.") else f"api.{host}"

    def _base_url(self) -> str:
        return f"https://{self._site_host()}"

    def _http_timeout_seconds(self) -> float:
        raw = self._secrets.get("DATADOG_HTTP_TIMEOUT_SECONDS", default="10") or "10"
        try:
            value = float(raw)
        except ValueError:
            value = 10.0
        return 10.0 if value <= 0 else value

    def _headers(self) -> dict[str, str]:
        api_key = self._secrets.get("DATADOG_API_KEY")
        app_key = self._secrets.get("DATADOG_APP_KEY")
        missing: list[str] = []
        if not api_key:
            missing.append("DATADOG_API_KEY")
        if not app_key:
            missing.append("DATADOG_APP_KEY")
        if missing:
            raise RuntimeError("Datadog provider misconfigured: missing " + ", ".join(missing))
        return {
            "DD-API-KEY": api_key,
            "DD-APPLICATION-KEY": app_key,
        }

    @staticmethod
    def _parse_dt(value: str) -> datetime:
        normalized = value.strip()
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise RuntimeError(f"Invalid ISO timestamp: {value}") from exc
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _to_iso(ts_seconds: int | float | None) -> str | None:
        if ts_seconds is None:
            return None
        try:
            ts_value = float(ts_seconds)
            if ts_value > 100_000_000_000:
                ts_value = ts_value / 1000.0
            dt = datetime.fromtimestamp(ts_value, tz=timezone.utc)
        except (TypeError, ValueError, OSError):
            return None
        return dt.isoformat()

    @staticmethod
    def _service_from_tags(tags: list[str], fallback: str | None = None) -> str:
        for tag in tags:
            if tag.startswith("service:"):
                value = tag.split(":", 1)[1].strip()
                if value:
                    return value
        return fallback or "unknown"

    @staticmethod
    def _priority(priority: Any, tags: list[str]) -> str:
        if isinstance(priority, str) and priority.upper() in {"P1", "P2", "P3", "P4"}:
            return priority.upper()
        if isinstance(priority, (int, float)):
            mapping = {1: "P1", 2: "P2", 3: "P3", 4: "P4", 5: "P4"}
            return mapping.get(int(priority), "P3")
        for tag in tags:
            if tag.startswith("priority:"):
                value = tag.split(":", 1)[1].strip().upper()
                if value in {"P1", "P2", "P3", "P4"}:
                    return value
        return "P3"

    @staticmethod
    def _status(value: str) -> str:
        normalized = value.strip().lower()
        if normalized in {"alert", "triggered"}:
            return "triggered"
        if normalized in {"warn", "warning"}:
            return "warning"
        return "resolved"

    def fetch_active_alerts(
        self, services: list[str], since_minutes: int, max_alerts: int
    ) -> list[dict[str, Any]]:
        limit = max(0, max_alerts)
        if limit == 0:
            return []
        service_filters = [svc.strip() for svc in services if svc and svc.strip()]
        query_terms = ["status:(Alert OR Warn)"]
        query_terms.extend(f"tag:service:{svc}" for svc in service_filters)
        query = " ".join(query_terms)

        response = requests.get(
            f"{self._base_url()}/api/v1/monitor/search",
            headers=self._headers(),
            params={"query": query},
            timeout=self._http_timeout_seconds(),
        )
        response.raise_for_status()
        payload = response.json()
        monitors = payload.get("monitors") if isinstance(payload, dict) else []
        if not isinstance(monitors, list):
            return []

        lower_filters = {svc.lower() for svc in service_filters}
        fallback_start = datetime.now(timezone.utc) - timedelta(minutes=max(1, since_minutes))
        alerts: list[dict[str, Any]] = []
        for monitor in monitors:
            if not isinstance(monitor, dict):
                continue
            state = str(monitor.get("overall_state") or monitor.get("status") or "").strip()
            status = self._status(state)
            if status == "resolved":
                continue

            tags = monitor.get("tags") if isinstance(monitor.get("tags"), list) else []
            tag_values = [str(tag) for tag in tags]
            service = self._service_from_tags(tag_values, fallback=service_filters[0] if service_filters else None)
            if lower_filters and service.lower() not in lower_filters:
                continue

            started_at = self._to_iso(monitor.get("last_triggered_ts")) or fallback_start.isoformat()
            alert_id = monitor.get("id") or monitor.get("monitor_id")
            alerts.append(
                {
                    "alert_id": f"dd_{alert_id}" if alert_id is not None else f"dd_{len(alerts) + 1}",
                    "provider": "datadog",
                    "service": service,
                    "name": str(monitor.get("name") or "Datadog monitor alert"),
                    "status": status,
                    "started_at_iso": started_at,
                    "priority": self._priority(monitor.get("priority"), tag_values),
                    "signal": {
                        "key": "monitor_state",
                        "value": state or "Alert",
                    },
                }
            )
            if len(alerts) >= limit:
                break

        return alerts

    def _query_latest_value(self, query: str, start_iso: str, end_iso: str) -> float | None:
        start_ts = int(self._parse_dt(start_iso).timestamp())
        end_ts = int(self._parse_dt(end_iso).timestamp())
        response = requests.get(
            f"{self._base_url()}/api/v1/query",
            headers=self._headers(),
            params={"from": start_ts, "to": end_ts, "query": query},
            timeout=self._http_timeout_seconds(),
        )
        response.raise_for_status()
        payload = response.json()
        series = payload.get("series") if isinstance(payload, dict) else None
        if not isinstance(series, list):
            return None
        for entry in series:
            if not isinstance(entry, dict):
                continue
            pointlist = entry.get("pointlist")
            if not isinstance(pointlist, list):
                continue
            for point in reversed(pointlist):
                if not isinstance(point, (list, tuple)) or len(point) < 2:
                    continue
                value = point[1]
                if value is None:
                    continue
                try:
                    return float(value)
                except (TypeError, ValueError):
                    continue
        return None

    def health_snapshot(self, service: str, start_iso: str, end_iso: str) -> dict[str, Any]:
        error_rate = self._query_latest_value(
            f"avg:trace.http.request.errors{{service:{service}}}.as_rate()",
            start_iso,
            end_iso,
        )
        latency_p95_ms = self._query_latest_value(
            f"p95:trace.http.request.duration{{service:{service}}}",
            start_iso,
            end_iso,
        )
        rps = self._query_latest_value(
            f"sum:trace.http.request.hits{{service:{service}}}.as_rate()",
            start_iso,
            end_iso,
        )

        status = "healthy"
        if (
            (error_rate is not None and error_rate >= 0.15)
            or (latency_p95_ms is not None and latency_p95_ms >= 1500)
        ):
            status = "critical"
        elif (
            (error_rate is not None and error_rate >= 0.05)
            or (latency_p95_ms is not None and latency_p95_ms >= 800)
        ):
            status = "degraded"

        return {
            "provider": "datadog",
            "service": service,
            "window": {"start": start_iso, "end": end_iso},
            "status": status,
            "indicators": {
                "error_rate": {"value": error_rate, "unit": "ratio"},
                "latency_p95_ms": {"value": latency_p95_ms},
                "rps": {"value": rps},
            },
            "top_endpoints": [],
        }
