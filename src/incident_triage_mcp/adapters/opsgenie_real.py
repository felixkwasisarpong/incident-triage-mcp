from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

import requests

from incident_triage_mcp.secrets.loader import SecretsLoader


class OpsgenieAPI:
    def __init__(self, secrets: SecretsLoader) -> None:
        self._secrets = secrets

    def _base_url(self) -> str:
        raw = (
            self._secrets.get("OPSGENIE_BASE_URL", default="https://api.opsgenie.com") or ""
        ).strip()
        if not raw:
            raise RuntimeError("Opsgenie provider misconfigured: missing OPSGENIE_BASE_URL")
        if not raw.startswith(("http://", "https://")):
            raw = f"https://{raw}"
        parsed = urlparse(raw)
        if not parsed.netloc:
            raise RuntimeError("Opsgenie provider misconfigured: invalid OPSGENIE_BASE_URL")
        base = f"{parsed.scheme}://{parsed.netloc}{parsed.path or ''}"
        return base.rstrip("/")

    def _timeout_seconds(self) -> float:
        raw = self._secrets.get("OPSGENIE_HTTP_TIMEOUT_SECONDS", default="10") or "10"
        try:
            value = float(raw)
        except ValueError:
            value = 10.0
        return 10.0 if value <= 0 else value

    def _headers(self) -> dict[str, str]:
        key = (self._secrets.get("OPSGENIE_API_KEY") or "").strip()
        if not key:
            raise RuntimeError("Opsgenie provider misconfigured: missing OPSGENIE_API_KEY")
        return {
            "Authorization": f"GenieKey {key}",
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
        if lowered in {"open", "triggered"}:
            return "triggered"
        if lowered in {"acknowledged", "seen"}:
            return "warning"
        return "resolved"

    @staticmethod
    def _priority(value: str) -> str:
        normalized = value.strip().upper()
        if normalized in {"P1", "P2", "P3", "P4"}:
            return normalized
        if normalized == "P5":
            return "P4"
        return "P3"

    @staticmethod
    def _service_name(alert: dict[str, Any], fallback: str | None = None) -> str:
        details = alert.get("details") if isinstance(alert.get("details"), dict) else {}
        for key in ("service", "service_name", "app", "application"):
            value = str(details.get(key) or "").strip()
            if value:
                return value

        tags = alert.get("tags") if isinstance(alert.get("tags"), list) else []
        for tag in tags:
            text = str(tag).strip()
            if not text or ":" not in text:
                continue
            left, right = text.split(":", 1)
            if left.strip().lower() in {"service", "svc"} and right.strip():
                return right.strip()

        source = str(alert.get("source") or "").strip()
        if source:
            return source
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
            f"{self._base_url()}/v2/alerts",
            headers=self._headers(),
            params={
                "query": "status:open OR status:acknowledged",
                "limit": min(max(limit * 2, 25), 100),
                "sort": "createdAt",
                "order": "desc",
            },
            timeout=self._timeout_seconds(),
        )
        response.raise_for_status()
        payload = response.json()
        alerts = payload.get("data") if isinstance(payload, dict) else []
        if not isinstance(alerts, list):
            return []

        out: list[dict[str, Any]] = []
        for alert in alerts:
            if not isinstance(alert, dict):
                continue
            status_raw = str(alert.get("status") or "open")
            status = self._status(status_raw)
            if status == "resolved":
                continue

            service_name = self._service_name(
                alert,
                fallback=service_filters[0] if service_filters else None,
            )
            if service_lookup and service_name.lower() not in service_lookup:
                continue

            started_at = self._parse_dt(alert.get("createdAt")) or self._parse_dt(
                alert.get("updatedAt")
            )
            if started_at and started_at < cutoff:
                continue
            started_at_iso = (started_at or cutoff).isoformat()

            priority_raw = str(alert.get("priority") or "P3")
            alert_id = str(alert.get("id") or alert.get("tinyId") or f"og_{len(out) + 1}")
            message = str(alert.get("message") or "Opsgenie alert")
            tiny_id = str(alert.get("tinyId") or "").strip() or None

            out.append(
                {
                    "alert_id": alert_id,
                    "provider": "opsgenie",
                    "service": service_name,
                    "name": message,
                    "status": status,
                    "started_at_iso": started_at_iso,
                    "priority": self._priority(priority_raw),
                    "signal": {
                        "key": "priority",
                        "value": priority_raw,
                        "tiny_id": tiny_id,
                    },
                }
            )
            if len(out) >= limit:
                break

        return out

    def acknowledge_alert(self, alert_id: str) -> dict[str, Any]:
        response = requests.post(
            f"{self._base_url()}/v2/alerts/{alert_id}/acknowledge",
            headers=self._headers(),
            json={"note": "Acknowledged via incident-triage-mcp"},
            timeout=self._timeout_seconds(),
        )
        response.raise_for_status()
        data = response.json() if response.content else {}
        return {
            "acknowledged": True,
            "alert_id": alert_id,
            "request_id": data.get("requestId"),
        }

    def close_alert(self, alert_id: str, note: str = "") -> dict[str, Any]:
        body: dict[str, Any] = {}
        if note:
            body["note"] = note
        response = requests.post(
            f"{self._base_url()}/v2/alerts/{alert_id}/close",
            headers=self._headers(),
            json=body,
            timeout=self._timeout_seconds(),
        )
        response.raise_for_status()
        data = response.json() if response.content else {}
        return {
            "closed": True,
            "alert_id": alert_id,
            "request_id": data.get("requestId"),
        }

    def health_snapshot(self, service: str, start_iso: str, end_iso: str) -> dict[str, Any]:
        raise RuntimeError(
            "Opsgenie adapter does not implement health_snapshot. "
            "Use METRICS_PROVIDER=datadog|cloudwatch|prometheus."
        )
