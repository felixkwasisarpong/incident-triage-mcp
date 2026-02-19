from __future__ import annotations
from incident_triage_mcp.audit import AuditLog
import os
from pathlib import Path
import json
from mcp.server.fastmcp import FastMCP
from incident_triage_mcp.adapters.datadog_mock import DatadogMock
from incident_triage_mcp.adapters.runbooks_local import RunbooksLocal
from incident_triage_mcp.adapters.airflow_api import AirflowAPI
from incident_triage_mcp.adapters.idempotency_store import FileIdempotencyStore
from incident_triage_mcp.tools.incidents import triage_incident_run
from incident_triage_mcp.tools.evidence import load_bundle
from incident_triage_mcp.tools.runbooks import search_runbooks as search_local_runbooks
from incident_triage_mcp.tools.waiter import wait_for
from incident_triage_mcp.adapters.artifacts_s3 import read_evidence_bundle
from incident_triage_mcp.domain_models import EvidenceBundle
from incident_triage_mcp.config import ConfigError,load_config
from incident_triage_mcp.tools.triage import build_triage_summary
from incident_triage_mcp.tools.jira_draft import build_jira_draft
from incident_triage_mcp.policy.rbac import require_allowed, role
from incident_triage_mcp.policy.safe_actions import SafeActionContext, enforce, SafeActionError
from incident_triage_mcp.adapters.jira_provider import get_provider, provider_name


try:
    CFG = load_config()
except ConfigError as e:
    raise SystemExit(f"[config] {e}") from e

_mcp_host = os.getenv("MCP_HOST", "127.0.0.1")
_mcp_port = int(os.getenv("MCP_PORT", "8000"))
mcp = FastMCP("Incident Triage MCP", json_response=True, host=_mcp_host, port=_mcp_port)
audit = AuditLog()
datadog = DatadogMock()
runbooks = RunbooksLocal()
airflow = AirflowAPI(base_url=os.getenv("AIRFLOW_BASE_URL", "http://localhost:8080"))
ticket_idempotency_store = FileIdempotencyStore(
    os.getenv("IDEMPOTENCY_STORE_PATH", "./data/jira_idempotency.json")
)


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


@mcp.tool()
def incident_triage_run(incident_id: str, service: str) -> dict:
    """
    One-call demo: alerts -> airflow evidence -> artifact -> summary.
    """
    corr = audit.write("incident.triage_run", {"incident_id": incident_id, "service": service}, ok=True)

    result = triage_incident_run(
        incident_id=incident_id,
        service=service,
        alerts_fetch_active=alerts_fetch_active,
        airflow_trigger_incident_dag=airflow_trigger_incident_dag,
        airflow_get_incident_artifact=airflow_get_incident_artifact,
        # tickets_create=tickets_create,  # uncomment when you wire Jira mock tool
    )

    result["correlation_id"] = corr
    return result


@mcp.tool()
def alerts_fetch_active(services: list[str] = None, since_minutes: int = 30, max_alerts: int = 50) -> dict:
    services = services or []
    args = {"services":services, "since_minutes": since_minutes, "max_alerts": max_alerts}
    corr = audit.write("alerts.fetch_active", args, ok=True)

    alerts = datadog.fetch_active_alerts(services, since_minutes, max_alerts)
    by_service = {}
    for a in alerts:
        by_service.setdefault(a["service"], []).append(a["alert_id"])

    return {"correlation_id": corr, "alerts": alerts, "grouping": {"by_service": by_service}}


@mcp.tool()
def service_health_snapshot(service: str, start_iso: str, end_iso: str) -> dict:
    args = {"service": service, "start_iso": start_iso, "end_iso": end_iso}
    corr = audit.write("service.health_snapshot", args, ok=True)

    snap = datadog.health_snapshot(service, start_iso, end_iso)
    return {"correlation_id": corr, "snapshot": snap}

@mcp.tool()
def runbooks_search(query: str, limit: int = 5) -> dict:
    args = {"query": query, "limit": limit}
    corr = audit.write("runbooks.search", args, ok=True)

    results = runbooks.search(query, limit)
    return {"correlation_id": corr, "results": results}

@mcp.tool()
def ping(message: str = "hello") -> dict:
    return {"ok": True, "message": message}

@mcp.tool()
def airflow_trigger_incident_dag(incident_id: str, service: str) -> dict:
    dag_id = "incident_evidence_v1"
    conf = {"incident_id": incident_id, "service": service}
    corr = audit.write("airflow.trigger_incident_dag", {"dag_id": dag_id, "conf": conf}, ok=True)

    run = airflow.trigger_dag(dag_id, conf)
    return {"correlation_id": corr, "dag_id": dag_id, "dag_run": run}

@mcp.tool()
def airflow_get_incident_artifact(incident_id: str) -> dict:
    corr = audit.write("airflow.get_incident_artifact", {"incident_id": incident_id}, ok=True)

    artifact_dir = Path(os.getenv("AIRFLOW_ARTIFACT_DIR", "/airflow_artifacts"))
    path = artifact_dir / f"{incident_id}.json"
    if not path.exists():
        return {"correlation_id": corr, "found": False, "path": str(path)}

    data = json.loads(path.read_text(encoding="utf-8"))
    return {"correlation_id": corr, "found": True, "path": str(path), "artifact": data}

def main() -> None:
    # stdio by default; for HTTP:
    # MCP_TRANSPORT=streamable-http python -m incident_triage_mcp.server
    transport = os.getenv("MCP_TRANSPORT", "stdio")
    mcp.run(transport=transport)


