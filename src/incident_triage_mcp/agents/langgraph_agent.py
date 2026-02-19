from __future__ import annotations

import argparse
import importlib
import json
import os
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph


class IncidentGraphState(TypedDict, total=False):
    incident_id: str
    service: str
    include_ticket: bool
    project_key: str | None
    notify_slack: bool
    slack_channel: str | None
    slack_dry_run: bool
<<<<<<< HEAD
    create_ticket_live: bool
    ticket_reason: str | None
    confirm_token: str | None
    idempotency_key: str | None
    live_ticket: dict[str, Any]
=======
>>>>>>> origin/main
    result: dict[str, Any]
    error: str


def _load_server_module():
    # Late import keeps agent startup lightweight and allows env to be set first.
    return importlib.import_module("incident_triage_mcp.server")


def _run_triage_node(state: IncidentGraphState) -> IncidentGraphState:
    server = _load_server_module()
    try:
        result = server.incident_triage_run(
            incident_id=state["incident_id"],
            service=state["service"],
            include_ticket=state.get("include_ticket", False),
            project_key=state.get("project_key"),
            notify_slack=state.get("notify_slack", False),
            slack_channel=state.get("slack_channel"),
            slack_dry_run=state.get("slack_dry_run", True),
        )
        return {"result": result}
    except Exception as exc:  # pragma: no cover - covered via run_agent tests
        return {"error": str(exc)}


def _route_after_triage(state: IncidentGraphState) -> str:
    if state.get("error"):
        return "failed"
<<<<<<< HEAD
    if state.get("create_ticket_live"):
        return "create_live_ticket"
    return "succeeded"


def _default_live_idempotency_key(state: IncidentGraphState) -> str:
    project = state.get("project_key") or os.getenv("JIRA_PROJECT_KEY", "INC") or "INC"
    return f"{state['incident_id']}-{project}-live"


def _create_live_ticket_node(state: IncidentGraphState) -> IncidentGraphState:
    server = _load_server_module()
    try:
        ticket = server.jira_create_ticket(
            incident_id=state["incident_id"],
            project_key=state.get("project_key"),
            dry_run=False,
            reason=state.get("ticket_reason"),
            confirm_token=state.get("confirm_token"),
            idempotency_key=state.get("idempotency_key") or _default_live_idempotency_key(state),
        )
        result = state.get("result")
        if isinstance(result, dict):
            merged = dict(result)
            merged["live_ticket"] = ticket
            return {"result": merged, "live_ticket": ticket}
        return {"live_ticket": ticket}
    except Exception as exc:  # pragma: no cover - covered via run_agent tests
        return {"error": str(exc)}


def _route_after_live_ticket(state: IncidentGraphState) -> str:
    if state.get("error"):
        return "failed"
=======
>>>>>>> origin/main
    return "succeeded"


def _identity_node(_state: IncidentGraphState) -> IncidentGraphState:
    return {}


def build_agent():
    graph = StateGraph(IncidentGraphState)
    graph.add_node("run_triage", _run_triage_node)
<<<<<<< HEAD
    graph.add_node("create_live_ticket", _create_live_ticket_node)
=======
>>>>>>> origin/main
    graph.add_node("succeeded", _identity_node)
    graph.add_node("failed", _identity_node)
    graph.set_entry_point("run_triage")
    graph.add_conditional_edges(
        "run_triage",
        _route_after_triage,
<<<<<<< HEAD
        {
            "create_live_ticket": "create_live_ticket",
            "succeeded": "succeeded",
            "failed": "failed",
        },
    )
    graph.add_conditional_edges(
        "create_live_ticket",
        _route_after_live_ticket,
=======
>>>>>>> origin/main
        {"succeeded": "succeeded", "failed": "failed"},
    )
    graph.add_edge("succeeded", END)
    graph.add_edge("failed", END)
    return graph.compile()


