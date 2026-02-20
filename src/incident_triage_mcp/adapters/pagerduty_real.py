from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

import requests

from incident_triage_mcp.secrets.loader import SecretsLoader


class PagerDutyAPI:
    def __init__(self, secrets: SecretsLoader) -> None:
        self._secrets = secrets

    def _base_url(self) -> str:
        raw = (self._secrets.get("PAGERDUTY_BASE_URL", default="https://api.pagerduty.com") or "").strip()
        if not raw:
            raise RuntimeError("PagerDuty provider misconfigured: missing PAGERDUTY_BASE_URL")
        if not raw.startswith(("http://", "https://")):
            raw = f"https://{raw}"
        parsed = urlparse(raw)
        if not parsed.netloc:
            raise RuntimeError("PagerDuty provider misconfigured: invalid PAGERDUTY_BASE_URL")
        base = f"{parsed.scheme}://{parsed.netloc}{parsed.path or ''}"
        return base.rstrip("/")

    def _timeout_seconds(self) -> float:
        raw = self._secrets.get("PAGERDUTY_HTTP_TIMEOUT_SECONDS", default="10") or "10"
        try:
            value = float(raw)
        except ValueError:
            value = 10.0
        return 10.0 if value <= 0 else value

    def _headers(self) -> dict[str, str]:
        token = (self._secrets.get("PAGERDUTY_API_TOKEN") or "").strip()
        if not token:
            raise RuntimeError("PagerDuty provider misconfigured: missing PAGERDUTY_API_TOKEN")
        return {
            "Accept": "application/vnd.pagerduty+json;version=2",
            "Authorization": f"Token token={token}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _parse_dt(value: Any) -> datetime | None:
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

    @staticmethod
    def _status(value: str) -> str:
        lowered = value.strip().lower()
        if lowered in {"triggered", "firing"}:
            return "triggered"
        if lowered in {"acknowledged", "warning"}:
            return "warning"
        return "resolved"

    @staticmethod
    def _priority(urgency: str, severity: str) -> str:
        urgency_value = urgency.strip().lower()
        severity_value = severity.strip().lower()
        if urgency_value == "high" or severity_value in {"critical", "error"}:
            return "P1"
        if urgency_value == "low" and severity_value in {"warning", "info"}:
            return "P3"
        if severity_value in {"warning", "warn"}:
            return "P2"
        return "P2"

    @staticmethod
    def _service_name(incident: dict[str, Any], fallback: str | None = None) -> str:
        service = incident.get("service")
        if isinstance(service, dict):
            summary = str(service.get("summary") or "").strip()
            if summary:
                return summary
        return fallback or "unknown"

    def fetch_active_alerts(
        self, services: list[str], since_minutes: int, max_alerts: int
    ) -> list[dict[str, Any]]:
        limit = max(0, max_alerts)
        if limit == 0:
            return []

        service_filters = [svc.strip() for svc in services if svc and svc.strip()]
        service_lookup = {svc.lower() for svc in service_filters}
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=max(1, since_minutes))

        response = requests.get(
            f"{self._base_url()}/incidents",
            headers=self._headers(),
            params={
                "statuses[]": ["triggered", "acknowledged"],
                "limit": min(max(limit * 2, 25), 100),
                "sort_by": "created_at:desc",
            },
            timeout=self._timeout_seconds(),
        )
        response.raise_for_status()
        payload = response.json()
        incidents = payload.get("incidents") if isinstance(payload, dict) else []
        if not isinstance(incidents, list):
            return []

        out: list[dict[str, Any]] = []
        for incident in incidents:
            if not isinstance(incident, dict):
                continue
            status = self._status(str(incident.get("status") or "triggered"))
            if status == "resolved":
                continue

            service_name = self._service_name(
                incident,
                fallback=service_filters[0] if service_filters else None,
            )
            if service_lookup and service_name.lower() not in service_lookup:
                continue

            started_at = self._parse_dt(incident.get("created_at")) or self._parse_dt(incident.get("last_status_change_at"))
            if started_at and started_at < cutoff:
                continue
            started_at_iso = (started_at or cutoff).isoformat()

            urgency = str(incident.get("urgency") or "")
            body = incident.get("body") if isinstance(incident.get("body"), dict) else {}
            details = body.get("details") if isinstance(body.get("details"), dict) else {}
            severity = str(details.get("severity") or "")
            title = str(incident.get("title") or "PagerDuty incident")
            incident_id = str(incident.get("id") or f"pd_{len(out) + 1}")
            html_url = str(incident.get("html_url") or "")

            out.append(
                {
                    "alert_id": incident_id,
                    "provider": "pagerduty",
                    "service": service_name,
                    "name": title,
                    "status": status,
                    "started_at_iso": started_at_iso,
                    "priority": self._priority(urgency, severity),
                    "signal": {
                        "key": "urgency",
                        "value": urgency or "unknown",
                        "url": html_url or None,
                    },
                }
            )
            if len(out) >= limit:
                break

        return out

    def health_snapshot(self, service: str, start_iso: str, end_iso: str) -> dict[str, Any]:
        raise RuntimeError(
            "PagerDuty adapter does not implement health_snapshot. "
            "Use METRICS_PROVIDER=datadog|cloudwatch|prometheus."
        )
