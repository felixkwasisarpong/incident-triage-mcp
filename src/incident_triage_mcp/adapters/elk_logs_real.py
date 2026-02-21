from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import requests

from incident_triage_mcp.secrets.loader import SecretsLoader


class ElkLogsAPI:
    def __init__(self, secrets: SecretsLoader) -> None:
        self._secrets = secrets

    def _base_url(self) -> str:
        raw_url = (self._secrets.get("ELASTICSEARCH_BASE_URL", default="http://localhost:9200") or "").strip()
        if not raw_url:
            raise RuntimeError("ELK logs provider misconfigured: missing ELASTICSEARCH_BASE_URL")
        if not raw_url.startswith(("http://", "https://")):
            raw_url = f"http://{raw_url}"
        parsed = urlparse(raw_url)
        if not parsed.netloc:
            raise RuntimeError("ELK logs provider misconfigured: invalid ELASTICSEARCH_BASE_URL")
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path or ''}".rstrip("/")

    def _index_pattern(self) -> str:
        return (self._secrets.get("ELASTICSEARCH_LOG_INDEX", default="logs-*") or "logs-*").strip() or "logs-*"

    def _timestamp_field(self) -> str:
        return (
            self._secrets.get("ELASTICSEARCH_TIMESTAMP_FIELD", default="@timestamp")
            or "@timestamp"
        ).strip() or "@timestamp"

    def _service_field(self) -> str:
        return (
            self._secrets.get("ELASTICSEARCH_SERVICE_FIELD", default="service.name")
            or "service.name"
        ).strip() or "service.name"

    def _message_fields(self) -> list[str]:
        raw = self._secrets.get(
            "ELASTICSEARCH_MESSAGE_FIELDS",
            default="message,log.original,event.original",
        ) or "message,log.original,event.original"
        fields = [f.strip() for f in raw.split(",") if f.strip()]
        return fields or ["message"]

    def _timeout_seconds(self) -> float:
        raw = self._secrets.get("ELASTICSEARCH_HTTP_TIMEOUT_SECONDS", default="10") or "10"
        try:
            value = float(raw)
        except ValueError:
            value = 10.0
        return 10.0 if value <= 0 else value

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        api_key = (self._secrets.get("ELASTICSEARCH_API_KEY") or "").strip()
        if api_key:
            headers["Authorization"] = f"ApiKey {api_key}"
        return headers

    def _auth(self) -> tuple[str, str] | None:
        username = self._secrets.get("ELASTICSEARCH_USERNAME")
        password = self._secrets.get("ELASTICSEARCH_PASSWORD")
        if bool(username) ^ bool(password):
            raise RuntimeError(
                "ELK logs provider misconfigured: set both ELASTICSEARCH_USERNAME and "
                "ELASTICSEARCH_PASSWORD for basic auth."
            )
        if username and password:
            return username, password
        return None

    @staticmethod
    def _parse_iso(value: str) -> datetime:
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
    def _get_nested(source: dict[str, Any], dotted_path: str) -> Any:
        current: Any = source
        for part in dotted_path.split("."):
            if not isinstance(current, dict):
                return None
            current = current.get(part)
            if current is None:
                return None
        return current

    def fetch_logs(
        self, service: str, start_iso: str, end_iso: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        size = min(max(limit, 0), 1000)
        if size == 0:
            return []

        start = self._parse_iso(start_iso)
        end = self._parse_iso(end_iso)
        if end <= start:
            raise RuntimeError("Invalid log window: end_iso must be after start_iso")

        timestamp_field = self._timestamp_field()
        service_field = self._service_field()
        service_keyword = f"{service_field}.keyword"

        query_body = {
            "size": size,
            "sort": [{timestamp_field: {"order": "desc"}}],
            "query": {
                "bool": {
                    "filter": [
                        {
                            "range": {
                                timestamp_field: {
                                    "gte": start.isoformat(),
                                    "lte": end.isoformat(),
                                }
                            }
                        },
                        {
                            "bool": {
                                "should": [
                                    {"term": {service_field: service}},
                                    {"term": {service_keyword: service}},
                                    {"match_phrase": {service_field: service}},
                                ],
                                "minimum_should_match": 1,
                            }
                        },
                    ]
                }
            },
        }

        response = requests.post(
            f"{self._base_url()}/{self._index_pattern()}/_search",
            headers=self._headers(),
            auth=self._auth(),
            json=query_body,
            timeout=self._timeout_seconds(),
        )
        response.raise_for_status()
        payload = response.json()

        hits_block = payload.get("hits") if isinstance(payload, dict) else {}
        hits = hits_block.get("hits") if isinstance(hits_block, dict) else []
        if not isinstance(hits, list):
            return []

        message_fields = self._message_fields()
        out: list[dict[str, Any]] = []
        for hit in hits:
            if not isinstance(hit, dict):
                continue
            source = hit.get("_source") if isinstance(hit.get("_source"), dict) else {}
            if not source:
                continue

            timestamp = self._get_nested(source, timestamp_field) or source.get("@timestamp")
            level = (
                self._get_nested(source, "log.level")
                or source.get("level")
                or source.get("severity")
                or "info"
            )
            message = None
            for field in message_fields:
                value = self._get_nested(source, field)
                if value is not None and str(value).strip():
                    message = str(value).strip()
                    break
            if message is None:
                message = str(source)

            trace_id = self._get_nested(source, "trace.id") or self._get_nested(source, "traceId")
            out.append(
                {
                    "timestamp": str(timestamp) if timestamp is not None else None,
                    "service": str(self._get_nested(source, service_field) or service),
                    "level": str(level),
                    "message": message,
                    "source": str(hit.get("_index") or self._index_pattern()),
                    "trace_id": str(trace_id) if trace_id is not None else None,
                }
            )
        return out

    def fetch_active_alerts(
        self, services: list[str], since_minutes: int, max_alerts: int
    ) -> list[dict[str, Any]]:
        raise RuntimeError(
            "ELK logs adapter does not implement fetch_active_alerts. "
            "Use ALERTS_PROVIDER=datadog|cloudwatch|prometheus|pagerduty|opsgenie."
        )

    def health_snapshot(self, service: str, start_iso: str, end_iso: str) -> dict[str, Any]:
        raise RuntimeError(
            "ELK logs adapter does not implement health_snapshot. "
            "Use METRICS_PROVIDER=datadog|cloudwatch|prometheus."
        )
