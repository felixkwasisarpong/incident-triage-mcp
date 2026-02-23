from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from typing import Any

import requests
from mcp.server.fastmcp import FastMCP

from incident_triage_mcp.adapters.idempotency_store import (
    IdempotencyStore,
    build_idempotency_store_from_env,
)
from incident_triage_mcp.adapters.jira_provider import get_provider, provider_name
from incident_triage_mcp.adapters.registry import build_observability_registry
from incident_triage_mcp.adapters.resilience import ResilienceError, ResiliencePolicy
from incident_triage_mcp.adapters.runbooks_local import RunbooksLocal
from incident_triage_mcp.adapters.artifacts_s3 import read_evidence_bundle
from incident_triage_mcp.adapters.teams_webhook import (
    build_teams_message_card,
    post_teams_webhook,
)
from incident_triage_mcp.audit import AuditLog
from incident_triage_mcp.config import ConfigError, load_config
from incident_triage_mcp.domain_models import EvidenceBundle
from incident_triage_mcp.policy.http_auth import HTTPAuthError, verify_api_key, verify_jwt_from_headers
from incident_triage_mcp.policy.rbac import require_allowed, role
from incident_triage_mcp.policy.safe_actions import SafeActionContext, enforce, SafeActionError
from incident_triage_mcp.telemetry import ServiceTelemetry
from incident_triage_mcp.tools.evidence import load_bundle
from incident_triage_mcp.tools.incidents import triage_incident_run
from incident_triage_mcp.tools.jira_draft import build_jira_draft
from incident_triage_mcp.tools.runbooks import search_runbooks as search_local_runbooks
from incident_triage_mcp.tools.triage import build_triage_summary
from incident_triage_mcp.tools.waiter import wait_for
from incident_triage_mcp.secrets.loader import SecretsError, get_secrets_loader


class _NoopIdempotencyStore:
    def get(self, key: str) -> dict[str, Any] | None:
        return None

    def set(self, key: str, value: dict[str, Any]) -> None:
        return None


def _env_truthy(raw: str | None, *, default: bool = False) -> bool:
    value = (raw or "").strip()
    if not value:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def _parse_float(raw: str | None, *, default: float) -> float:
    value = (raw or "").strip()
    if not value:
        return default
    try:
        out = float(value)
    except ValueError:
        return default
    return out if out > 0 else default


def _parse_otlp_headers(raw: str | None) -> dict[str, str]:
    value = (raw or "").strip()
    if not value:
        return {}

    if value.startswith("{"):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            out: dict[str, str] = {}
            for k, v in parsed.items():
                key = str(k).strip()
                header_value = str(v).strip()
                if key and header_value:
                    out[key] = header_value
            return out
        return {}

    out: dict[str, str] = {}
    for part in value.split(","):
        chunk = part.strip()
        if not chunk or "=" not in chunk:
            continue
        key, header_value = chunk.split("=", 1)
        key = key.strip()
        header_value = header_value.strip()
        if key and header_value:
            out[key] = header_value
    return out


def _normalize_hex(value: str | None, width: int) -> str:
    raw = (value or "").strip().lower()
    clean = "".join(ch for ch in raw if ch in "0123456789abcdef")
    if len(clean) < width:
        clean = clean.rjust(width, "0")
    return clean[:width]


def _iso_to_dt(ts: str | None) -> datetime:
    raw = (ts or "").strip()
    if raw:
        normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
        try:
            dt = datetime.fromisoformat(normalized)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _to_unix_nanos(dt: datetime) -> str:
    return str(max(0, int(dt.timestamp() * 1_000_000_000)))


def _otlp_attribute(key: str, value: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"key": key}
    if isinstance(value, bool):
        out["value"] = {"boolValue": value}
    elif isinstance(value, int):
        out["value"] = {"intValue": str(value)}
    elif isinstance(value, float):
        out["value"] = {"doubleValue": float(value)}
    else:
        out["value"] = {"stringValue": str(value)}
    return out


def _build_otlp_trace_payload(event: dict[str, Any], *, service_name: str) -> dict[str, Any]:
    end_dt = _iso_to_dt(str(event.get("timestamp_iso") or ""))
    latency_ms = max(0.0, float(event.get("latency_ms") or 0.0))
    start_dt = end_dt - timedelta(milliseconds=latency_ms)
    trace_id = _normalize_hex(str(event.get("trace_id") or ""), 32)
    span_id = _normalize_hex(str(event.get("span_id") or ""), 16)
    status_code = 1 if bool(event.get("ok", True)) else 2

    attrs = [
        _otlp_attribute("tool.name", event.get("tool_name", "")),
        _otlp_attribute("tool.ok", bool(event.get("ok", True))),
        _otlp_attribute("tool.latency_ms", latency_ms),
    ]
    request_id = (str(event.get("request_id") or "")).strip()
    if request_id:
        attrs.append(_otlp_attribute("request.id", request_id))
    transport = (str(event.get("transport") or "")).strip()
    if transport:
        attrs.append(_otlp_attribute("transport", transport))
    error = (str(event.get("error") or "")).strip()
    if error:
        attrs.append(_otlp_attribute("error.message", error))

    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        _otlp_attribute("service.name", service_name),
                    ]
                },
                "scopeSpans": [
                    {
                        "scope": {"name": "incident-triage-mcp", "version": "0.1"},
                        "spans": [
                            {
                                "traceId": trace_id,
                                "spanId": span_id,
                                "name": str(event.get("tool_name") or "tool.call"),
                                "kind": 2,  # SPAN_KIND_SERVER
                                "startTimeUnixNano": _to_unix_nanos(start_dt),
                                "endTimeUnixNano": _to_unix_nanos(end_dt),
                                "attributes": attrs,
                                "status": {"code": status_code},
                            }
                        ],
                    }
                ],
            }
        ]
    }


def _build_otlp_trace_sink(
    *,
    service_name: str,
    endpoint: str,
    timeout_seconds: float,
    headers: dict[str, str] | None = None,
):
    request_headers = {"Content-Type": "application/json"}
    if headers:
        request_headers.update(headers)

    def _sink(event: dict[str, Any]) -> None:
        payload = _build_otlp_trace_payload(event, service_name=service_name)
        response = requests.post(
            endpoint,
            json=payload,
            headers=request_headers,
            timeout=timeout_seconds,
        )
        response.raise_for_status()

    return _sink


try:
    CFG = load_config()
except ConfigError as e:
    raise SystemExit(f"[config] {e}") from e

try:
    SECRETS = get_secrets_loader()
except SecretsError as e:
    raise SystemExit(f"[secrets] {e}") from e

