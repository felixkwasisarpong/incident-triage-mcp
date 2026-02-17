from __future__ import annotations
from incident_triage_mcp.audit import AuditLog
import os
from pathlib import Path
import json
from mcp.server.fastmcp import FastMCP
from incident_triage_mcp.adapters.datadog_mock import DatadogMock
from incident_triage_mcp.adapters.runbooks_local import RunbooksLocal
from incident_triage_mcp.adapters.airflow_api import AirflowAPI
from incident_triage_mcp.tools.incidents import triage_incident_run
from incident_triage_mcp.tools.evidence import load_bundle
from incident_triage_mcp.tools.runbooks import search_runbooks as search_local_runbooks
from incident_triage_mcp.tools.waiter import wait_for
from incident_triage_mcp.adapters.artifacts_s3 import read_evidence_bundle
from incident_triage_mcp.domain_models import EvidenceBundle
from incident_triage_mcp.config import ConfigError,load_config
from incident_triage_mcp.tools.triage import build_triage_summary
from incident_triage_mcp.tools.jira_draft import build_jira_draft



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
def jira_draft_ticket(incident_id: str, project_key: str = "INC") -> dict:
    corr = audit.write("jira.draft_ticket", {"incident_id": incident_id, "project_key": project_key}, ok=True)

    evidence = evidence_get_bundle(incident_id)
    if not evidence.get("found"):
        evidence["correlation_id"] = corr
        return evidence

    bundle = evidence.get("bundle") or {}
    uri = evidence.get("uri") or evidence.get("path")
    out = build_jira_draft(bundle, evidence_uri=uri)
    out["project_key"] = project_key
    out["correlation_id"] = corr
    return out


if __name__ == "__main__":
    main()