def run_agent(
    incident_id: str,
    service: str,
    include_ticket: bool = False,
    project_key: str | None = None,
    notify_slack: bool = False,
    slack_channel: str | None = None,
    slack_dry_run: bool = True,
<<<<<<< HEAD
    create_ticket_live: bool = False,
    ticket_reason: str | None = None,
    confirm_token: str | None = None,
    idempotency_key: str | None = None,
=======
>>>>>>> origin/main
) -> IncidentGraphState:
    app = build_agent()
    initial_state: IncidentGraphState = {
        "incident_id": incident_id,
        "service": service,
        "include_ticket": include_ticket,
        "project_key": project_key,
        "notify_slack": notify_slack,
        "slack_channel": slack_channel,
        "slack_dry_run": slack_dry_run,
<<<<<<< HEAD
        "create_ticket_live": create_ticket_live,
        "ticket_reason": ticket_reason,
        "confirm_token": confirm_token,
        "idempotency_key": idempotency_key,
=======
>>>>>>> origin/main
    }
    return app.invoke(initial_state)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run incident triage with a local LangGraph agent (no Claude required)."
    )
    parser.add_argument("--incident-id", required=True, help="Incident identifier, e.g. INC-123")
    parser.add_argument("--service", required=True, help="Service name, e.g. payments-api")
    parser.add_argument(
        "--artifact-store",
        choices=("fs", "s3"),
        default="fs",
        help="Artifact backend for this run (default: fs).",
    )
    parser.add_argument(
        "--artifact-dir",
        default="./airflow/artifacts",
        help="Filesystem artifact directory used when --artifact-store=fs.",
    )
    parser.add_argument("--include-ticket", action="store_true", help="Include Jira draft ticket hook")
    parser.add_argument("--project-key", help="Optional Jira project key override")
<<<<<<< HEAD
    parser.add_argument(
        "--create-ticket-live",
        action="store_true",
        help="Create Jira ticket for real after triage (requires reason + confirm token).",
    )
    parser.add_argument(
        "--ticket-reason",
        help="Required when --create-ticket-live is set.",
    )
    parser.add_argument(
        "--confirm-token",
        help="Safe-action confirm token; falls back to CONFIRM_TOKEN env.",
    )
    parser.add_argument(
        "--idempotency-key",
        help="Optional idempotency key for live ticket creation.",
    )
=======
>>>>>>> origin/main
    parser.add_argument("--notify-slack", action="store_true", help="Send Slack update via webhook tool")
    parser.add_argument("--slack-channel", help="Slack channel override (e.g. #incident-triage)")
    parser.add_argument(
        "--slack-live",
        action="store_true",
        help="Disable Slack dry-run mode (equivalent to slack_dry_run=false).",
    )
    parser.add_argument("--compact", action="store_true", help="Print compact JSON output")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
<<<<<<< HEAD
    confirm_token = args.confirm_token or os.getenv("CONFIRM_TOKEN")

    if args.create_ticket_live and not args.ticket_reason:
        parser.error("--ticket-reason is required when --create-ticket-live is set.")
    if args.create_ticket_live and not confirm_token:
        parser.error("--confirm-token (or CONFIRM_TOKEN env) is required when --create-ticket-live is set.")
=======
>>>>>>> origin/main

    # Force deterministic local defaults for CLI usage.
    os.environ["ARTIFACT_STORE"] = args.artifact_store
    if args.artifact_store == "fs":
        os.environ["AIRFLOW_ARTIFACT_DIR"] = args.artifact_dir

    state = run_agent(
        incident_id=args.incident_id,
        service=args.service,
        include_ticket=args.include_ticket,
        project_key=args.project_key,
        notify_slack=args.notify_slack,
        slack_channel=args.slack_channel,
        slack_dry_run=not args.slack_live,
<<<<<<< HEAD
        create_ticket_live=args.create_ticket_live,
        ticket_reason=args.ticket_reason,
        confirm_token=confirm_token,
        idempotency_key=args.idempotency_key,
=======
>>>>>>> origin/main
    )

    payload = {
        "ok": not bool(state.get("error")),
        "error": state.get("error"),
        "result": state.get("result"),
    }
    if args.compact:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))

    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