_mcp_host = os.getenv("MCP_HOST", CFG.mcp_host or "127.0.0.1")
_mcp_port = int(os.getenv("MCP_PORT", str(CFG.mcp_port or 8000)))
mcp = FastMCP("Incident Triage MCP", json_response=True, host=_mcp_host, port=_mcp_port)
audit = AuditLog()
_trace_enabled = _env_truthy(os.getenv("MCP_TRACE_ENABLED"), default=True)
try:
    _trace_buffer_size = int((os.getenv("MCP_TRACE_BUFFER_SIZE") or "200").strip() or "200")
except ValueError:
    _trace_buffer_size = 200
_otlp_enabled = _env_truthy(os.getenv("MCP_OTLP_ENABLED"), default=False)
_otlp_endpoint = (os.getenv("MCP_OTLP_ENDPOINT") or "").strip()
_otlp_timeout_seconds = _parse_float(os.getenv("MCP_OTLP_TIMEOUT_SECONDS"), default=2.0)
_otlp_headers = _parse_otlp_headers(os.getenv("MCP_OTLP_HEADERS"))
_otlp_export_enabled = _otlp_enabled and bool(_otlp_endpoint)

if _otlp_enabled and _otlp_endpoint:
    _trace_event_sink = _build_otlp_trace_sink(
        service_name="incident-triage-mcp",
        endpoint=_otlp_endpoint,
        timeout_seconds=_otlp_timeout_seconds,
        headers=_otlp_headers,
    )
else:
    _trace_event_sink = None

telemetry = ServiceTelemetry(
    "incident-triage-mcp",
    trace_enabled=_trace_enabled,
    trace_buffer_size=_trace_buffer_size,
    trace_event_sink=_trace_event_sink,
)


def _otlp_export_status() -> dict[str, Any]:
    if not _otlp_enabled:
        return {"enabled": False, "reason": "disabled"}
    if not _otlp_endpoint:
        return {"enabled": False, "reason": "missing_endpoint"}
    return {"enabled": True, "endpoint": _otlp_endpoint}


def _record_resilience_event(event: dict[str, Any]) -> None:
    kind = str(event.get("kind", "adapter_call_failed"))
    telemetry.observe_adapter(
        str(event.get("provider", "unknown")),
        str(event.get("operation", "unknown")),
        ok=(kind == "success"),
        latency_ms=float(event.get("elapsed_ms", 0.0)),
    )


observability = build_observability_registry(
    alerts_provider=CFG.alerts_provider,
    metrics_provider=CFG.metrics_provider,
    logs_provider=CFG.logs_provider,
    traces_provider=CFG.traces_provider,
    secrets=SECRETS,
    resilience_policy=ResiliencePolicy(
        timeout_seconds=CFG.adapter_timeout_seconds,
        retries=CFG.adapter_retries,
        base_backoff_seconds=CFG.adapter_backoff_seconds,
        max_backoff_seconds=CFG.adapter_max_backoff_seconds,
        circuit_failure_threshold=CFG.adapter_circuit_failure_threshold,
        circuit_open_seconds=CFG.adapter_circuit_open_seconds,
    ),
    resilience_event_sink=_record_resilience_event,
)
# Backward-compatible test hook; currently points at alerts provider adapter.
datadog = observability.alerts_adapter
runbooks = RunbooksLocal()


def _active_transport() -> str:
    return (os.getenv("MCP_TRANSPORT", CFG.mcp_transport or "stdio") or "stdio").strip().lower()


def _request_headers() -> dict[str, str]:
    get_context = getattr(mcp, "get_context", None)
    if not callable(get_context):
        return {}
    try:
        ctx = get_context()
    except Exception:
        return {}
    try:
        request_context = getattr(ctx, "request_context", None)
    except Exception:
        # FastMCP can raise outside an active request context.
        return {}
    request = getattr(request_context, "request", None) if request_context is not None else None
    headers = getattr(request, "headers", None)
    if not headers:
        return {}
    try:
        return {str(k).lower(): str(v) for k, v in headers.items()}
    except Exception:
        return {}


def _request_correlation_id(headers: dict[str, str]) -> str | None:
    for key in ("x-correlation-id", "x-request-id"):
        value = (headers.get(key) or "").strip()
        if value:
            return value
    return None


@contextmanager
def _tool_observation(
    tool_name: str,
    *,
    request_id: str | None = None,
    transport: str | None = None,
):
    trace_id = telemetry.new_trace_id()
    span_id = telemetry.new_span_id()
    started = time.perf_counter()
    try:
        yield
    except Exception as exc:
        telemetry.observe_tool_with_trace(
            tool_name,
            ok=False,
            latency_ms=(time.perf_counter() - started) * 1000.0,
            trace_id=trace_id,
            span_id=span_id,
            request_id=request_id,
            transport=transport,
            error=f"{exc.__class__.__name__}: {exc}",
        )
        raise
    telemetry.observe_tool_with_trace(
        tool_name,
        ok=True,
        latency_ms=(time.perf_counter() - started) * 1000.0,
        trace_id=trace_id,
        span_id=span_id,
        request_id=request_id,
        transport=transport,
    )


def _instrumented_tool(tool_name: str):
    def _decorate(fn):
        @wraps(fn)
        def _wrapped(*args, **kwargs):
            headers = _request_headers()
            request_id = _request_correlation_id(headers)
            with _tool_observation(
                tool_name,
                request_id=request_id,
                transport=_active_transport(),
            ):
                return fn(*args, **kwargs)

        return _wrapped

    return _decorate


def _assert_audit_meta_complete(meta: dict[str, Any]) -> None:
    required = {
        "transport",
        "auth_mode",
        "auth_required",
        "authenticated",
        "principal",
        "request_id",
    }
    missing = [key for key in sorted(required) if key not in meta]
    if missing:
        raise RuntimeError(f"Incomplete audit metadata: missing {', '.join(missing)}")


