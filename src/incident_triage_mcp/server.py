from __future__ import annotations
from incident_triage_mcp.audit import AuditLog
import os
from mcp.server.fastmcp import FastMCP
from incident_triage_mcp.adapters.datadog_mock import DatadogMock
from incident_triage_mcp.adapters.runbooks_local import RunbooksLocal

mcp = FastMCP("Incident Triage MCP", json_response=True)

audit = AuditLog(path = os.getenv("AUDIT_PATH", "audit.jsonl"))
datadog = DatadogMock()
runbooks = RunbooksLocal()

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

def main() -> None:
    # stdio by default; for HTTP:
    # MCP_TRANSPORT=streamable-http python -m incident_triage_mcp.server
    transport = os.getenv("MCP_TRANSPORT", "stdio")
    mcp.run(transport=transport)

if __name__ == "__main__":
    main()
