from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import os
import time
from typing import Any, TypedDict

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from langgraph.graph import END, StateGraph


class IncidentGraphState(TypedDict, total=False):
    incident_id: str
    service: str
    include_ticket: bool
    project_key: str | None
    notify_slack: bool
    notify_provider: str | None
    slack_channel: str | None
    slack_dry_run: bool
    create_ticket_live: bool
    ticket_reason: str | None
    confirm_token: str | None
    idempotency_key: str | None
    mcp_url: str | None
    mcp_api_key: str | None
    mcp_client_id: str | None
    live_ticket: dict[str, Any]
    result: dict[str, Any]
    error: str


def _load_server_module():
    # Late import keeps agent startup lightweight and allows env to be set first.
    return importlib.import_module("incident_triage_mcp.server")


def _mcp_headers(api_key: str | None = None, client_id: str | None = None) -> dict[str, str] | None:
    headers: dict[str, str] = {}
    if api_key:
        headers["x-api-key"] = api_key
    if client_id:
        headers["x-client-id"] = client_id
    return headers or None


def _extract_tool_result_payload(result: Any) -> dict[str, Any]:
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        if getattr(result, "isError", False):
            raise RuntimeError(json.dumps(structured, ensure_ascii=False))
        return structured

    contents = getattr(result, "content", None) or []
    text_chunks: list[str] = []
    for item in contents:
        if getattr(item, "type", None) == "text":
            text = getattr(item, "text", "")
            if isinstance(text, str) and text:
                text_chunks.append(text)
    if text_chunks:
        joined = "\n".join(text_chunks)
        try:
            parsed = json.loads(joined)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            if getattr(result, "isError", False):
                raise RuntimeError(json.dumps(parsed, ensure_ascii=False))
            return parsed
        if getattr(result, "isError", False):
            raise RuntimeError(joined)
        return {"text": joined}

    if getattr(result, "isError", False):
        raise RuntimeError("Remote MCP tool call returned an error with no payload.")
    raise RuntimeError("Remote MCP tool call returned an unexpected payload format.")


def _flatten_exception_messages(exc: BaseException) -> list[str]:
    messages: list[str] = []
    stack: list[BaseException] = [exc]
    while stack:
        current = stack.pop(0)
        text = str(current).strip() or current.__class__.__name__
        messages.append(f"{current.__class__.__name__}: {text}")
        nested = getattr(current, "exceptions", None)
        if isinstance(nested, tuple):
            for child in nested:
                if isinstance(child, BaseException):
                    stack.append(child)
    return messages


def _format_agent_error(exc: BaseException) -> str:
    parts = _flatten_exception_messages(exc)
    # Preserve order but avoid repeating the same message text.
    unique_parts: list[str] = []
    seen: set[str] = set()
    for part in parts:
        if part in seen:
            continue
        seen.add(part)
        unique_parts.append(part)
    return " | ".join(unique_parts)


def _is_transient_mcp_client_error(exc: BaseException) -> bool:
    text = str(exc)
    transient_markers = (
        "TaskGroup",
        "EndOfStream",
        "BrokenResourceError",
        "ConnectionResetError",
        "RemoteProtocolError",
        "Server disconnected",
        "timed out",
        "timeout",
    )
    return any(marker in text for marker in transient_markers)


async def _mcp_call_tool_async(
    *,
    mcp_url: str,
    tool_name: str,
    arguments: dict[str, Any],
    api_key: str | None = None,
    client_id: str | None = None,
) -> dict[str, Any]:
    headers = _mcp_headers(api_key=api_key, client_id=client_id)
    async with streamablehttp_client(mcp_url, headers=headers) as (
        read_stream,
        write_stream,
        _get_session_id,
    ):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments=arguments)
            return _extract_tool_result_payload(result)