def _tool_request_meta(tool_event: str) -> tuple[dict[str, Any], str | None]:
    headers = _request_headers()
    request_id = _request_correlation_id(headers)
    transport = _active_transport()
    mode = CFG.http_auth_mode
    auth_required = transport == "streamable-http" and mode != "none"

    meta: dict[str, Any] = {
        "transport": transport,
        "auth_mode": mode,
        "auth_required": auth_required,
        "authenticated": False,
        "principal": "local-cli" if transport == "stdio" else "anonymous",
        "request_id": request_id,
    }

    if not auth_required:
        _assert_audit_meta_complete(meta)
        return meta, request_id

    try:
        if mode == "api_key":
            verdict = verify_api_key(headers, CFG.http_api_key or "")
        elif mode == "jwt_hs256":
            verdict = verify_jwt_from_headers(
                headers,
                CFG.http_jwt_secret or "",
                issuer=CFG.http_jwt_issuer,
                audience=CFG.http_jwt_audience,
                leeway_seconds=CFG.http_jwt_leeway_seconds,
            )
        else:
            raise HTTPAuthError(f"Unsupported MCP_HTTP_AUTH_MODE={mode!r}")
    except HTTPAuthError as e:
        telemetry.observe_auth_denied()
        _assert_audit_meta_complete(meta)
        audit.write(
            f"{tool_event}.auth_denied",
            {"error": str(e)},
            ok=False,
            meta=meta,
            correlation_id=request_id,
        )
        raise

    meta.update(
        {
            "authenticated": bool(verdict.get("authenticated", True)),
            "principal": str(verdict.get("principal", "authenticated-client")),
        }
    )
    if "issuer" in verdict:
        meta["issuer"] = verdict.get("issuer")
    if "audience" in verdict:
        meta["audience"] = verdict.get("audience")
    _assert_audit_meta_complete(meta)
    return meta, request_id


def _http_health_payload() -> dict[str, Any]:
    airflow_reason = _airflow_disabled_reason()
    health = telemetry.health()
    health["tracing"] = telemetry.snapshot().get("tracing", {})
    health["tracing"]["otlp_export"] = _otlp_export_status()
    health["bundle_only_mode"] = CFG.bundle_only_mode
    health["transport"] = _active_transport()
    health["evidence_backend"] = _evidence_backend()
    health["providers"] = observability.provider_summary()
    health["airflow"] = {
        "enabled": airflow_reason == "",
        "reason": airflow_reason or None,
    }
    return health


def _http_metrics_payload() -> dict[str, Any]:
    snapshot = telemetry.snapshot()
    snapshot.setdefault("tracing", {})["otlp_export"] = _otlp_export_status()
    snapshot["bundle_only_mode"] = CFG.bundle_only_mode
    snapshot["transport"] = _active_transport()
    snapshot["evidence_backend"] = _evidence_backend()
    snapshot["providers"] = observability.provider_summary()
    return snapshot


def _register_http_health_routes() -> None:
    custom_route = getattr(mcp, "custom_route", None)
    if not callable(custom_route):
        return
    try:
        from starlette.responses import JSONResponse
    except Exception:
        return

    @custom_route("/healthz", methods=["GET"], include_in_schema=False)
    async def _healthz(_request):  # pragma: no cover - exercised in HTTP runtime
        payload = _http_health_payload()
        status_code = 200 if payload.get("ok") else 503
        return JSONResponse(payload, status_code=status_code)

    @custom_route("/metrics", methods=["GET"], include_in_schema=False)
    async def _metrics(_request):  # pragma: no cover - exercised in HTTP runtime
        return JSONResponse(_http_metrics_payload())

    @custom_route("/traces", methods=["GET"], include_in_schema=False)
    async def _traces(request):  # pragma: no cover - exercised in HTTP runtime
        raw_limit = "25"
        try:
            raw_limit = str(request.query_params.get("limit", "25"))
        except Exception:
            pass
        try:
            limit = max(1, int(raw_limit))
        except ValueError:
            limit = 25
        return JSONResponse(
            {
                "traces": telemetry.recent_traces(limit),
                "tracing": telemetry.snapshot().get("tracing", {}),
            }
        )


def _build_idempotency_store() -> IdempotencyStore:
    try:
        return build_idempotency_store_from_env()
    except Exception:
        # Keep server bootable if backend is unavailable/misconfigured.
        return _NoopIdempotencyStore()


ticket_idempotency_store = _build_idempotency_store()


def _evidence_backend() -> str:
    backend = (os.getenv("EVIDENCE_BACKEND") or CFG.evidence_backend or "").strip().lower()
    if not backend:
        backend = (os.getenv("ARTIFACT_STORE") or CFG.artifact_store or "fs").strip().lower()
    if backend in {"none", "fs", "s3", "airflow"}:
        return backend
    return "fs"


def _primary_evidence_dir() -> str:
    return (
        os.getenv("EVIDENCE_DIR")
        or os.getenv("AIRFLOW_ARTIFACT_DIR")
        or CFG.evidence_dir
        or "./evidence"
    )


def _evidence_dirs() -> list[str]:
    dirs: list[str] = []
    for candidate in [
        os.getenv("EVIDENCE_DIR"),
        os.getenv("AIRFLOW_ARTIFACT_DIR"),
        CFG.evidence_dir,
        "./airflow/artifacts",
    ]:
        if not candidate:
            continue
        resolved = str(Path(candidate))
        if resolved not in dirs:
            dirs.append(resolved)
    if not dirs:
        dirs.append("./evidence")
    return dirs


def _airflow_settings() -> tuple[str | None, str | None, str | None]:
    base_url = os.getenv("AIRFLOW_BASE_URL") or CFG.airflow_base_url
    username = os.getenv("AIRFLOW_USERNAME") or CFG.airflow_username
    password = os.getenv("AIRFLOW_PASSWORD") or CFG.airflow_password
    return base_url, username, password


def _airflow_disabled_reason() -> str:
    if _evidence_backend() != "airflow":
        return (
            f"Airflow integration disabled: EVIDENCE_BACKEND={_evidence_backend()!r}. "
            "Set EVIDENCE_BACKEND=airflow to enable Airflow tools."
        )
    base_url, username, password = _airflow_settings()
    missing: list[str] = []
    if not base_url:
        missing.append("AIRFLOW_BASE_URL")
    if not username:
        missing.append("AIRFLOW_USERNAME")
    if not password:
        missing.append("AIRFLOW_PASSWORD")
    if missing:
        return "Airflow backend misconfigured: missing " + ", ".join(missing)
    return ""


_airflow_client: Any | None = None


def _get_airflow_client() -> tuple[Any | None, str]:
    reason = _airflow_disabled_reason()
    if reason:
        return None, reason

    global _airflow_client
    if _airflow_client is None:
        # Lazy import keeps standalone mode free from Airflow client initialization.
        from incident_triage_mcp.adapters.airflow_api import AirflowAPI

        base_url, _, _ = _airflow_settings()
        _airflow_client = AirflowAPI(base_url=base_url or "http://localhost:8080")
    return _airflow_client, ""


class _AirflowProxy:
    def trigger_dag(self, dag_id: str, conf: dict[str, Any]) -> dict[str, Any]:
        client, reason = _get_airflow_client()
        if reason:
            raise RuntimeError(reason)
        return client.trigger_dag(dag_id, conf)

    def get_dag_run(self, dag_id: str, dag_run_id: str) -> dict[str, Any]:
        client, reason = _get_airflow_client()
        if reason:
            raise RuntimeError(reason)
        return client.get_dag_run(dag_id, dag_run_id)