@mcp.tool()
def evidence_get_bundle(incident_id: str) -> dict:
    artifact_dir = os.getenv("AIRFLOW_ARTIFACT_DIR", "/airflow_artifacts")
    corr = audit.write("evidence.get_bundle", {"incident_id": incident_id, "artifact_dir": artifact_dir}, ok=True)
    out = load_bundle(artifact_dir, incident_id)
    out["correlation_id"] = corr
    return out

@mcp.tool()
def runbooks_search(query: str, limit: int = 5) -> dict:
    runbooks_dir = os.getenv("RUNBOOKS_DIR", "/runbooks")
    corr = audit.write("runbooks.search", {"query": query, "limit": limit, "runbooks_dir": runbooks_dir}, ok=True)
    hits = search_local_runbooks(runbooks_dir, query, limit)
    return {"correlation_id": corr, "results": hits}


@mcp.tool()
def evidence_wait_for_bundle(incident_id: str, timeout_seconds: int = 30, poll_seconds: int = 2) -> dict:
    corr = audit.write(
        "evidence.wait_for_bundle",
        {"incident_id": incident_id, "timeout_seconds": timeout_seconds, "poll_seconds": poll_seconds},
        ok=True,
    )

    # reuse your existing evidence_get_bundle implementation
    def _getter(iid: str) -> dict:
        return evidence_get_bundle(iid)

    out = wait_for(_getter, incident_id, timeout_seconds=timeout_seconds, poll_seconds=poll_seconds)
    out["correlation_id"] = corr
    return out



@mcp.tool()
def evidence_get_bundle(incident_id: str) -> dict:
    store = os.getenv("ARTIFACT_STORE", "s3").lower()
    corr = audit.write("evidence.get_bundle", {"incident_id": incident_id, "store": store}, ok=True)

    if store == "s3":
        out = read_evidence_bundle(incident_id)
        if not out.get("found"):
            out["correlation_id"] = corr
            return out
        bundle = EvidenceBundle.model_validate(out["raw"])
        return {"correlation_id": corr, "found": True, "uri": out["uri"], "bundle": bundle.model_dump()}

    # optional fs fallback if you still want it
    artifact_dir = os.getenv("AIRFLOW_ARTIFACT_DIR", "./airflow/artifacts")
    out = load_bundle(artifact_dir, incident_id)
    out["correlation_id"] = corr
    return out



@mcp.tool()
def incident_triage_summary(incident_id: str) -> dict:
    """
    Deterministic (non-LLM) summary of an incident from the Evidence Bundle.
    Great for recruiter demos and for agent planning.
    """
    corr = audit.write("incident.triage_summary", {"incident_id": incident_id}, ok=True)

    # Reuse your existing evidence getter (S3/MinIO)
    evidence = evidence_get_bundle(incident_id)

    if not evidence.get("found"):
        evidence["correlation_id"] = corr
        return evidence

    bundle = evidence.get("bundle") or {}
    uri = evidence.get("uri")
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

    # RBAC first
    require_allowed(tool_name)

    # For non-dry-run calls, replay existing result if this idempotency key has already been used.
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

    # Build the draft from the Evidence Bundle you already have
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

    # Enforce safe action (only if actually creating)
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
        # return a structured safe failure (still auditable)
        audit.write("jira.create_ticket.denied", {"correlation_id": corr, "error": str(e)}, ok=False)
        return {"correlation_id": corr, "created": False, "dry_run": dry_run, "error": str(e), "draft": draft}

    # If dry-run, do not create
    if dry_run:
        return {"correlation_id": corr, "created": False, "dry_run": True, "draft": draft}

    # Create via provider
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

    audit.write("jira.create_ticket.created", {"correlation_id": corr, "result": {k: result.get(k) for k in ["created","issue_key","browse_url","provider"]}}, ok=True)

    return {"correlation_id": corr, "dry_run": False, **result}


@mcp.tool()
def jira_list_projects() -> dict:
    """
    Read-only helper: list Jira projects visible to the configured credentials.
    """
    provider = provider_name()
    corr = audit.write("jira.list_projects", {"provider": provider}, ok=True)

    try:
        projects = get_provider().list_projects()
        return {
            "correlation_id": corr,
            "ok": True,
            "provider": provider,
            "projects": projects,
        }
    except Exception as e:
        audit.write("jira.list_projects.error", {"error": str(e)}, ok=False)
        return {
            "correlation_id": corr,
            "ok": False,
            "provider": provider,
            "projects": [],
            "error": str(e),
        }


@mcp.tool()
def jira_list_issue_types(project_key: str | None = None) -> dict:
    """
    Read-only helper: list available Jira issue types for a project key.
    """
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
    """
    Safe read-only Jira Cloud auth check. Does not create anything.
    """
    corr = audit.write("jira.validate_credentials", {}, ok=True)

    if provider_name() != "cloud":
        return {"correlation_id": corr, "ok": False, "error": "Set JIRA_PROVIDER=cloud to validate Jira Cloud credentials."}

    try:
        provider = get_provider()
        out = provider.validate()
        out["correlation_id"] = corr
        out["ok"] = True
        return out
    except Exception as e:
        audit.write("jira.validate_credentials.error", {"error": str(e)}, ok=False)
        return {"correlation_id": corr, "ok": False, "error": str(e)}

if __name__ == "__main__":
    main()