def _mcp_call_tool(
    *,
    mcp_url: str,
    tool_name: str,
    arguments: dict[str, Any],
    api_key: str | None = None,
    client_id: str | None = None,
) -> dict[str, Any]:
    attempts = max(1, int(os.getenv("MCP_CLIENT_RETRY_ATTEMPTS", "2")))
    delay_seconds = max(0.0, float(os.getenv("MCP_CLIENT_RETRY_DELAY_SECONDS", "0.25")))
    last_exc: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            return asyncio.run(
                _mcp_call_tool_async(
                    mcp_url=mcp_url,
                    tool_name=tool_name,
                    arguments=arguments,
                    api_key=api_key,
                    client_id=client_id,
                )
            )
        except Exception as exc:
            last_exc = exc
            if attempt >= attempts or not _is_transient_mcp_client_error(exc):
                raise
            time.sleep(delay_seconds)
    assert last_exc is not None  # pragma: no cover
    raise last_exc


def _remote_enabled(state: IncidentGraphState) -> bool:
    return bool((state.get("mcp_url") or "").strip())


def _run_triage_node(state: IncidentGraphState) -> IncidentGraphState:
    try:
        kwargs = {
            "incident_id": state["incident_id"],
            "service": state["service"],
            "include_ticket": state.get("include_ticket", False),
            "project_key": state.get("project_key"),
            "notify_slack": state.get("notify_slack", False),
            "notify_provider": state.get("notify_provider"),
            "slack_channel": state.get("slack_channel"),
            "slack_dry_run": state.get("slack_dry_run", True),
        }
        if _remote_enabled(state):
            result = _mcp_call_tool(
                mcp_url=(state.get("mcp_url") or "").strip(),
                tool_name="incident_triage_run",
                arguments=kwargs,
                api_key=state.get("mcp_api_key"),
                client_id=state.get("mcp_client_id"),
            )
        else:
            server = _load_server_module()
            result = server.incident_triage_run(**kwargs)
        return {"result": result}
    except Exception as exc:  # pragma: no cover - covered via run_agent tests
        return {"error": _format_agent_error(exc)}


def _route_after_triage(state: IncidentGraphState) -> str:
    if state.get("error"):
        return "failed"
    if state.get("create_ticket_live"):
        return "create_live_ticket"
    return "succeeded"


def _default_live_idempotency_key(state: IncidentGraphState) -> str:
    project = state.get("project_key") or os.getenv("JIRA_PROJECT_KEY", "INC") or "INC"
    return f"{state['incident_id']}-{project}-live"


def _create_live_ticket_node(state: IncidentGraphState) -> IncidentGraphState:
    try:
        kwargs = {
            "incident_id": state["incident_id"],
            "project_key": state.get("project_key"),
            "dry_run": False,
            "reason": state.get("ticket_reason"),
            "confirm_token": state.get("confirm_token"),
            "idempotency_key": state.get("idempotency_key") or _default_live_idempotency_key(state),
        }
        if _remote_enabled(state):
            ticket = _mcp_call_tool(
                mcp_url=(state.get("mcp_url") or "").strip(),
                tool_name="jira_create_ticket",
                arguments=kwargs,
                api_key=state.get("mcp_api_key"),
                client_id=state.get("mcp_client_id"),
            )
        else:
            server = _load_server_module()
            ticket = server.jira_create_ticket(**kwargs)
        result = state.get("result")
        if isinstance(result, dict):
            merged = dict(result)
            merged["live_ticket"] = ticket
            return {"result": merged, "live_ticket": ticket}
        return {"live_ticket": ticket}
    except Exception as exc:  # pragma: no cover - covered via run_agent tests
        return {"error": _format_agent_error(exc)}


def _route_after_live_ticket(state: IncidentGraphState) -> str:
    if state.get("error"):
        return "failed"
    return "succeeded"


def _identity_node(_state: IncidentGraphState) -> IncidentGraphState:
    return {}