airflow = _AirflowProxy()


def _jira_project_key(project_key: str | None) -> str:
    resolved = (project_key or os.getenv("JIRA_PROJECT_KEY", "INC") or "INC").strip()
    return resolved or "INC"


def _jira_issue_type() -> str:
    resolved = (os.getenv("JIRA_ISSUE_TYPE", "Task") or "Task").strip()
    return resolved or "Task"


def _notify_provider(provider: str | None = None) -> str:
    resolved = (
        provider
        or os.getenv("NOTIFY_PROVIDER")
        or CFG.notify_provider
        or "slack"
    ).strip().lower()
    if resolved in {"slack", "teams"}:
        return resolved
    return "slack"


def _observability_disabled_error(operation: str) -> dict[str, Any]:
    return {
        "kind": "disabled",
        "operation": operation,
        "bundle_only_mode": True,
        "message": (
            "BUNDLE_ONLY_MODE=true disables direct observability fetch tools. "
            "Use normalized evidence bundles (e.g., via Airflow) and consume them via evidence_get_bundle."
        ),
    }


def _normalized_idempotency_key(idempotency_key: str | None) -> str | None:
    if not idempotency_key:
        return None
    key = idempotency_key.strip()
    return key or None


def _build_slack_message(
    incident_id: str,
    service: str | None = None,
    summary: dict | None = None,
    ticket: dict | None = None,
) -> str:
    lines = [f"*Incident Update*: `{incident_id}`"]
    if service:
        lines.append(f"*Service*: `{service}`")

    if summary:
        status = summary.get("status")
        if status:
            lines.append(f"*Status*: `{status}`")
        alerts_count = summary.get("alerts_count")
        if alerts_count is not None:
            lines.append(f"*Alerts in window*: `{alerts_count}`")

        next_steps = summary.get("next_steps") or []
        if isinstance(next_steps, list) and next_steps:
            lines.append("*Next Steps*:")
            for step in next_steps[:3]:
                lines.append(f"- {step}")

    if ticket:
        issue_key = ticket.get("issue_key")
        browse_url = ticket.get("browse_url")
        if issue_key and browse_url:
            lines.append(f"*Ticket*: <{browse_url}|{issue_key}>")
        elif issue_key:
            lines.append(f"*Ticket*: `{issue_key}`")
        elif ticket.get("dry_run"):
            lines.append("*Ticket*: dry-run prepared")

    return "\n".join(lines)


@mcp.tool()
@_instrumented_tool("incident_triage_run")
def incident_triage_run(
    incident_id: str,
    service: str,
    include_ticket: bool = False,
    project_key: str | None = None,
    notify_slack: bool = False,
    notify_provider: str | None = None,
    slack_channel: str | None = None,
    slack_dry_run: bool = True,
) -> dict:
    """
    One-call triage orchestration.
    Airflow trigger is optional and backend-dependent.
    """
    meta, request_id = _tool_request_meta("incident.triage_run")
    resolved_project_key = _jira_project_key(project_key)
    resolved_notify_provider = _notify_provider(notify_provider)
    corr = audit.write(
        "incident.triage_run",
        {
            "incident_id": incident_id,
            "service": service,
            "include_ticket": include_ticket,
            "project_key": resolved_project_key if include_ticket else None,
            "notify_slack": notify_slack,
            "notify_provider": resolved_notify_provider if notify_slack else None,
            "slack_channel": slack_channel,
            "slack_dry_run": slack_dry_run,
            "evidence_backend": _evidence_backend(),
        },
        ok=True,
        meta=meta,
        correlation_id=request_id,
    )

    tickets_create = None
    if include_ticket:
        # Keep orchestration safe by default: ticket hook is dry-run.
        def _ticket_hook(
            title: str | None = None,
            body: str | None = None,
            severity: str | None = None,
            **_ignored: object,
        ) -> dict:
            try:
                return jira_create_ticket(
                    incident_id=incident_id,
                    project_key=resolved_project_key,
                    dry_run=True,
                )
            except Exception as e:
                return {"created": False, "dry_run": True, "error": str(e)}

        tickets_create = _ticket_hook

    result = triage_incident_run(
        incident_id=incident_id,
        service=service,
        alerts_fetch_active=alerts_fetch_active,
        airflow_trigger_incident_dag=airflow_trigger_incident_dag,
        airflow_get_incident_artifact=airflow_get_incident_artifact,
        evidence_wait_for_bundle=evidence_wait_for_bundle,
        tickets_create=tickets_create,
    )

    if notify_slack:
        target = resolved_notify_provider
        try:
            notify_result = notify_post_update(
                incident_id=incident_id,
                service=service,
                summary=result.get("summary"),
                ticket=result.get("ticket"),
                provider=target,
                channel=slack_channel,
                dry_run=slack_dry_run,
            )
        except Exception as e:
            notify_result = {
                "posted": False,
                "dry_run": slack_dry_run,
                "error": str(e),
                "provider": target,
            }
        result["notify"] = notify_result
        notify_key = "teams" if str(notify_result.get("provider") or target).lower() == "teams" else "slack"
        result[notify_key] = notify_result

    result["correlation_id"] = corr
    return result


@mcp.tool()
@_instrumented_tool("alerts_fetch_active")
def alerts_fetch_active(services: list[str] = None, since_minutes: int = 30, max_alerts: int = 50) -> dict:
    meta, request_id = _tool_request_meta("alerts.fetch_active")
    services = services or []
    args = {"services": services, "since_minutes": since_minutes, "max_alerts": max_alerts}
    corr = audit.write("alerts.fetch_active", args, ok=True, meta=meta, correlation_id=request_id)

    if CFG.bundle_only_mode:
        err = _observability_disabled_error("fetch_active_alerts")
        audit.write("alerts.fetch_active.disabled", {"error": err}, ok=False)
        return {
            "correlation_id": corr,
            "alerts": [],
            "grouping": {"by_service": {}},
            "error": err,
        }

    try:
        alerts = observability.fetch_active_alerts(services, since_minutes, max_alerts)
    except ResilienceError as e:
        audit.write("alerts.fetch_active.error", {"error": e.to_dict()}, ok=False)
        return {
            "correlation_id": corr,
            "alerts": [],
            "grouping": {"by_service": {}},
            "error": e.to_dict(),
        }

    by_service: dict[str, list[str]] = {}
    for a in alerts:
        by_service.setdefault(a["service"], []).append(a["alert_id"])

    return {"correlation_id": corr, "alerts": alerts, "grouping": {"by_service": by_service}}


