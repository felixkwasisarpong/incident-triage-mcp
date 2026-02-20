from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
from mcp.server.fastmcp import FastMCP

from incident_triage_mcp.adapters.idempotency_store import FileIdempotencyStore
from incident_triage_mcp.adapters.jira_provider import get_provider, provider_name
from incident_triage_mcp.adapters.registry import build_observability_registry
from incident_triage_mcp.adapters.resilience import ResilienceError, ResiliencePolicy
from incident_triage_mcp.adapters.runbooks_local import RunbooksLocal
from incident_triage_mcp.adapters.artifacts_s3 import read_evidence_bundle
from incident_triage_mcp.audit import AuditLog
from incident_triage_mcp.config import ConfigError, load_config
from incident_triage_mcp.domain_models import EvidenceBundle
from incident_triage_mcp.policy.rbac import require_allowed, role
from incident_triage_mcp.policy.safe_actions import SafeActionContext, enforce, SafeActionError
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
)
# Backward-compatible test hook; currently points at alerts provider adapter.
datadog = observability.alerts_adapter
runbooks = RunbooksLocal()


def _build_idempotency_store():
    path = os.getenv("IDEMPOTENCY_STORE_PATH", "./data/jira_idempotency.json")
    try:
        return FileIdempotencyStore(path)
    except OSError:
        # Keep server bootable in read-only CWDs; idempotency replay is disabled.
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
def incident_triage_run(
    incident_id: str,
    service: str,
    include_ticket: bool = False,
    project_key: str | None = None,
    notify_slack: bool = False,
    slack_channel: str | None = None,
    slack_dry_run: bool = True,
) -> dict:
    """
    One-call triage orchestration.
    Airflow trigger is optional and backend-dependent.
    """
    resolved_project_key = _jira_project_key(project_key)
    corr = audit.write(
        "incident.triage_run",
        {
            "incident_id": incident_id,
            "service": service,
            "include_ticket": include_ticket,
            "project_key": resolved_project_key if include_ticket else None,
            "notify_slack": notify_slack,
            "slack_channel": slack_channel,
            "slack_dry_run": slack_dry_run,
            "evidence_backend": _evidence_backend(),
        },
        ok=True,
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
        tickets_create=tickets_create,
    )

    if notify_slack:
        try:
            result["slack"] = slack_post_update(
                incident_id=incident_id,
                service=service,
                summary=result.get("summary"),
                ticket=result.get("ticket"),
                channel=slack_channel,
                dry_run=slack_dry_run,
            )
        except Exception as e:
            result["slack"] = {
                "posted": False,
                "dry_run": slack_dry_run,
                "error": str(e),
            }

    result["correlation_id"] = corr
    return result


@mcp.tool()
def alerts_fetch_active(services: list[str] = None, since_minutes: int = 30, max_alerts: int = 50) -> dict:
    services = services or []
    args = {"services": services, "since_minutes": since_minutes, "max_alerts": max_alerts}
    corr = audit.write("alerts.fetch_active", args, ok=True)

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
def service_health_snapshot(service: str, start_iso: str, end_iso: str) -> dict:
    args = {"service": service, "start_iso": start_iso, "end_iso": end_iso}
    corr = audit.write("service.health_snapshot", args, ok=True)

    try:
        snap = observability.health_snapshot(service, start_iso, end_iso)
    except ResilienceError as e:
        audit.write("service.health_snapshot.error", {"error": e.to_dict()}, ok=False)
        return {"correlation_id": corr, "snapshot": {}, "error": e.to_dict()}

    return {"correlation_id": corr, "snapshot": snap}


@mcp.tool()
def runbooks_search(query: str, limit: int = 5) -> dict:
    runbooks_dir = os.getenv("RUNBOOKS_DIR", CFG.runbooks_dir)
    corr = audit.write("runbooks.search", {"query": query, "limit": limit, "runbooks_dir": runbooks_dir}, ok=True)
    hits = search_local_runbooks(runbooks_dir, query, limit)
    return {"correlation_id": corr, "results": hits}


