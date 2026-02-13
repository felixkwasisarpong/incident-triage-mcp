from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, Any

def triage_incident_run(
    incident_id: str,
    service: str,
    alerts_fetch_active,
    airflow_trigger_incident_dag,
    airflow_get_incident_artifact,
    tickets_create=None,
) -> Dict[str, Any]:
    """
    Pure function orchestration: easy to test, no MCP imports.
    """
    # 1) Evidence: current alerts
    alerts = alerts_fetch_active(services=[service], since_minutes=30, max_alerts=50)

    # 2) Kick off Airflow evidence pipeline
    dag_run = airflow_trigger_incident_dag(incident_id=incident_id, service=service)

    # 3) Pull artifact (may not exist immediately; caller can re-call)
    artifact = airflow_get_incident_artifact(incident_id=incident_id)

    # 4) Simple summary (keep deterministic; don’t “invent”)
    summary = {
        "incident_id": incident_id,
        "service": service,
        "status": "triage_started",
        "alerts_count": len(alerts.get("alerts", [])),
        "artifact_found": artifact.get("found", False),
        "next_steps": [
            "Confirm if a deploy happened in the last 30 minutes",
            "Check top failing endpoint and dependency health",
            "Apply relevant runbook steps if match found",
        ],
    }

    out = {
        "summary": summary,
        "alerts": alerts,
        "airflow": {"dag_run": dag_run},
        "artifact": artifact,
    }

    # Optional: ticket
    if tickets_create is not None:
        ticket = tickets_create(
            title=f"[{service}] Incident {incident_id} triage started",
            body=f"Auto-triage summary: {summary}",
            severity="SEV2",
        )
        out["ticket"] = ticket

    return out