@mcp.tool()
@_instrumented_tool("service_health_snapshot")
def service_health_snapshot(service: str, start_iso: str, end_iso: str) -> dict:
    meta, request_id = _tool_request_meta("service.health_snapshot")
    args = {"service": service, "start_iso": start_iso, "end_iso": end_iso}
    corr = audit.write("service.health_snapshot", args, ok=True, meta=meta, correlation_id=request_id)

    if CFG.bundle_only_mode:
        err = _observability_disabled_error("health_snapshot")
        audit.write("service.health_snapshot.disabled", {"error": err}, ok=False)
        return {"correlation_id": corr, "snapshot": {}, "error": err}

    try:
        snap = observability.health_snapshot(service, start_iso, end_iso)
    except ResilienceError as e:
        audit.write("service.health_snapshot.error", {"error": e.to_dict()}, ok=False)
        return {"correlation_id": corr, "snapshot": {}, "error": e.to_dict()}

    return {"correlation_id": corr, "snapshot": snap}


@mcp.tool()
@_instrumented_tool("logs_fetch_recent")
def logs_fetch_recent(service: str, start_iso: str, end_iso: str, limit: int = 100) -> dict:
    meta, request_id = _tool_request_meta("logs.fetch_recent")
    args = {
        "service": service,
        "start_iso": start_iso,
        "end_iso": end_iso,
        "limit": limit,
    }
    corr = audit.write("logs.fetch_recent", args, ok=True, meta=meta, correlation_id=request_id)

    if CFG.bundle_only_mode:
        err = _observability_disabled_error("fetch_logs")
        audit.write("logs.fetch_recent.disabled", {"error": err}, ok=False)
        return {"correlation_id": corr, "logs": [], "error": err}

    try:
        logs = observability.fetch_logs(service, start_iso, end_iso, limit)
    except ResilienceError as e:
        audit.write("logs.fetch_recent.error", {"error": e.to_dict()}, ok=False)
        return {"correlation_id": corr, "logs": [], "error": e.to_dict()}

    return {"correlation_id": corr, "logs": logs}


@mcp.tool()
@_instrumented_tool("traces_fetch_recent")
def traces_fetch_recent(service: str, start_iso: str, end_iso: str, limit: int = 100) -> dict:
    meta, request_id = _tool_request_meta("traces.fetch_recent")
    args = {
        "service": service,
        "start_iso": start_iso,
        "end_iso": end_iso,
        "limit": limit,
    }
    corr = audit.write("traces.fetch_recent", args, ok=True, meta=meta, correlation_id=request_id)

    if CFG.bundle_only_mode:
        err = _observability_disabled_error("fetch_traces")
        audit.write("traces.fetch_recent.disabled", {"error": err}, ok=False)
        return {"correlation_id": corr, "traces": [], "error": err}

    try:
        traces = observability.fetch_traces(service, start_iso, end_iso, limit)
    except ResilienceError as e:
        audit.write("traces.fetch_recent.error", {"error": e.to_dict()}, ok=False)
        return {"correlation_id": corr, "traces": [], "error": e.to_dict()}

    return {"correlation_id": corr, "traces": traces}


@mcp.tool()
@_instrumented_tool("runbooks_search")
def runbooks_search(query: str, limit: int = 5) -> dict:
    meta, request_id = _tool_request_meta("runbooks.search")
    runbooks_dir = os.getenv("RUNBOOKS_DIR", CFG.runbooks_dir)
    corr = audit.write(
        "runbooks.search",
        {"query": query, "limit": limit, "runbooks_dir": runbooks_dir},
        ok=True,
        meta=meta,
        correlation_id=request_id,
    )
    hits = search_local_runbooks(runbooks_dir, query, limit)
    return {"correlation_id": corr, "results": hits}


@mcp.tool()
@_instrumented_tool("ping")
def ping(message: str = "hello") -> dict:
    meta, request_id = _tool_request_meta("ping")
    audit.write("ping", {"message": message}, ok=True, meta=meta, correlation_id=request_id)
    return {"ok": True, "message": message}


@mcp.tool()
@_instrumented_tool("mcp_health")
def mcp_health() -> dict:
    meta, request_id = _tool_request_meta("mcp.health")
    corr = audit.write("mcp.health", {}, ok=True, meta=meta, correlation_id=request_id)
    health = _http_health_payload()
    health["correlation_id"] = corr
    return health


@mcp.tool()
@_instrumented_tool("mcp_metrics")
def mcp_metrics() -> dict:
    meta, request_id = _tool_request_meta("mcp.metrics")
    corr = audit.write("mcp.metrics", {}, ok=True, meta=meta, correlation_id=request_id)
    snapshot = _http_metrics_payload()
    snapshot["correlation_id"] = corr
    return snapshot


@mcp.tool()
@_instrumented_tool("mcp_traces_recent")
def mcp_traces_recent(limit: int = 25) -> dict:
    meta, request_id = _tool_request_meta("mcp.traces_recent")
    corr = audit.write(
        "mcp.traces_recent",
        {"limit": limit},
        ok=True,
        meta=meta,
        correlation_id=request_id,
    )
    return {
        "correlation_id": corr,
        "traces": telemetry.recent_traces(limit),
        "tracing": telemetry.snapshot().get("tracing", {}),
        "otlp_export": _otlp_export_status(),
    }


@mcp.tool()
@_instrumented_tool("notify_post_update")
def notify_post_update(
    incident_id: str,
    service: str | None = None,
    summary: dict | None = None,
    ticket: dict | None = None,
    provider: str | None = None,
    channel: str | None = None,
    dry_run: bool = True,
    text: str | None = None,
) -> dict:
    """
    Provider-agnostic notification entrypoint.
    Routes to Slack or Teams based on provider/env defaults.
    """
    resolved_provider = _notify_provider(provider)
    call_kwargs: dict[str, Any] = {
        "incident_id": incident_id,
        "service": service,
        "summary": summary,
        "ticket": ticket,
        "channel": channel,
        "dry_run": dry_run,
    }
    if text is not None:
        call_kwargs["text"] = text

    if resolved_provider == "teams":
        out = teams_post_update(**call_kwargs)
    else:
        out = slack_post_update(**call_kwargs)

    result = dict(out)
    result["provider"] = resolved_provider
    return result