@mcp.tool()
def ping(message: str = "hello") -> dict:
    return {"ok": True, "message": message}


@mcp.tool()
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
    )

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


def airflow_trigger_incident_dag(incident_id: str, service: str) -> dict:
    dag_id = "incident_evidence_v1"
    conf = {"incident_id": incident_id, "service": service}
    corr = audit.write(
        "airflow.trigger_incident_dag",
        {"dag_id": dag_id, "conf": conf, "evidence_backend": _evidence_backend()},
        ok=True,
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


def airflow_get_incident_artifact(incident_id: str) -> dict:
    corr = audit.write(
        "airflow.get_incident_artifact",
        {"incident_id": incident_id, "evidence_backend": _evidence_backend()},
        ok=True,
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
def evidence_get_bundle(incident_id: str) -> dict:
    backend = _evidence_backend()
    corr = audit.write("evidence.get_bundle", {"incident_id": incident_id, "backend": backend}, ok=True)

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
def evidence_wait_for_bundle(incident_id: str, timeout_seconds: int = 30, poll_seconds: int = 2) -> dict:
    corr = audit.write(
        "evidence.wait_for_bundle",
        {"incident_id": incident_id, "timeout_seconds": timeout_seconds, "poll_seconds": poll_seconds},
        ok=True,
    )

    def _getter(iid: str) -> dict:
        return evidence_get_bundle(iid)

    out = wait_for(_getter, incident_id, timeout_seconds=timeout_seconds, poll_seconds=poll_seconds)
    out["correlation_id"] = corr
    return out


@mcp.tool()
def evidence_seed_sample(incident_id: str, service: str, window_minutes: int = 30) -> dict:
    """
    Offline helper: writes a deterministic Evidence Bundle v1 JSON to EVIDENCE_DIR.
    """
    window = max(1, int(window_minutes))
    corr = audit.write(
        "evidence.seed_sample",
        {"incident_id": incident_id, "service": service, "window_minutes": window},
        ok=True,
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
def incident_triage_summary(incident_id: str) -> dict:
    """
    Deterministic (non-LLM) summary of an incident from the Evidence Bundle.
    """
    corr = audit.write("incident.triage_summary", {"incident_id": incident_id}, ok=True)
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
def jira_draft_ticket(incident_id: str, project_key: str | None = None) -> dict:
    resolved_project_key = _jira_project_key(project_key)
    corr = audit.write("jira.draft_ticket", {"incident_id": incident_id, "project_key": resolved_project_key}, ok=True)

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
    - dry_run=False requires reason + confirm_token + RBAC allow
    """
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
def jira_list_projects() -> dict:
    provider = provider_name()
    corr = audit.write("jira.list_projects", {"provider": provider}, ok=True)

    try:
        projects = get_provider().list_projects()
        return {"correlation_id": corr, "ok": True, "provider": provider, "projects": projects}
    except Exception as e:
        audit.write("jira.list_projects.error", {"error": str(e)}, ok=False)
        return {"correlation_id": corr, "ok": False, "provider": provider, "projects": [], "error": str(e)}


@mcp.tool()
def jira_list_issue_types(project_key: str | None = None) -> dict:
    provider = provider_name()
    resolved_project_key = _jira_project_key(project_key)
    corr = audit.write(
        "jira.list_issue_types",
        {"provider": provider, "project_key": resolved_project_key},
        ok=True,
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
def jira_validate_credentials() -> dict:
    corr = audit.write("jira.validate_credentials", {}, ok=True)

    if provider_name() != "cloud":
        return {
            "correlation_id": corr,
            "ok": False,
            "error": "Set JIRA_PROVIDER=cloud to validate Jira Cloud credentials.",
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


def main() -> None:
    transport = os.getenv("MCP_TRANSPORT", CFG.mcp_transport or "stdio")
    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
