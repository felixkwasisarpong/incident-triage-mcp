from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any

from incident_triage_mcp.secrets.loader import SecretsLoader


class XRayAPI:
    def __init__(self, secrets: SecretsLoader, xray_client: Any | None = None) -> None:
        self._secrets = secrets
        self._xray_client = xray_client

    def _region(self) -> str:
        return (
            self._secrets.get("XRAY_REGION")
            or self._secrets.get("AWS_REGION")
            or self._secrets.get("AWS_DEFAULT_REGION")
            or self._secrets.get("S3_REGION")
            or "us-east-1"
        )

    def _client(self) -> Any:
        if self._xray_client is not None:
            return self._xray_client

        access_key = self._secrets.get("AWS_ACCESS_KEY_ID")
        secret_key = self._secrets.get("AWS_SECRET_ACCESS_KEY")
        session_token = self._secrets.get("AWS_SESSION_TOKEN")

        if bool(access_key) ^ bool(secret_key):
            raise RuntimeError(
                "X-Ray provider misconfigured: set both AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY, "
                "or rely on IAM role/default credential chain."
            )

        try:
            import boto3  # type: ignore
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "X-Ray provider requires optional dependency 'boto3'. "
                "Install with: pip install 'incident-triage-mcp[aws]'"
            ) from exc

        session_kwargs: dict[str, Any] = {"region_name": self._region()}
        if access_key and secret_key:
            session_kwargs["aws_access_key_id"] = access_key
            session_kwargs["aws_secret_access_key"] = secret_key
            if session_token:
                session_kwargs["aws_session_token"] = session_token

        session = boto3.session.Session(**session_kwargs)
        self._xray_client = session.client("xray")
        return self._xray_client

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
    def _to_iso(value: datetime | None) -> str | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()

    @staticmethod
    def _summary_services(summary: dict[str, Any]) -> list[str]:
        service_ids = summary.get("ServiceIds") if isinstance(summary.get("ServiceIds"), list) else []
        out: list[str] = []
        for item in service_ids:
            if not isinstance(item, dict):
                continue
            name = str(item.get("Name") or "").strip()
            if name:
                out.append(name)
        return out

    @staticmethod
    def _safe_segment_doc(trace: dict[str, Any]) -> dict[str, Any]:
        segments = trace.get("Segments") if isinstance(trace.get("Segments"), list) else []
        for seg in segments:
            if not isinstance(seg, dict):
                continue
            doc_raw = seg.get("Document")
            if not isinstance(doc_raw, str):
                continue
            try:
                doc = json.loads(doc_raw)
            except json.JSONDecodeError:
                continue
            if isinstance(doc, dict):
                return doc
        return {}

    @staticmethod
    def _status(summary: dict[str, Any]) -> str:
        if bool(summary.get("HasFault")):
            return "fault"
        if bool(summary.get("HasError")):
            return "error"
        if bool(summary.get("HasThrottle")):
            return "throttle"
        return "ok"

    @staticmethod
    def _chunked(items: list[str], size: int) -> list[list[str]]:
        if size <= 0:
            return [items]
        return [items[i:i + size] for i in range(0, len(items), size)]

    def fetch_traces(
        self, service: str, start_iso: str, end_iso: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        max_items = min(max(limit, 0), 100)
        if max_items == 0:
            return []

        start = self._parse_iso(start_iso)
        end = self._parse_iso(end_iso)
        if end <= start:
            raise RuntimeError("Invalid trace window: end_iso must be after start_iso")

        requested_service = service.strip().lower()
        client = self._client()
        summaries: list[dict[str, Any]] = []
        next_token: str | None = None
        while len(summaries) < max_items:
            req: dict[str, Any] = {
                "StartTime": start,
                "EndTime": end,
                "Sampling": False,
            }
            if next_token:
                req["NextToken"] = next_token
            out = client.get_trace_summaries(**req)
            page = out.get("TraceSummaries") if isinstance(out, dict) else []
            if isinstance(page, list):
                for summary in page:
                    if not isinstance(summary, dict):
                        continue
                    service_names = self._summary_services(summary)
                    if requested_service and service_names:
                        lowered = {name.lower() for name in service_names}
                        if requested_service not in lowered:
                            continue
                    summaries.append(summary)
                    if len(summaries) >= max_items:
                        break

            next_token = out.get("NextToken") if isinstance(out, dict) else None
            if not next_token:
                break

        trace_ids = [str(s.get("Id") or "") for s in summaries if str(s.get("Id") or "").strip()]
        trace_ids = trace_ids[:max_items]
        if not trace_ids:
            return []

        traces_by_id: dict[str, dict[str, Any]] = {}
        for chunk in self._chunked(trace_ids, 5):
            batch = client.batch_get_traces(TraceIds=chunk)
            traces = batch.get("Traces") if isinstance(batch, dict) else []
            if not isinstance(traces, list):
                continue
            for trace in traces:
                if not isinstance(trace, dict):
                    continue
                trace_id = str(trace.get("Id") or "").strip()
                if trace_id:
                    traces_by_id[trace_id] = trace

        out: list[dict[str, Any]] = []
        for summary in summaries:
            trace_id = str(summary.get("Id") or "").strip()
            if not trace_id:
                continue
            trace = traces_by_id.get(trace_id, {})
            services = self._summary_services(summary)
            service_name = service or (services[0] if services else "unknown")
            duration = summary.get("Duration")
            response_time = summary.get("ResponseTime")

            doc = self._safe_segment_doc(trace)
            http = doc.get("http") if isinstance(doc.get("http"), dict) else {}
            request = http.get("request") if isinstance(http.get("request"), dict) else {}
            root_name = str(doc.get("name") or service_name)

            out.append(
                {
                    "trace_id": trace_id,
                    "service": service_name,
                    "status": self._status(summary),
                    "start_time_iso": self._to_iso(summary.get("StartTime")),
                    "duration_ms": round(float(duration) * 1000, 2) if isinstance(duration, (int, float)) else None,
                    "response_time_ms": round(float(response_time) * 1000, 2) if isinstance(response_time, (int, float)) else None,
                    "fault": bool(summary.get("HasFault")),
                    "error": bool(summary.get("HasError")),
                    "throttle": bool(summary.get("HasThrottle")),
                    "root_segment": root_name,
                    "http_method": str(request.get("method")) if request.get("method") is not None else None,
                    "http_url": str(request.get("url")) if request.get("url") is not None else None,
                }
            )
            if len(out) >= max_items:
                break

        return out

    def fetch_active_alerts(
        self, services: list[str], since_minutes: int, max_alerts: int
    ) -> list[dict[str, Any]]:
        raise RuntimeError(
            "X-Ray adapter does not implement fetch_active_alerts. "
            "Use ALERTS_PROVIDER=datadog|cloudwatch|prometheus|pagerduty|opsgenie."
        )

    def health_snapshot(self, service: str, start_iso: str, end_iso: str) -> dict[str, Any]:
        raise RuntimeError(
            "X-Ray adapter does not implement health_snapshot. "
            "Use METRICS_PROVIDER=datadog|cloudwatch|prometheus."
        )