@mcp.tool()
@_instrumented_tool("slack_post_update")
def slack_post_update(
    incident_id: str,
    service: str | None = None,
    summary: dict | None = None,
    ticket: dict | None = None,
    channel: str | None = None,
    dry_run: bool = True,
    text: str | None = None,
) -> dict:
    """
    Post an incident update to Slack via Incoming Webhook.
    Safe-by-default: dry_run=True returns payload without sending.
    """
    meta, request_id = _tool_request_meta("slack.post_update")
    resolved_channel = (channel or os.getenv("SLACK_DEFAULT_CHANNEL") or "").strip() or None
    message = text or _build_slack_message(incident_id=incident_id, service=service, summary=summary, ticket=ticket)
    payload = {"text": message}
    if resolved_channel:
        payload["channel"] = resolved_channel

    corr = audit.write(
        "slack.post_update.request",
        {
            "incident_id": incident_id,
            "channel": resolved_channel,
            "dry_run": dry_run,
        },
        ok=True,
        meta=meta,
        correlation_id=request_id,
    )

    if not dry_run:
        try:
            require_allowed("slack.post_update")
        except Exception as e:
            audit.write(
                "slack.post_update.denied",
                {"correlation_id": corr, "error": str(e)},
                ok=False,
                meta=meta,
                correlation_id=corr,
            )
            raise

    if dry_run:
        return {
            "correlation_id": corr,
            "posted": False,
            "dry_run": True,
            "channel": resolved_channel,
            "payload": payload,
        }

    webhook = os.getenv("SLACK_WEBHOOK_URL")
    if not webhook:
        err = "SLACK_WEBHOOK_URL is not set. Configure it or call with dry_run=true."
        audit.write("slack.post_update.error", {"correlation_id": corr, "error": err}, ok=False)
        return {
            "correlation_id": corr,
            "posted": False,
            "dry_run": False,
            "channel": resolved_channel,
            "error": err,
            "payload": payload,
        }

    try:
        r = requests.post(webhook, json=payload, timeout=15)
        r.raise_for_status()
        return {
            "correlation_id": corr,
            "posted": True,
            "dry_run": False,
            "channel": resolved_channel,
        }
    except Exception as e:
        audit.write("slack.post_update.error", {"correlation_id": corr, "error": str(e)}, ok=False)
        return {
            "correlation_id": corr,
            "posted": False,
            "dry_run": False,
            "channel": resolved_channel,
            "error": str(e),
            "payload": payload,
        }


@mcp.tool()
@_instrumented_tool("teams_post_update")
def teams_post_update(
    incident_id: str,
    service: str | None = None,
    summary: dict | None = None,
    ticket: dict | None = None,
    channel: str | None = None,
    dry_run: bool = True,
    text: str | None = None,
) -> dict:
    """
    Post an incident update to Microsoft Teams via Incoming Webhook.
    Safe-by-default: dry_run=True returns payload without sending.
    """
    meta, request_id = _tool_request_meta("teams.post_update")
    resolved_channel = (channel or os.getenv("TEAMS_DEFAULT_CHANNEL") or "").strip() or None
    message = text or _build_slack_message(incident_id=incident_id, service=service, summary=summary, ticket=ticket)
    payload = build_teams_message_card(
        title=f"Incident Update {incident_id}",
        message=message,
    )
    if resolved_channel:
        payload["summary"] = f"Incident Update {incident_id} ({resolved_channel})"

    corr = audit.write(
        "teams.post_update.request",
        {
            "incident_id": incident_id,
            "channel": resolved_channel,
            "dry_run": dry_run,
        },
        ok=True,
        meta=meta,
        correlation_id=request_id,
    )

    if not dry_run:
        try:
            require_allowed("teams.post_update")
        except Exception as e:
            audit.write(
                "teams.post_update.denied",
                {"correlation_id": corr, "error": str(e)},
                ok=False,
                meta=meta,
                correlation_id=corr,
            )
            raise

    if dry_run:
        return {
            "correlation_id": corr,
            "posted": False,
            "dry_run": True,
            "channel": resolved_channel,
            "payload": payload,
        }

    webhook = os.getenv("TEAMS_WEBHOOK_URL")
    if not webhook:
        err = "TEAMS_WEBHOOK_URL is not set. Configure it or call with dry_run=true."
        audit.write("teams.post_update.error", {"correlation_id": corr, "error": err}, ok=False)
        return {
            "correlation_id": corr,
            "posted": False,
            "dry_run": False,
            "channel": resolved_channel,
            "error": err,
            "payload": payload,
        }

    try:
        post_teams_webhook(webhook, payload, timeout_seconds=15.0)
        return {
            "correlation_id": corr,
            "posted": True,
            "dry_run": False,
            "channel": resolved_channel,
        }
    except Exception as e:
        audit.write("teams.post_update.error", {"correlation_id": corr, "error": str(e)}, ok=False)
        return {
            "correlation_id": corr,
            "posted": False,
            "dry_run": False,
            "channel": resolved_channel,
            "error": str(e),
            "payload": payload,
        }


@_instrumented_tool("airflow_trigger_incident_dag")
def airflow_trigger_incident_dag(incident_id: str, service: str) -> dict:
    meta, request_id = _tool_request_meta("airflow.trigger_incident_dag")
    dag_id = "incident_evidence_v1"
    conf = {"incident_id": incident_id, "service": service}
    corr = audit.write(
        "airflow.trigger_incident_dag",
        {"dag_id": dag_id, "conf": conf, "evidence_backend": _evidence_backend()},
        ok=True,
        meta=meta,
        correlation_id=request_id,
    )

    try:
        run = airflow.trigger_dag(dag_id, conf)
        return {"correlation_id": corr, "dag_id": dag_id, "dag_run": run}
    except RuntimeError as e:
        return {
            "correlation_id": corr,
            "enabled": False,
            "backend": _evidence_backend(),
            "dag_id": dag_id,
            "dag_run": None,
            "error": f"airflow_disabled: {e}",
        }


@_instrumented_tool("airflow_get_incident_artifact")
def airflow_get_incident_artifact(incident_id: str) -> dict:
    meta, request_id = _tool_request_meta("airflow.get_incident_artifact")
    corr = audit.write(
        "airflow.get_incident_artifact",
        {"incident_id": incident_id, "evidence_backend": _evidence_backend()},
        ok=True,
        meta=meta,
        correlation_id=request_id,
    )

    if _evidence_backend() == "airflow":
        _, reason = _get_airflow_client()
        if reason:
            return {
                "correlation_id": corr,
                "enabled": False,
                "backend": "airflow",
                "found": False,
                "error": f"airflow_disabled: {reason}",
            }

    artifact_dir = Path(_primary_evidence_dir())
    path = artifact_dir / f"{incident_id}.json"
    if not path.exists():
        return {"correlation_id": corr, "found": False, "path": str(path)}

    data = json.loads(path.read_text(encoding="utf-8"))
    return {"correlation_id": corr, "found": True, "path": str(path), "artifact": data}


