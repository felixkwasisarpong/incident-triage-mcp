from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

import requests

from incident_triage_mcp.secrets.loader import SecretsLoader


class PrometheusAPI:
    def __init__(self, secrets: SecretsLoader) -> None:
        self._secrets = secrets

    def _base_url(self) -> str:
        raw_url = (self._secrets.get("PROMETHEUS_BASE_URL", default="http://localhost:9090") or "").strip()
        if not raw_url:
            raise RuntimeError("Prometheus provider misconfigured: missing PROMETHEUS_BASE_URL")
        if not raw_url.startswith(("http://", "https://")):
            raw_url = f"http://{raw_url}"
        parsed = urlparse(raw_url)
        if not parsed.netloc:
            raise RuntimeError("Prometheus provider misconfigured: invalid PROMETHEUS_BASE_URL")
        base = f"{parsed.scheme}://{parsed.netloc}{parsed.path or ''}"
        return base.rstrip("/")

    def _timeout_seconds(self) -> float:
        raw = self._secrets.get("PROMETHEUS_HTTP_TIMEOUT_SECONDS", default="10") or "10"
        try:
            value = float(raw)
        except ValueError:
            value = 10.0
        return 10.0 if value <= 0 else value

    def _headers(self) -> dict[str, str]:
        token = (self._secrets.get("PROMETHEUS_BEARER_TOKEN") or "").strip()
        if not token:
            return {}
        return {"Authorization": f"Bearer {token}"}

    def _basic_auth(self) -> tuple[str, str] | None:
        username = self._secrets.get("PROMETHEUS_USERNAME")
        password = self._secrets.get("PROMETHEUS_PASSWORD")
        if bool(username) ^ bool(password):
            raise RuntimeError(
                "Prometheus provider misconfigured: set both PROMETHEUS_USERNAME and PROMETHEUS_PASSWORD."
            )
        if username and password:
            return username, password
        return None

    def _request(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        response = requests.get(
            f"{self._base_url()}{path}",
            params=params,
            headers=self._headers(),
            auth=self._basic_auth(),
            timeout=self._timeout_seconds(),
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("Prometheus API returned unexpected payload")
        if payload.get("status") != "success":
            error_type = payload.get("errorType") or "unknown_error"
            error = payload.get("error") or "request failed"
            raise RuntimeError(f"Prometheus API error ({error_type}): {error}")
        data = payload.get("data")
        if not isinstance(data, dict):
            return {}
        return data

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
    def _parse_optional_dt(value: Any) -> datetime | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _service_label_keys(self) -> list[str]:
        configured = (self._secrets.get("PROMETHEUS_SERVICE_LABEL", default="service") or "service").strip()
        keys = [configured, "service", "app", "application", "job"]
        out: list[str] = []
        for key in keys:
            lowered = key.lower()
            if lowered not in out:
                out.append(lowered)
        return out

    def _extract_service(self, labels: dict[str, Any], fallback: str | None = None) -> str:
        key_order = self._service_label_keys()
        label_lookup = {str(k).lower(): str(v) for k, v in labels.items()}
        for key in key_order:
            value = (label_lookup.get(key) or "").strip()
            if value:
                return value
        return fallback or "unknown"

    @staticmethod
    def _status_from_state(state: str) -> str:
        lowered = state.strip().lower()
        if lowered == "firing":
            return "triggered"
        if lowered == "pending":
            return "warning"
        return "resolved"

    @staticmethod
    def _priority_from_severity(severity: str | None) -> str:
        lowered = (severity or "").strip().lower()
        if lowered in {"critical", "sev1", "p1", "page"}:
            return "P1"
        if lowered in {"high", "warning", "sev2", "p2"}:
            return "P2"
        if lowered in {"low", "sev4", "p4"}:
            return "P4"
        return "P3"

    def fetch_active_alerts(
        self, services: list[str], since_minutes: int, max_alerts: int
    ) -> list[dict[str, Any]]:
        limit = max(0, max_alerts)
        if limit == 0:
            return []

        data = self._request("/api/v1/alerts", params={})
        raw_alerts = data.get("alerts")
        if not isinstance(raw_alerts, list):
            return []

        service_filters = [svc.strip() for svc in services if svc and svc.strip()]
        service_lookup = {svc.lower() for svc in service_filters}
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=max(1, since_minutes))

        out: list[dict[str, Any]] = []
        for raw in raw_alerts:
            if not isinstance(raw, dict):
                continue

            state = str(raw.get("state") or "firing")
            status = self._status_from_state(state)
            if status == "resolved":
                continue

            labels = raw.get("labels") if isinstance(raw.get("labels"), dict) else {}
            annotations = raw.get("annotations") if isinstance(raw.get("annotations"), dict) else {}
            fallback_service = service_filters[0] if service_filters else None
            service = self._extract_service(labels, fallback=fallback_service)
            if service_lookup and service.lower() not in service_lookup:
                continue

            active_at = self._parse_optional_dt(raw.get("activeAt"))
            if active_at and active_at < cutoff:
                continue
            started_at_iso = (active_at or cutoff).isoformat()

            alert_name = str(labels.get("alertname") or annotations.get("summary") or "Prometheus alert")
            fingerprint = str(raw.get("fingerprint") or f"prom_{service}_{alert_name}_{started_at_iso}")
            severity = str(labels.get("severity") or "")
            metric_hint = str(labels.get("__name__") or labels.get("alertname") or "prometheus_alert")

            out.append(
                {
                    "alert_id": fingerprint,
                    "provider": "prometheus",
                    "service": service,
                    "name": alert_name,
                    "status": status,
                    "started_at_iso": started_at_iso,
                    "priority": self._priority_from_severity(severity),
                    "signal": {
                        "key": metric_hint,
                        "value": state,
                    },
                }
            )
            if len(out) >= limit:
                break

        return out

    def _query_last_value(self, query: str, start: datetime, end: datetime, step_seconds: int) -> float | None:
        data = self._request(
            "/api/v1/query_range",
            params={
                "query": query,
                "start": start.timestamp(),
                "end": end.timestamp(),
                "step": step_seconds,
            },
        )
        result = data.get("result")
        if not isinstance(result, list):
            return None

        for series in result:
            if not isinstance(series, dict):
                continue
            values = series.get("values")
            if not isinstance(values, list):
                continue
            for point in reversed(values):
                if not isinstance(point, (list, tuple)) or len(point) < 2:
                    continue
                raw_value = point[1]
                if raw_value in {None, "NaN"}:
                    continue
                try:
                    return float(raw_value)
                except (TypeError, ValueError):
                    continue
        return None

    def _query_template(self, env_name: str, default: str, service: str) -> str:
        template = self._secrets.get(env_name, default=default) or default
        return template.replace("{service}", service)

    def health_snapshot(self, service: str, start_iso: str, end_iso: str) -> dict[str, Any]:
        start = self._parse_dt(start_iso)
        end = self._parse_dt(end_iso)
        if end <= start:
            raise RuntimeError("Prometheus query window is invalid: end must be after start")

        step_raw = self._secrets.get("PROMETHEUS_QUERY_STEP_SECONDS", default="60") or "60"
        try:
            step_seconds = int(step_raw)
        except ValueError:
            step_seconds = 60
        if step_seconds <= 0:
            step_seconds = 60

        error_rate_query = self._query_template(
            "PROMETHEUS_ERROR_RATE_QUERY",
            'sum(rate(http_server_errors_total{service="{service}"}[5m])) / '
            'clamp_min(sum(rate(http_server_requests_total{service="{service}"}[5m])), 1)',
            service,
        )
        latency_query = self._query_template(
            "PROMETHEUS_LATENCY_P95_MS_QUERY",
            'histogram_quantile(0.95, sum(rate(http_server_request_duration_seconds_bucket{service="{service}"}[5m])) by (le)) * 1000',
            service,
        )
        rps_query = self._query_template(
            "PROMETHEUS_RPS_QUERY",
            'sum(rate(http_server_requests_total{service="{service}"}[5m]))',
            service,
        )

        error_rate = self._query_last_value(error_rate_query, start, end, step_seconds)
        latency_p95_ms = self._query_last_value(latency_query, start, end, step_seconds)
        rps = self._query_last_value(rps_query, start, end, step_seconds)

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
            "provider": "prometheus",
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