def build_agent():
    graph = StateGraph(IncidentGraphState)
    graph.add_node("run_triage", _run_triage_node)
    graph.add_node("create_live_ticket", _create_live_ticket_node)
    graph.add_node("succeeded", _identity_node)
    graph.add_node("failed", _identity_node)
    graph.set_entry_point("run_triage")
    graph.add_conditional_edges(
        "run_triage",
        _route_after_triage,
        {
            "create_live_ticket": "create_live_ticket",
            "succeeded": "succeeded",
            "failed": "failed",
        },
    )
    graph.add_conditional_edges(
        "create_live_ticket",
        _route_after_live_ticket,
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
    notify_provider: str | None = None,
    slack_channel: str | None = None,
    slack_dry_run: bool = True,
    create_ticket_live: bool = False,
    ticket_reason: str | None = None,
    confirm_token: str | None = None,
    idempotency_key: str | None = None,
    mcp_url: str | None = None,
    mcp_api_key: str | None = None,
    mcp_client_id: str | None = None,
) -> IncidentGraphState:
    app = build_agent()
    initial_state: IncidentGraphState = {
        "incident_id": incident_id,
        "service": service,
        "include_ticket": include_ticket,
        "project_key": project_key,
        "notify_slack": notify_slack,
        "notify_provider": notify_provider,
        "slack_channel": slack_channel,
        "slack_dry_run": slack_dry_run,
        "create_ticket_live": create_ticket_live,
        "ticket_reason": ticket_reason,
        "confirm_token": confirm_token,
        "idempotency_key": idempotency_key,
        "mcp_url": mcp_url,
        "mcp_api_key": mcp_api_key,
        "mcp_client_id": mcp_client_id,
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
    parser.add_argument("--notify-slack", action="store_true", help="Send Slack update via webhook tool")
    parser.add_argument(
        "--notify-provider",
        choices=("slack", "teams"),
        help="Notification provider for --notify-slack (default comes from NOTIFY_PROVIDER).",
    )
    parser.add_argument("--slack-channel", help="Slack channel override (e.g. #incident-triage)")
    parser.add_argument(
        "--slack-live",
        action="store_true",
        help="Disable Slack dry-run mode (equivalent to slack_dry_run=false).",
    )
    parser.add_argument(
        "--mcp-url",
        help="Remote MCP streamable-http URL (if set, agent calls MCP over network instead of importing local server).",
    )
    parser.add_argument(
        "--mcp-api-key",
        help="Optional API key for remote MCP HTTP auth (sent as x-api-key).",
    )
    parser.add_argument(
        "--mcp-client-id",
        default="incident-triage-agent",
        help="Optional x-client-id header for remote MCP HTTP auth/audit (default: incident-triage-agent).",
    )
    parser.add_argument("--compact", action="store_true", help="Print compact JSON output")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    confirm_token = args.confirm_token or os.getenv("CONFIRM_TOKEN")

    if args.create_ticket_live and not args.ticket_reason:
        parser.error("--ticket-reason is required when --create-ticket-live is set.")
    if args.create_ticket_live and not confirm_token:
        parser.error("--confirm-token (or CONFIRM_TOKEN env) is required when --create-ticket-live is set.")

    mcp_api_key = args.mcp_api_key or os.getenv("MCP_HTTP_API_KEY")
    if args.mcp_url:
        mcp_url = args.mcp_url.strip()
        if not mcp_url:
            parser.error("--mcp-url cannot be empty.")
    else:
        mcp_url = None
        # Force deterministic local defaults for CLI usage only in in-process mode.
        os.environ["EVIDENCE_BACKEND"] = args.artifact_store
        os.environ["ARTIFACT_STORE"] = args.artifact_store
        if args.artifact_store == "fs":
            os.environ["EVIDENCE_DIR"] = args.artifact_dir
            os.environ["AIRFLOW_ARTIFACT_DIR"] = args.artifact_dir

    state = run_agent(
        incident_id=args.incident_id,
        service=args.service,
        include_ticket=args.include_ticket,
        project_key=args.project_key,
        notify_slack=args.notify_slack,
        notify_provider=args.notify_provider,
        slack_channel=args.slack_channel,
        slack_dry_run=not args.slack_live,
        create_ticket_live=args.create_ticket_live,
        ticket_reason=args.ticket_reason,
        confirm_token=confirm_token,
        idempotency_key=args.idempotency_key,
        mcp_url=mcp_url,
        mcp_api_key=mcp_api_key,
        mcp_client_id=args.mcp_client_id,
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