@mcp.tool()
@_instrumented_tool("evidence_get_bundle")
def evidence_get_bundle(incident_id: str) -> dict:
    meta, request_id = _tool_request_meta("evidence.get_bundle")
    backend = _evidence_backend()
    corr = audit.write(
        "evidence.get_bundle",
        {"incident_id": incident_id, "backend": backend},
        ok=True,
        meta=meta,
        correlation_id=request_id,
    )

    if backend == "none":
        return {
            "correlation_id": corr,
            "found": False,
            "backend": "none",
            "error": "Evidence backend is disabled (EVIDENCE_BACKEND=none).",
        }

    if backend == "s3":
        out = read_evidence_bundle(incident_id)
        if not out.get("found"):
            out["correlation_id"] = corr
            out["backend"] = "s3"
            return out
        bundle = EvidenceBundle.model_validate(out["raw"])
        return {
            "correlation_id": corr,
            "found": True,
            "backend": "s3",
            "uri": out["uri"],
            "bundle": bundle.model_dump(),
        }

    # fs and airflow backends both support local file reads.
    fallback: dict[str, Any] | None = None
    for evidence_dir in _evidence_dirs():
        out = load_bundle(evidence_dir, incident_id)
        if out.get("found"):
            out["correlation_id"] = corr
            out["backend"] = backend
            return out
        if fallback is None:
            fallback = out

    fallback = fallback or {"found": False, "path": str(Path(_primary_evidence_dir()) / f"{incident_id}.json")}
    fallback["correlation_id"] = corr
    fallback["backend"] = backend
    return fallback


@mcp.tool()
@_instrumented_tool("evidence_wait_for_bundle")
def evidence_wait_for_bundle(incident_id: str, timeout_seconds: int = 30, poll_seconds: int = 2) -> dict:
    meta, request_id = _tool_request_meta("evidence.wait_for_bundle")
    corr = audit.write(
        "evidence.wait_for_bundle",
        {"incident_id": incident_id, "timeout_seconds": timeout_seconds, "poll_seconds": poll_seconds},
        ok=True,
        meta=meta,
        correlation_id=request_id,
    )

    def _getter(iid: str) -> dict:
        return evidence_get_bundle(iid)

    out = wait_for(_getter, incident_id, timeout_seconds=timeout_seconds, poll_seconds=poll_seconds)
    out["correlation_id"] = corr
    return out


@mcp.tool()
@_instrumented_tool("evidence_seed_sample")
def evidence_seed_sample(incident_id: str, service: str, window_minutes: int = 30) -> dict:
    """
    Offline helper: writes a deterministic Evidence Bundle v1 JSON to EVIDENCE_DIR.
    """
    meta, request_id = _tool_request_meta("evidence.seed_sample")
    window = max(1, int(window_minutes))
    corr = audit.write(
        "evidence.seed_sample",
        {"incident_id": incident_id, "service": service, "window_minutes": window},
        ok=True,
        meta=meta,
        correlation_id=request_id,
    )

    seed_offset = sum(ord(ch) for ch in f"{incident_id}:{service}") % (24 * 60)
    end = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=seed_offset)
    start = end - timedelta(minutes=window)
    generated = end + timedelta(minutes=1)

    bundle_dict = {
        "schema_version": "v1",
        "incident_id": incident_id,
        "service": service,
        "time_window": {
            "start_iso": start.isoformat(),
            "end_iso": end.isoformat(),
        },
        "alerts": [
            {
                "alert_id": f"alrt-{incident_id.lower()}-001",
                "provider": "mock",
                "service": service,
                "name": "Error rate elevated",
                "status": "triggered",
                "started_at_iso": start.isoformat(),
                "priority": "P2",
                "signal": {"key": "error_rate", "value": 0.12, "unit": "ratio"},
            }
        ],
        "signals": [
            {"key": "error_rate", "value": 0.12, "unit": "ratio"},
            {"key": "latency_p95_ms", "value": 840, "unit": "ms"},
            {"key": "rps", "value": 2100},
            {"key": "top_endpoint", "value": "POST /checkout"},
        ],
        "runbook_hits": [
            {
                "doc_id": "5xx-spike-checklist",
                "title": "5xx Spike Checklist",
                "score": 0.82,
                "summary": "Validate deploy changes and dependent service health.",
            }
        ],
        "hypotheses": [
            "Recent deploy introduced elevated failure rate on checkout path",
            "Downstream dependency latency is causing timeout amplification",
        ],
        "recommended_next_steps": [
            "Confirm deploy timeline against incident window",
            "Inspect dependency saturation and timeout rates",
            "Run 5xx spike checklist and compare before/after metrics",
        ],
        "links": [
            {"type": "dashboard", "url": "https://example.local/dashboards/payments"},
            {"type": "logs", "url": "https://example.local/logs?q=checkout+5xx"},
        ],
        "generated_at_iso": generated.isoformat(),
    }

    bundle = EvidenceBundle.model_validate(bundle_dict).model_dump()
    out_dir = Path(_primary_evidence_dir())
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{incident_id}.json"
    out_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "correlation_id": corr,
        "seeded": True,
        "backend": _evidence_backend(),
        "path": str(out_path),
        "bundle": bundle,
    }


@mcp.tool()
@_instrumented_tool("incident_triage_summary")
def incident_triage_summary(incident_id: str) -> dict:
    """
    Deterministic (non-LLM) summary of an incident from the Evidence Bundle.
    """
    meta, request_id = _tool_request_meta("incident.triage_summary")
    corr = audit.write(
        "incident.triage_summary",
        {"incident_id": incident_id},
        ok=True,
        meta=meta,
        correlation_id=request_id,
    )
    evidence = evidence_get_bundle(incident_id)

    if not evidence.get("found"):
        evidence["correlation_id"] = corr
        return evidence

    bundle = evidence.get("bundle") or {}
    uri = evidence.get("uri") or evidence.get("path")
    out = build_triage_summary(bundle, evidence_uri=uri)
    out["correlation_id"] = corr
    return out


@mcp.tool()
@_instrumented_tool("jira_draft_ticket")
def jira_draft_ticket(incident_id: str, project_key: str | None = None) -> dict:
    meta, request_id = _tool_request_meta("jira.draft_ticket")
    resolved_project_key = _jira_project_key(project_key)
    corr = audit.write(
        "jira.draft_ticket",
        {"incident_id": incident_id, "project_key": resolved_project_key},
        ok=True,
        meta=meta,
        correlation_id=request_id,
    )

    evidence = evidence_get_bundle(incident_id)
    if not evidence.get("found"):
        evidence["correlation_id"] = corr
        return evidence

    bundle = evidence.get("bundle") or {}
    uri = evidence.get("uri") or evidence.get("path")
    out = build_jira_draft(
        bundle,
        project_key=resolved_project_key,
        issue_type=_jira_issue_type(),
        evidence_uri=uri,
    )
    out["correlation_id"] = corr
    return out


