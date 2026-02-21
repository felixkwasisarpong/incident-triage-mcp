from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from incident_triage_mcp.secrets.loader import SecretsLoader


class CloudWatchAPI:
    def __init__(self, secrets: SecretsLoader, cloudwatch_client: Any | None = None) -> None:
        self._secrets = secrets
        self._cloudwatch_client = cloudwatch_client

    def _region(self) -> str:
        return (
            self._secrets.get("CLOUDWATCH_REGION")
            or self._secrets.get("AWS_REGION")
            or self._secrets.get("AWS_DEFAULT_REGION")
            or self._secrets.get("S3_REGION")
            or "us-east-1"
        )

    def _client(self) -> Any:
        if self._cloudwatch_client is not None:
            return self._cloudwatch_client

        try:
            import boto3  # type: ignore
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "CloudWatch provider requires optional dependency 'boto3'. "
                "Install with: pip install 'incident-triage-mcp[aws]'"
            ) from exc

        access_key = self._secrets.get("AWS_ACCESS_KEY_ID")
        secret_key = self._secrets.get("AWS_SECRET_ACCESS_KEY")
        session_token = self._secrets.get("AWS_SESSION_TOKEN")

        if bool(access_key) ^ bool(secret_key):
            raise RuntimeError(
                "CloudWatch provider misconfigured: set both AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY, "
                "or rely on IAM role/default credential chain."
            )

        session_kwargs: dict[str, Any] = {"region_name": self._region()}
        if access_key and secret_key:
            session_kwargs["aws_access_key_id"] = access_key
            session_kwargs["aws_secret_access_key"] = secret_key
            if session_token:
                session_kwargs["aws_session_token"] = session_token

        session = boto3.session.Session(**session_kwargs)
        self._cloudwatch_client = session.client("cloudwatch")
        return self._cloudwatch_client

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
    def _to_utc(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _priority_from_name(name: str) -> str:
        lowered = (name or "").lower()
        if any(token in lowered for token in ["critical", "sev1", "p1"]):
            return "P1"
        if any(token in lowered for token in ["high", "sev2", "p2"]):
            return "P2"
        if any(token in lowered for token in ["low", "sev4", "p4"]):
            return "P4"
        return "P3"

    @staticmethod
    def _status_from_state(state_value: str) -> str:
        lowered = (state_value or "").strip().lower()
        if lowered == "alarm":
            return "triggered"
        if lowered == "insufficient_data":
            return "warning"
        return "resolved"

    def _service_from_dimensions(
        self, dimensions: list[dict[str, Any]] | None, fallback: str | None = None
    ) -> str:
        if not isinstance(dimensions, list):
            return fallback or "unknown"

        preferred_names = [
            self._secrets.get("CLOUDWATCH_DIMENSION_NAME", default="Service") or "Service",
            "Service",
            "service",
            "App",
            "Application",
            "FunctionName",
            "ClusterName",
        ]
        preferred_lookup = {name.lower() for name in preferred_names}

        for dim in dimensions:
            if not isinstance(dim, dict):
                continue
            name = str(dim.get("Name") or "").strip()
            value = str(dim.get("Value") or "").strip()
            if name.lower() in preferred_lookup and value:
                return value

        return fallback or "unknown"

    def fetch_active_alerts(
        self, services: list[str], since_minutes: int, max_alerts: int
    ) -> list[dict[str, Any]]:
        limit = max(0, max_alerts)
        if limit == 0:
            return []

        client = self._client()
        service_filters = [svc.strip() for svc in services if svc and svc.strip()]
        service_lookup = {svc.lower() for svc in service_filters}
        since_cutoff = datetime.now(timezone.utc) - timedelta(minutes=max(1, since_minutes))

        alerts: list[dict[str, Any]] = []
        next_token: str | None = None
        while len(alerts) < limit:
            req: dict[str, Any] = {"StateValue": "ALARM", "MaxRecords": 100}
            if next_token:
                req["NextToken"] = next_token
            page = client.describe_alarms(**req)
            metric_alarms = page.get("MetricAlarms") if isinstance(page, dict) else []
            composite_alarms = page.get("CompositeAlarms") if isinstance(page, dict) else []
            alarms = []
            if isinstance(metric_alarms, list):
                alarms.extend(metric_alarms)
            if isinstance(composite_alarms, list):
                alarms.extend(composite_alarms)

            for alarm in alarms:
                if not isinstance(alarm, dict):
                    continue

                state = str(alarm.get("StateValue") or "ALARM")
                status = self._status_from_state(state)
                if status == "resolved":
                    continue

                updated_at = self._to_utc(alarm.get("StateUpdatedTimestamp"))
                if updated_at and updated_at < since_cutoff:
                    continue

                dimensions = alarm.get("Dimensions") if isinstance(alarm.get("Dimensions"), list) else []
                fallback_service = service_filters[0] if service_filters else None
                service = self._service_from_dimensions(dimensions, fallback=fallback_service)
                if service_lookup and service.lower() not in service_lookup:
                    continue

                started_at_iso = (updated_at or since_cutoff).isoformat()
                alarm_name = str(alarm.get("AlarmName") or "CloudWatch alarm")
                metric_name = str(alarm.get("MetricName") or "alarm_state")
                alert_id = str(alarm.get("AlarmArn") or alarm_name)
                alerts.append(
                    {
                        "alert_id": alert_id,
                        "provider": "cloudwatch",
                        "service": service,
                        "name": alarm_name,
                        "status": status,
                        "started_at_iso": started_at_iso,
                        "priority": self._priority_from_name(alarm_name),
                        "signal": {
                            "key": metric_name,
                            "value": state,
                        },
                    }
                )
                if len(alerts) >= limit:
                    break

            next_token = page.get("NextToken") if isinstance(page, dict) else None
            if not next_token:
                break

        return alerts

    def _latest_metric(
        self,
        *,
        service: str,
        metric_name: str,
        stat: str,
        start: datetime,
        end: datetime,
    ) -> float | None:
        period_raw = self._secrets.get("CLOUDWATCH_PERIOD_SECONDS", default="60") or "60"
        try:
            period = int(period_raw)
        except ValueError:
            period = 60
        if period <= 0:
            period = 60

        namespace = self._secrets.get("CLOUDWATCH_NAMESPACE", default="IncidentTriage") or "IncidentTriage"
        dimension_name = self._secrets.get("CLOUDWATCH_DIMENSION_NAME", default="Service") or "Service"
        request: dict[str, Any] = {
            "Namespace": namespace,
            "MetricName": metric_name,
            "Dimensions": [{"Name": dimension_name, "Value": service}],
            "StartTime": start,
            "EndTime": end,
            "Period": period,
        }
        if stat.startswith("p"):
            request["ExtendedStatistics"] = [stat]
        else:
            request["Statistics"] = [stat]

        out = self._client().get_metric_statistics(**request)
        datapoints = out.get("Datapoints") if isinstance(out, dict) else []
        if not isinstance(datapoints, list) or not datapoints:
            return None

        latest: dict[str, Any] | None = None
        for point in datapoints:
            if not isinstance(point, dict):
                continue
            ts = self._to_utc(point.get("Timestamp"))
            if ts is None:
                continue
            if latest is None:
                latest = point
                continue
            latest_ts = self._to_utc(latest.get("Timestamp"))
            if latest_ts is None or ts > latest_ts:
                latest = point

        if latest is None:
            return None

        raw_value = latest.get(stat)
        if raw_value is None:
            return None
        try:
            return float(raw_value)
        except (TypeError, ValueError):
            return None

    def health_snapshot(self, service: str, start_iso: str, end_iso: str) -> dict[str, Any]:
        start = self._parse_dt(start_iso)
        end = self._parse_dt(end_iso)

        error_metric = self._secrets.get("CLOUDWATCH_ERROR_RATE_METRIC", default="ErrorRate") or "ErrorRate"
        latency_metric = self._secrets.get("CLOUDWATCH_LATENCY_P95_METRIC", default="LatencyP95") or "LatencyP95"
        rps_metric = self._secrets.get("CLOUDWATCH_RPS_METRIC", default="RequestsPerSecond") or "RequestsPerSecond"

        error_rate = self._latest_metric(
            service=service,
            metric_name=error_metric,
            stat="Average",
            start=start,
            end=end,
        )
        latency_p95_ms = self._latest_metric(
            service=service,
            metric_name=latency_metric,
            stat="p95",
            start=start,
            end=end,
        )
        rps = self._latest_metric(
            service=service,
            metric_name=rps_metric,
            stat="Average",
            start=start,
            end=end,
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
            "provider": "cloudwatch",
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