@mcp.tool()
@_instrumented_tool("jira_create_ticket")
def jira_create_ticket(
    incident_id: str,
    project_key: str | None = None,
    dry_run: bool = True,
    reason: str | None = None,
    confirm_token: str | None = None,
    idempotency_key: str | None = None,
) -> dict:
    """
    Safe action:
    - dry_run=True by default (no mutation)
    - dry_run=False requires reason + confirm_token + idempotency_key + RBAC allow
    """
    meta, request_id = _tool_request_meta("jira.create_ticket")
    tool_name = "jira.create_ticket"
    resolved_project_key = _jira_project_key(project_key)
    resolved_issue_type = _jira_issue_type()
    normalized_idempotency_key = _normalized_idempotency_key(idempotency_key)
    corr = audit.write(
        "jira.create_ticket.request",
        {
            "incident_id": incident_id,
            "project_key": resolved_project_key,
            "issue_type": resolved_issue_type,
            "dry_run": dry_run,
            "role": role(),
            "idempotency_key": normalized_idempotency_key,
            "provider": provider_name(),
        },
        ok=True,
        meta=meta,
        correlation_id=request_id,
    )

    require_allowed(tool_name)

    if not dry_run and normalized_idempotency_key:
        existing = ticket_idempotency_store.get(normalized_idempotency_key)
        if existing:
            audit.write(
                "jira.create_ticket.idempotent_replay",
                {
                    "correlation_id": corr,
                    "idempotency_key": normalized_idempotency_key,
                    "issue_key": existing.get("issue_key"),
                },
                ok=True,
            )
            return {"correlation_id": corr, "dry_run": False, "idempotent_replay": True, **existing}

    evidence = evidence_get_bundle(incident_id)
    if not evidence.get("found"):
        evidence["correlation_id"] = corr
        return evidence

    bundle = evidence.get("bundle") or {}
    evidence_uri = evidence.get("uri") or evidence.get("path")

    try:
        draft = build_jira_draft(
            bundle,
            project_key=resolved_project_key,
            issue_type=resolved_issue_type,
            evidence_uri=evidence_uri,
        )
    except Exception as e:
        audit.write("jira.create_ticket.draft_error", {"error": str(e)}, ok=False)
        return {"created": False, "error": f"draft_failed: {e}"}

    try:
        enforce(
            SafeActionContext(
                tool_name=tool_name,
                role=role(),
                dry_run=dry_run,
                reason=reason,
                confirm_token=confirm_token,
                idempotency_key=normalized_idempotency_key,
            )
        )
    except SafeActionError as e:
        audit.write("jira.create_ticket.denied", {"correlation_id": corr, "error": str(e)}, ok=False)
        return {"correlation_id": corr, "created": False, "dry_run": dry_run, "error": str(e), "draft": draft}

    if dry_run:
        return {"correlation_id": corr, "created": False, "dry_run": True, "draft": draft}

    provider = get_provider()
    payload = {
        "project_key": resolved_project_key,
        "issue_type": resolved_issue_type,
        "title": draft["title"],
        "priority": draft["priority"],
        "labels": draft["labels"],
        "description_md": draft["description_md"],
        "evidence_uri": draft.get("evidence_uri"),
        "idempotency_key": normalized_idempotency_key,
        "reason": reason,
    }

    result = provider.create_issue(payload)

    if normalized_idempotency_key:
        ticket_idempotency_store.set(
            normalized_idempotency_key,
            {
                "created": bool(result.get("created", True)),
                "provider": result.get("provider"),
                "issue_key": result.get("issue_key"),
                "browse_url": result.get("browse_url"),
            },
        )

    audit.write(
        "jira.create_ticket.created",
        {
            "correlation_id": corr,
            "result": {k: result.get(k) for k in ["created", "issue_key", "browse_url", "provider"]},
        },
        ok=True,
    )
    return {"correlation_id": corr, "dry_run": False, **result}


@mcp.tool()
@_instrumented_tool("jira_list_projects")
def jira_list_projects() -> dict:
    meta, request_id = _tool_request_meta("jira.list_projects")
    provider = provider_name()
    corr = audit.write(
        "jira.list_projects",
        {"provider": provider},
        ok=True,
        meta=meta,
        correlation_id=request_id,
    )

    try:
        projects = get_provider().list_projects()
        return {"correlation_id": corr, "ok": True, "provider": provider, "projects": projects}
    except Exception as e:
        audit.write("jira.list_projects.error", {"error": str(e)}, ok=False)
        return {"correlation_id": corr, "ok": False, "provider": provider, "projects": [], "error": str(e)}


@mcp.tool()
@_instrumented_tool("jira_list_issue_types")
def jira_list_issue_types(project_key: str | None = None) -> dict:
    meta, request_id = _tool_request_meta("jira.list_issue_types")
    provider = provider_name()
    resolved_project_key = _jira_project_key(project_key)
    corr = audit.write(
        "jira.list_issue_types",
        {"provider": provider, "project_key": resolved_project_key},
        ok=True,
        meta=meta,
        correlation_id=request_id,
    )

    try:
        issue_types = get_provider().list_issue_types(resolved_project_key)
        return {
            "correlation_id": corr,
            "ok": True,
            "provider": provider,
            "project_key": resolved_project_key,
            "issue_types": issue_types,
        }
    except Exception as e:
        audit.write("jira.list_issue_types.error", {"error": str(e)}, ok=False)
        return {
            "correlation_id": corr,
            "ok": False,
            "provider": provider,
            "project_key": resolved_project_key,
            "issue_types": [],
            "error": str(e),
        }


@mcp.tool()
@_instrumented_tool("jira_validate_credentials")
def jira_validate_credentials() -> dict:
    meta, request_id = _tool_request_meta("jira.validate_credentials")
    corr = audit.write(
        "jira.validate_credentials",
        {},
        ok=True,
        meta=meta,
        correlation_id=request_id,
    )

    if provider_name() not in {"cloud", "servicenow"}:
        return {
            "correlation_id": corr,
            "ok": False,
            "error": "Set JIRA_PROVIDER=cloud or JIRA_PROVIDER=servicenow to validate ticket provider credentials.",
        }

    try:
        provider = get_provider()
        out = provider.validate()
        out["correlation_id"] = corr
        out["ok"] = True
        return out
    except Exception as e:
        audit.write("jira.validate_credentials.error", {"error": str(e)}, ok=False)
        return {"correlation_id": corr, "ok": False, "error": str(e)}


if _evidence_backend() == "airflow":
    # Airflow tools are discoverable only when explicitly requested.
    mcp.tool()(airflow_trigger_incident_dag)
    mcp.tool()(airflow_get_incident_artifact)


_register_http_health_routes()


def main() -> None:
    transport = os.getenv("MCP_TRANSPORT", CFG.mcp_transport or "stdio")
    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
