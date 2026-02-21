from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from typing import Any, Dict
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _reload_server_module():
    _ensure_mcp_stub()
    import incident_triage_mcp.policy.rbac as rbac
    import incident_triage_mcp.policy.safe_actions as safe_actions
    import incident_triage_mcp.server as server

    importlib.reload(rbac)
    importlib.reload(safe_actions)
    return importlib.reload(server)


def _ensure_mcp_stub() -> None:
    mcp_module = types.ModuleType("mcp")
    server_module = types.ModuleType("mcp.server")
    fastmcp_module = types.ModuleType("mcp.server.fastmcp")

    class FastMCP:  # pragma: no cover - tiny shim used only when mcp is absent
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        def tool(self):
            def decorator(fn):
                return fn

            return decorator

        def run(self, transport: str = "stdio") -> None:
            return None

    fastmcp_module.FastMCP = FastMCP
    server_module.fastmcp = fastmcp_module
    mcp_module.server = server_module

    sys.modules["mcp"] = mcp_module
    sys.modules["mcp.server"] = server_module
    sys.modules["mcp.server.fastmcp"] = fastmcp_module


def _bundle(incident_id: str = "INC-123") -> Dict[str, Any]:
    return {
        "schema_version": "v1",
        "incident_id": incident_id,
        "service": "payments-api",
        "time_window": {
            "start_iso": "2026-01-01T00:00:00Z",
            "end_iso": "2026-01-01T00:30:00Z",
        },
        "alerts": [],
        "signals": [],
        "runbook_hits": [],
        "hypotheses": [],
        "recommended_next_steps": [],
        "links": [],
        "generated_at_iso": "2026-01-01T00:31:00Z",
    }


class TestServerTools(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)

        self.env_patcher = patch.dict(
            os.environ,
            {
                "MCP_TRANSPORT": "stdio",
                "MCP_PORT": "3333",
                "EVIDENCE_BACKEND": "fs",
                "EVIDENCE_DIR": self.tmpdir.name,
                "ARTIFACT_STORE": "fs",
                "AIRFLOW_ARTIFACT_DIR": self.tmpdir.name,
                "RUNBOOKS_DIR": self.tmpdir.name,
                "MCP_ROLE": "responder",
                "JIRA_PROJECT_KEY": "SCRUM",
                "JIRA_ISSUE_TYPE": "Task",
                "CONFIRM_TOKEN": "test-confirm-token",
                "IDEMPOTENCY_STORE_PATH": str(Path(self.tmpdir.name) / "jira_idempotency.json"),
            },
            clear=False,
        )
        self.env_patcher.start()
        self.addCleanup(self.env_patcher.stop)

        self.server = _reload_server_module()
        self._attach_fake_audit(self.server)

    def _attach_fake_audit(self, server_module) -> None:
        self.audit_calls = []
        self._corr_counter = 0

        def fake_write(tool: str, arguments: Dict[str, Any], ok: bool, meta=None, correlation_id=None):
            self._corr_counter += 1
            corr = correlation_id or f"corr-{self._corr_counter}"
            self.audit_calls.append(
                {
                    "tool": tool,
                    "arguments": arguments,
                    "ok": ok,
                    "meta": meta or {},
                    "correlation_id": corr,
                }
            )
            return corr

        server_module.audit.write = Mock(side_effect=fake_write)

    def _reload_and_attach(self) -> Any:
        server = _reload_server_module()
        self._attach_fake_audit(server)
        return server

    def test_ping(self) -> None:
        self.assertEqual(self.server.ping(), {"ok": True, "message": "hello"})
        self.assertEqual(self.server.ping("hi"), {"ok": True, "message": "hi"})

    def test_ping_audit_meta_contains_auth_fields(self) -> None:
        self.server.ping("meta-check")
        self.assertGreaterEqual(len(self.audit_calls), 1)
        meta = self.audit_calls[0]["meta"]
        for key in ["transport", "auth_mode", "auth_required", "authenticated", "principal", "request_id"]:
            self.assertIn(key, meta)

    def test_mcp_health(self) -> None:
        out = self.server.mcp_health()
        self.assertEqual(out["correlation_id"], "corr-1")
        self.assertTrue(out["ok"])
        self.assertIn(out["status"], {"healthy", "degraded"})
        self.assertIn("uptime_seconds", out)
        self.assertIn("providers", out)
        self.assertIn("transport", out)

    def test_mcp_metrics_includes_tool_activity(self) -> None:
        self.server.ping("probe")
        out = self.server.mcp_metrics()
        self.assertEqual(out["correlation_id"], "corr-2")
        self.assertIn("totals", out)
        self.assertGreaterEqual(out["totals"]["tool_calls_total"], 1)
        self.assertIn("ping", out["tools"])
        self.assertGreaterEqual(out["tools"]["ping"]["calls_total"], 1)

    def test_http_health_payload_shape(self) -> None:
        out = self.server._http_health_payload()
        self.assertTrue(out["ok"])
        self.assertIn("service", out)
        self.assertIn("providers", out)
        self.assertIn("transport", out)
        self.assertIn("evidence_backend", out)
        self.assertIn("airflow", out)

    def test_http_metrics_payload_shape(self) -> None:
        self.server.ping("metric-probe")
        out = self.server._http_metrics_payload()
        self.assertIn("service", out)
        self.assertIn("totals", out)
        self.assertIn("tools", out)
        self.assertIn("providers", out)
        self.assertIn("transport", out)
        self.assertIn("evidence_backend", out)

    def test_http_auth_api_key_denies_missing_header(self) -> None:
        with patch.dict(
            os.environ,
            {
                "MCP_TRANSPORT": "streamable-http",
                "MCP_HTTP_AUTH_MODE": "api_key",
                "MCP_HTTP_API_KEY": "test-api-key",
            },
            clear=False,
        ):
            server = self._reload_and_attach()
            with self.assertRaises(server.HTTPAuthError):
                server.ping("secure")

    def test_http_auth_api_key_allows_valid_header(self) -> None:
        with patch.dict(
            os.environ,
            {
                "MCP_TRANSPORT": "streamable-http",
                "MCP_HTTP_AUTH_MODE": "api_key",
                "MCP_HTTP_API_KEY": "test-api-key",
            },
            clear=False,
        ):
            server = self._reload_and_attach()
            with patch.object(
                server,
                "_request_headers",
                return_value={
                    "x-api-key": "test-api-key",
                    "x-client-id": "staging-gateway",
                    "x-request-id": "req-123",
                },
            ):
                out = server.ping("secure")

        self.assertEqual(out, {"ok": True, "message": "secure"})
        self.assertEqual(self.audit_calls[0]["meta"]["authenticated"], True)
        self.assertEqual(self.audit_calls[0]["meta"]["principal"], "staging-gateway")
        self.assertEqual(self.audit_calls[0]["meta"]["request_id"], "req-123")

    def test_request_headers_handles_missing_request_context(self) -> None:
        class _ContextWithoutRequest:
            @property
            def request_context(self):
                raise ValueError("Context is not available outside of a request")

        with patch.object(self.server.mcp, "get_context", return_value=_ContextWithoutRequest(), create=True):
            headers = self.server._request_headers()

        self.assertEqual(headers, {})

    def test_slack_post_update_dry_run(self) -> None:
        out = self.server.slack_post_update(
            incident_id="INC-100",
            service="payments-api",
            summary={"status": "triage_started", "alerts_count": 2, "next_steps": ["Check logs"]},
            ticket={"dry_run": True},
        )

        self.assertEqual(out["correlation_id"], "corr-1")
        self.assertFalse(out["posted"])
        self.assertTrue(out["dry_run"])
        self.assertIn("payload", out)
        self.assertIn("Incident Update", out["payload"]["text"])

    def test_slack_post_update_live_missing_webhook(self) -> None:
        with patch.dict(os.environ, {"SLACK_WEBHOOK_URL": ""}, clear=False):
            out = self.server.slack_post_update(
                incident_id="INC-101",
                service="payments-api",
                dry_run=False,
            )

        self.assertEqual(out["correlation_id"], "corr-1")
        self.assertFalse(out["posted"])
        self.assertFalse(out["dry_run"])
        self.assertIn("SLACK_WEBHOOK_URL", out["error"])

    def test_slack_post_update_live_success(self) -> None:
        response = Mock()
        response.raise_for_status.return_value = None
        with patch.dict(os.environ, {"SLACK_WEBHOOK_URL": "https://hooks.slack.test/abc"}, clear=False), patch.object(
            self.server.requests, "post", return_value=response
        ) as post_mock:
            out = self.server.slack_post_update(
                incident_id="INC-102",
                service="payments-api",
                channel="#incident-triage",
                dry_run=False,
            )

        post_mock.assert_called_once()
        payload = post_mock.call_args.kwargs["json"]
        self.assertEqual(payload["channel"], "#incident-triage")
        self.assertIn("INC-102", payload["text"])
        self.assertTrue(out["posted"])
        self.assertFalse(out["dry_run"])

    def test_slack_post_update_live_rbac_denied(self) -> None:
        with patch.dict(os.environ, {"MCP_ROLE": "triager"}, clear=False):
            server = self._reload_and_attach()
            with patch.object(server.requests, "post") as post_mock:
                with self.assertRaises(RuntimeError):
                    server.slack_post_update(
                        incident_id="INC-103",
                        service="payments-api",
                        dry_run=False,
                    )

        post_mock.assert_not_called()

    def test_teams_post_update_dry_run(self) -> None:
        out = self.server.teams_post_update(
            incident_id="INC-200",
            service="payments-api",
            summary={"status": "triage_started", "alerts_count": 2, "next_steps": ["Check logs"]},
            ticket={"dry_run": True},
        )

        self.assertEqual(out["correlation_id"], "corr-1")
        self.assertFalse(out["posted"])
        self.assertTrue(out["dry_run"])
        self.assertIn("payload", out)
        self.assertEqual(out["payload"]["@type"], "MessageCard")
        self.assertIn("Incident Update", out["payload"]["title"])

    def test_teams_post_update_live_missing_webhook(self) -> None:
        with patch.dict(os.environ, {"TEAMS_WEBHOOK_URL": ""}, clear=False):
            out = self.server.teams_post_update(
                incident_id="INC-201",
                service="payments-api",
                dry_run=False,
            )

        self.assertEqual(out["correlation_id"], "corr-1")
        self.assertFalse(out["posted"])
        self.assertFalse(out["dry_run"])
        self.assertIn("TEAMS_WEBHOOK_URL", out["error"])

    def test_teams_post_update_live_success(self) -> None:
        with patch.dict(os.environ, {"TEAMS_WEBHOOK_URL": "https://hooks.teams.test/abc"}, clear=False), patch.object(
            self.server, "post_teams_webhook"
        ) as post_mock:
            out = self.server.teams_post_update(
                incident_id="INC-202",
                service="payments-api",
                channel="Incident Triage",
                dry_run=False,
            )

        post_mock.assert_called_once()
        payload = post_mock.call_args.args[1]
        self.assertEqual(payload["@type"], "MessageCard")
        self.assertIn("INC-202", payload["title"])
        self.assertTrue(out["posted"])
        self.assertFalse(out["dry_run"])

    def test_teams_post_update_live_rbac_denied(self) -> None:
        with patch.dict(os.environ, {"MCP_ROLE": "triager"}, clear=False):
            server = self._reload_and_attach()
            with patch.object(server, "post_teams_webhook") as post_mock:
                with self.assertRaises(RuntimeError):
                    server.teams_post_update(
                        incident_id="INC-203",
                        service="payments-api",
                        dry_run=False,
                    )

        post_mock.assert_not_called()

    def test_incident_triage_run(self) -> None:
        with patch.object(self.server, "triage_incident_run", return_value={"status": "ok"}) as run_mock:
            out = self.server.incident_triage_run("INC-1", "payments-api")

        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["correlation_id"], "corr-1")
        self.assertEqual(run_mock.call_args.kwargs["incident_id"], "INC-1")
        self.assertEqual(run_mock.call_args.kwargs["service"], "payments-api")
        self.assertIs(run_mock.call_args.kwargs["alerts_fetch_active"], self.server.alerts_fetch_active)
        self.assertIs(run_mock.call_args.kwargs["airflow_trigger_incident_dag"], self.server.airflow_trigger_incident_dag)
        self.assertIs(run_mock.call_args.kwargs["airflow_get_incident_artifact"], self.server.airflow_get_incident_artifact)
        self.assertIsNone(run_mock.call_args.kwargs["tickets_create"])

    def test_incident_triage_run_with_ticket_hook(self) -> None:
        def fake_triage(**kwargs):
            ticket = kwargs["tickets_create"]("title", "body", "SEV2")
            return {"status": "ok", "ticket": ticket}

        with patch.object(self.server, "triage_incident_run", side_effect=fake_triage) as run_mock, patch.object(
            self.server, "jira_create_ticket", return_value={"created": False, "dry_run": True, "draft": {"title": "x"}}
        ) as jira_mock:
            out = self.server.incident_triage_run("INC-2", "payments-api", include_ticket=True, project_key="PAY")

        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["correlation_id"], "corr-1")
        self.assertTrue("ticket" in out)
        self.assertIsNotNone(run_mock.call_args.kwargs["tickets_create"])
        jira_mock.assert_called_once_with(
            incident_id="INC-2",
            project_key="PAY",
            dry_run=True,
        )

    def test_incident_triage_run_with_ticket_hook_keyword_payload(self) -> None:
        def fake_triage(**kwargs):
            ticket = kwargs["tickets_create"](title="title", body="body", severity="SEV2")
            return {"status": "ok", "ticket": ticket}

        with patch.object(self.server, "triage_incident_run", side_effect=fake_triage), patch.object(
            self.server, "jira_create_ticket", return_value={"created": False, "dry_run": True, "draft": {"title": "x"}}
        ) as jira_mock:
            out = self.server.incident_triage_run("INC-2", "payments-api", include_ticket=True, project_key="PAY")

        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["correlation_id"], "corr-1")
        self.assertIn("ticket", out)
        jira_mock.assert_called_once_with(
            incident_id="INC-2",
            project_key="PAY",
            dry_run=True,
        )

    def test_incident_triage_run_with_ticket_hook_handles_error(self) -> None:
        def fake_triage(**kwargs):
            return {"status": "ok", "ticket": kwargs["tickets_create"]("title", "body", "SEV2")}

        with patch.object(self.server, "triage_incident_run", side_effect=fake_triage), patch.object(
            self.server, "jira_create_ticket", side_effect=RuntimeError("Role 'viewer' is not allowed to call 'jira.create_ticket'.")
        ):
            out = self.server.incident_triage_run("INC-3", "payments-api", include_ticket=True)

        self.assertEqual(out["status"], "ok")
        self.assertFalse(out["ticket"]["created"])
        self.assertTrue(out["ticket"]["dry_run"])
        self.assertIn("not allowed", out["ticket"]["error"])

    def test_incident_triage_run_with_slack_notify(self) -> None:
        with patch.object(
            self.server,
            "triage_incident_run",
            return_value={"status": "ok", "summary": {"status": "triage_started"}, "ticket": {"issue_key": "PAY-1"}},
        ), patch.object(
            self.server,
            "slack_post_update",
            return_value={"posted": False, "dry_run": True, "payload": {"text": "preview"}},
        ) as slack_mock:
            out = self.server.incident_triage_run(
                "INC-4",
                "payments-api",
                notify_slack=True,
                slack_channel="#incident-triage",
                slack_dry_run=True,
            )

        self.assertEqual(out["correlation_id"], "corr-1")
        self.assertIn("slack", out)
        slack_mock.assert_called_once_with(
            incident_id="INC-4",
            service="payments-api",
            summary={"status": "triage_started"},
            ticket={"issue_key": "PAY-1"},
            channel="#incident-triage",
            dry_run=True,
        )

    def test_incident_triage_run_with_slack_notify_handles_error(self) -> None:
        with patch.object(
            self.server,
            "triage_incident_run",
            return_value={"status": "ok", "summary": {"status": "triage_started"}},
        ), patch.object(self.server, "slack_post_update", side_effect=RuntimeError("webhook timeout")):
            out = self.server.incident_triage_run("INC-5", "payments-api", notify_slack=True, slack_dry_run=False)

        self.assertEqual(out["correlation_id"], "corr-1")
        self.assertFalse(out["slack"]["posted"])
        self.assertFalse(out["slack"]["dry_run"])
        self.assertIn("timeout", out["slack"]["error"])

    def test_incident_triage_run_with_teams_notify(self) -> None:
        with patch.object(
            self.server,
            "triage_incident_run",
            return_value={"status": "ok", "summary": {"status": "triage_started"}, "ticket": {"issue_key": "PAY-1"}},
        ), patch.object(
            self.server,
            "teams_post_update",
            return_value={"posted": False, "dry_run": True, "payload": {"title": "preview"}},
        ) as teams_mock:
            out = self.server.incident_triage_run(
                "INC-6",
                "payments-api",
                notify_slack=True,
                notify_provider="teams",
                slack_channel="Incident Triage",
                slack_dry_run=True,
            )

        self.assertEqual(out["correlation_id"], "corr-1")
        self.assertIn("teams", out)
        teams_mock.assert_called_once_with(
            incident_id="INC-6",
            service="payments-api",
            summary={"status": "triage_started"},
            ticket={"issue_key": "PAY-1"},
            channel="Incident Triage",
            dry_run=True,
        )

    def test_incident_triage_run_with_teams_notify_handles_error(self) -> None:
        with patch.object(
            self.server,
            "triage_incident_run",
            return_value={"status": "ok", "summary": {"status": "triage_started"}},
        ), patch.object(self.server, "teams_post_update", side_effect=RuntimeError("teams webhook timeout")):
            out = self.server.incident_triage_run(
                "INC-7",
                "payments-api",
                notify_slack=True,
                notify_provider="teams",
                slack_dry_run=False,
            )

        self.assertEqual(out["correlation_id"], "corr-1")
        self.assertFalse(out["teams"]["posted"])
        self.assertFalse(out["teams"]["dry_run"])
        self.assertIn("timeout", out["teams"]["error"])

    def test_alerts_fetch_active(self) -> None:
        alerts = [
            {"alert_id": "a1", "service": "payments-api"},
            {"alert_id": "a2", "service": "payments-api"},
            {"alert_id": "b1", "service": "orders-api"},
        ]
        with patch.object(self.server.datadog, "fetch_active_alerts", return_value=alerts) as fetch_mock:
            out = self.server.alerts_fetch_active(["payments-api"], since_minutes=60, max_alerts=10)

        fetch_mock.assert_called_once_with(["payments-api"], 60, 10)
        self.assertEqual(out["correlation_id"], "corr-1")
        self.assertEqual(out["alerts"], alerts)
        self.assertEqual(out["grouping"]["by_service"]["payments-api"], ["a1", "a2"])
        self.assertEqual(out["grouping"]["by_service"]["orders-api"], ["b1"])

    def test_service_health_snapshot(self) -> None:
        snapshot = {"status": "degraded", "service": "payments-api"}
        with patch.object(self.server.datadog, "health_snapshot", return_value=snapshot) as snap_mock:
            out = self.server.service_health_snapshot("payments-api", "start", "end")

        snap_mock.assert_called_once_with("payments-api", "start", "end")
        self.assertEqual(out, {"correlation_id": "corr-1", "snapshot": snapshot})

    def test_logs_fetch_recent(self) -> None:
        logs = [
            {"timestamp": "2026-01-01T00:01:00Z", "message": "timeout", "level": "error"},
            {"timestamp": "2026-01-01T00:00:30Z", "message": "retrying", "level": "warning"},
        ]
        with patch.object(self.server.observability, "fetch_logs", return_value=logs) as logs_mock:
            out = self.server.logs_fetch_recent("payments-api", "start", "end", limit=50)

        logs_mock.assert_called_once_with("payments-api", "start", "end", 50)
        self.assertEqual(out["correlation_id"], "corr-1")
        self.assertEqual(out["logs"], logs)

    def test_logs_fetch_recent_handles_resilience_error(self) -> None:
        err = self.server.ResilienceError(
            provider="elk",
            operation="fetch_logs",
            kind="adapter_call_failed",
            message="elk.fetch_logs failed after 1 attempt(s)",
            attempts=1,
            retriable=True,
            cause=RuntimeError("index not found"),
        )
        with patch.object(self.server.observability, "fetch_logs", side_effect=err):
            out = self.server.logs_fetch_recent("payments-api", "start", "end", limit=10)

        self.assertEqual(out["correlation_id"], "corr-1")
        self.assertEqual(out["logs"], [])
        self.assertIn("error", out)
        self.assertEqual(out["error"]["operation"], "fetch_logs")
        self.assertEqual(out["error"]["provider"], "elk")

    def test_traces_fetch_recent(self) -> None:
        traces = [
            {"trace_id": "trc-1", "status": "error", "duration_ms": 840},
            {"trace_id": "trc-2", "status": "ok", "duration_ms": 220},
        ]
        with patch.object(self.server.observability, "fetch_traces", return_value=traces) as traces_mock:
            out = self.server.traces_fetch_recent("payments-api", "start", "end", limit=25)

        traces_mock.assert_called_once_with("payments-api", "start", "end", 25)
        self.assertEqual(out["correlation_id"], "corr-1")
        self.assertEqual(out["traces"], traces)

    def test_traces_fetch_recent_handles_resilience_error(self) -> None:
        err = self.server.ResilienceError(
            provider="xray",
            operation="fetch_traces",
            kind="adapter_call_failed",
            message="xray.fetch_traces failed after 1 attempt(s)",
            attempts=1,
            retriable=True,
            cause=RuntimeError("missing permission"),
        )
        with patch.object(self.server.observability, "fetch_traces", side_effect=err):
            out = self.server.traces_fetch_recent("payments-api", "start", "end", limit=10)

        self.assertEqual(out["correlation_id"], "corr-1")
        self.assertEqual(out["traces"], [])
        self.assertIn("error", out)
        self.assertEqual(out["error"]["operation"], "fetch_traces")
        self.assertEqual(out["error"]["provider"], "xray")

    def test_runbooks_search(self) -> None:
        hits = [{"title": "restart payment workers", "score": 0.88}]
        with patch.object(self.server, "search_local_runbooks", return_value=hits) as search_mock:
            out = self.server.runbooks_search("payment timeout", limit=3)

        search_mock.assert_called_once_with(self.tmpdir.name, "payment timeout", 3)
        self.assertEqual(out, {"correlation_id": "corr-1", "results": hits})

    def test_airflow_trigger_incident_dag(self) -> None:
        dag_run = {"dag_run_id": "manual__1", "state": "queued"}
        with patch.object(self.server.airflow, "trigger_dag", return_value=dag_run) as trigger_mock:
            out = self.server.airflow_trigger_incident_dag("INC-55", "payments-api")

        trigger_mock.assert_called_once_with(
            "incident_evidence_v1",
            {"incident_id": "INC-55", "service": "payments-api"},
        )
        self.assertEqual(out["correlation_id"], "corr-1")
        self.assertEqual(out["dag_id"], "incident_evidence_v1")
        self.assertEqual(out["dag_run"], dag_run)

    def test_airflow_get_incident_artifact_not_found(self) -> None:
        out = self.server.airflow_get_incident_artifact("INC-404")
        self.assertEqual(out["correlation_id"], "corr-1")
        self.assertFalse(out["found"])
        self.assertTrue(out["path"].endswith("INC-404.json"))

    def test_airflow_get_incident_artifact_found(self) -> None:
        artifact_path = Path(self.tmpdir.name) / "INC-200.json"
        artifact_path.write_text(json.dumps({"ok": True, "value": 7}), encoding="utf-8")

        out = self.server.airflow_get_incident_artifact("INC-200")
        self.assertEqual(out["correlation_id"], "corr-1")
        self.assertTrue(out["found"])
        self.assertEqual(out["artifact"], {"ok": True, "value": 7})
        self.assertEqual(out["path"], str(artifact_path))

    def test_evidence_get_bundle_fs(self) -> None:
        with patch.object(
            self.server,
            "load_bundle",
            return_value={"found": True, "path": "/tmp/INC-9.json", "bundle": _bundle("INC-9")},
        ) as load_mock:
            out = self.server.evidence_get_bundle("INC-9")

        load_mock.assert_called_once_with(self.tmpdir.name, "INC-9")
        self.assertEqual(out["correlation_id"], "corr-1")
        self.assertTrue(out["found"])
        self.assertEqual(out["bundle"]["incident_id"], "INC-9")

    def test_evidence_get_bundle_s3_found(self) -> None:
        with patch.dict(
            os.environ,
            {
                "EVIDENCE_BACKEND": "s3",
                "ARTIFACT_STORE": "s3",
                "S3_ENDPOINT_URL": "http://localhost:9000",
                "S3_BUCKET": "triage-artifacts",
                "AWS_ACCESS_KEY_ID": "key",
                "AWS_SECRET_ACCESS_KEY": "secret",
            },
            clear=False,
        ):
            server = self._reload_and_attach()
            with patch.object(
                server,
                "read_evidence_bundle",
                return_value={
                    "found": True,
                    "uri": "s3://triage-artifacts/evidence/v1/INC-88.json",
                    "raw": _bundle("INC-88"),
                },
            ) as read_mock:
                out = server.evidence_get_bundle("INC-88")

        read_mock.assert_called_once_with("INC-88")
        self.assertEqual(out["correlation_id"], "corr-1")
        self.assertTrue(out["found"])
        self.assertEqual(out["bundle"]["incident_id"], "INC-88")
        self.assertEqual(out["uri"], "s3://triage-artifacts/evidence/v1/INC-88.json")

    def test_evidence_get_bundle_s3_not_found(self) -> None:
        with patch.dict(
            os.environ,
            {
                "EVIDENCE_BACKEND": "s3",
                "ARTIFACT_STORE": "s3",
                "S3_ENDPOINT_URL": "http://localhost:9000",
                "S3_BUCKET": "triage-artifacts",
                "AWS_ACCESS_KEY_ID": "key",
                "AWS_SECRET_ACCESS_KEY": "secret",
            },
            clear=False,
        ):
            server = self._reload_and_attach()
            with patch.object(server, "read_evidence_bundle", return_value={"found": False}) as read_mock:
                out = server.evidence_get_bundle("INC-404")

        read_mock.assert_called_once_with("INC-404")
        self.assertEqual(out["correlation_id"], "corr-1")
        self.assertFalse(out["found"])

    def test_evidence_wait_for_bundle(self) -> None:
        waited = {"found": True, "bundle": _bundle("INC-WAIT"), "attempts": 2, "waited_seconds": 1}
        with patch.object(self.server, "wait_for", return_value=waited) as wait_mock:
            out = self.server.evidence_wait_for_bundle("INC-WAIT", timeout_seconds=90, poll_seconds=3)

        wait_mock.assert_called_once()
        self.assertEqual(wait_mock.call_args.args[1], "INC-WAIT")
        self.assertEqual(wait_mock.call_args.kwargs["timeout_seconds"], 90)
        self.assertEqual(wait_mock.call_args.kwargs["poll_seconds"], 3)
        self.assertEqual(out["correlation_id"], "corr-1")
        self.assertTrue(out["found"])

    def test_incident_triage_summary_found(self) -> None:
        with patch.object(
            self.server,
            "evidence_get_bundle",
            return_value={"found": True, "bundle": _bundle("INC-SUM"), "uri": "s3://bucket/INC-SUM.json"},
        ) as get_bundle_mock, patch.object(
            self.server,
            "build_triage_summary",
            return_value={"headline": "summary headline"},
        ) as summary_mock:
            out = self.server.incident_triage_summary("INC-SUM")

        get_bundle_mock.assert_called_once_with("INC-SUM")
        summary_mock.assert_called_once_with(_bundle("INC-SUM"), evidence_uri="s3://bucket/INC-SUM.json")
        self.assertEqual(out, {"headline": "summary headline", "correlation_id": "corr-1"})

    def test_incident_triage_summary_not_found(self) -> None:
        with patch.object(self.server, "evidence_get_bundle", return_value={"found": False}) as get_bundle_mock:
            out = self.server.incident_triage_summary("INC-MISSING")

        get_bundle_mock.assert_called_once_with("INC-MISSING")
        self.assertFalse(out["found"])
        self.assertEqual(out["correlation_id"], "corr-1")

    def test_jira_draft_ticket_uses_env_defaults(self) -> None:
        with patch.object(
            self.server,
            "evidence_get_bundle",
            return_value={"found": True, "bundle": _bundle("INC-JD"), "uri": "s3://bucket/INC-JD.json"},
        ) as get_bundle_mock, patch.object(
            self.server,
            "build_jira_draft",
            return_value={"title": "t", "project_key": "SCRUM", "issue_type": "Task"},
        ) as draft_mock:
            out = self.server.jira_draft_ticket("INC-JD")

        get_bundle_mock.assert_called_once_with("INC-JD")
        draft_mock.assert_called_once_with(
            _bundle("INC-JD"),
            project_key="SCRUM",
            issue_type="Task",
            evidence_uri="s3://bucket/INC-JD.json",
        )
        self.assertEqual(out["project_key"], "SCRUM")
        self.assertEqual(out["issue_type"], "Task")
        self.assertEqual(out["correlation_id"], "corr-1")

    def test_jira_draft_ticket_not_found(self) -> None:
        with patch.object(self.server, "evidence_get_bundle", return_value={"found": False}) as get_bundle_mock:
            out = self.server.jira_draft_ticket("INC-NONE")

        get_bundle_mock.assert_called_once_with("INC-NONE")
        self.assertFalse(out["found"])
        self.assertEqual(out["correlation_id"], "corr-1")

    def test_jira_create_ticket_dry_run(self) -> None:
        draft = {
            "title": "Incident title",
            "priority": "P2",
            "labels": ["incident"],
            "description_md": "text",
            "evidence_uri": "s3://bucket/INC-DRY.json",
        }
        with patch.object(self.server, "require_allowed") as allowed_mock, patch.object(
            self.server, "evidence_get_bundle", return_value={"found": True, "bundle": _bundle("INC-DRY")}
        ), patch.object(
            self.server, "build_jira_draft", return_value=draft
        ) as draft_mock, patch.object(
            self.server, "enforce"
        ) as enforce_mock, patch.object(
            self.server, "get_provider"
        ) as provider_mock:
            out = self.server.jira_create_ticket("INC-DRY")

        allowed_mock.assert_called_once_with("jira.create_ticket")
        draft_mock.assert_called_once()
        enforce_mock.assert_called_once()
        provider_mock.assert_not_called()
        self.assertEqual(out["correlation_id"], "corr-1")
        self.assertFalse(out["created"])
        self.assertTrue(out["dry_run"])
        self.assertEqual(out["draft"], draft)

    def test_jira_create_ticket_success(self) -> None:
        draft = {
            "title": "Incident title",
            "priority": "P1",
            "labels": ["incident"],
            "description_md": "details",
            "evidence_uri": "s3://bucket/INC-OK.json",
        }
        provider = Mock()
        store = Mock()
        store.get.return_value = None
        provider.create_issue.return_value = {
            "created": True,
            "provider": "cloud",
            "issue_key": "SCRUM-123",
            "browse_url": "https://jira/browse/SCRUM-123",
        }
        with patch.object(self.server, "require_allowed"), patch.object(
            self.server, "evidence_get_bundle", return_value={"found": True, "bundle": _bundle("INC-OK")}
        ), patch.object(self.server, "build_jira_draft", return_value=draft), patch.object(
            self.server, "enforce"
        ), patch.object(
            self.server, "get_provider", return_value=provider
        ), patch.object(
            self.server, "ticket_idempotency_store", store
        ):
            out = self.server.jira_create_ticket(
                "INC-OK",
                dry_run=False,
                reason="Track incident timeline and coordinate responders",
                confirm_token="test-confirm-token",
                idempotency_key="INC-OK-SCRUM-1",
            )

        provider.create_issue.assert_called_once()
        payload = provider.create_issue.call_args.args[0]
        self.assertEqual(payload["project_key"], "SCRUM")
        self.assertEqual(payload["issue_type"], "Task")
        self.assertEqual(payload["idempotency_key"], "INC-OK-SCRUM-1")
        self.assertEqual(out["correlation_id"], "corr-1")
        self.assertTrue(out["created"])
        self.assertFalse(out["dry_run"])
        self.assertEqual(out["issue_key"], "SCRUM-123")
        store.get.assert_called_once_with("INC-OK-SCRUM-1")
        store.set.assert_called_once_with(
            "INC-OK-SCRUM-1",
            {
                "created": True,
                "provider": "cloud",
                "issue_key": "SCRUM-123",
                "browse_url": "https://jira/browse/SCRUM-123",
            },
        )

    def test_jira_create_ticket_idempotent_replay(self) -> None:
        store = Mock()
        store.get.return_value = {
            "created": True,
            "provider": "cloud",
            "issue_key": "SCRUM-999",
            "browse_url": "https://jira/browse/SCRUM-999",
        }
        with patch.object(self.server, "require_allowed"), patch.object(
            self.server, "ticket_idempotency_store", store
        ), patch.object(
            self.server, "get_provider"
        ) as provider_mock, patch.object(
            self.server, "evidence_get_bundle"
        ) as evidence_mock:
            out = self.server.jira_create_ticket(
                "INC-RETRY",
                dry_run=False,
                reason="retrying after timeout",
                confirm_token="test-confirm-token",
                idempotency_key="INC-RETRY-SCRUM-1",
            )

        provider_mock.assert_not_called()
        evidence_mock.assert_not_called()
        store.get.assert_called_once_with("INC-RETRY-SCRUM-1")
        store.set.assert_not_called()
        self.assertEqual(out["correlation_id"], "corr-1")
        self.assertTrue(out["created"])
        self.assertFalse(out["dry_run"])
        self.assertTrue(out["idempotent_replay"])
        self.assertEqual(out["issue_key"], "SCRUM-999")

    def test_jira_create_ticket_safe_action_denied(self) -> None:
        draft = {
            "title": "Incident title",
            "priority": "P1",
            "labels": ["incident"],
            "description_md": "details",
            "evidence_uri": "s3://bucket/INC-DENY.json",
        }
        with patch.object(self.server, "require_allowed"), patch.object(
            self.server, "evidence_get_bundle", return_value={"found": True, "bundle": _bundle("INC-DENY")}
        ), patch.object(self.server, "build_jira_draft", return_value=draft), patch.object(
            self.server,
            "enforce",
            side_effect=self.server.SafeActionError("Invalid or missing confirm_token for non-dry-run action."),
        ):
            out = self.server.jira_create_ticket("INC-DENY", dry_run=False, reason="valid reason")

        self.assertEqual(out["correlation_id"], "corr-1")
        self.assertFalse(out["created"])
        self.assertFalse(out["dry_run"])
        self.assertIn("confirm_token", out["error"])
        self.assertEqual(out["draft"], draft)

    def test_jira_create_ticket_draft_error(self) -> None:
        with patch.object(self.server, "require_allowed"), patch.object(
            self.server, "evidence_get_bundle", return_value={"found": True, "bundle": _bundle("INC-BAD-DRAFT")}
        ), patch.object(
            self.server, "build_jira_draft", side_effect=ValueError("bad draft")
        ):
            out = self.server.jira_create_ticket("INC-BAD-DRAFT", dry_run=False, reason="valid reason")

        self.assertFalse(out["created"])
        self.assertEqual(out["error"], "draft_failed: bad draft")

    def test_jira_create_ticket_evidence_missing(self) -> None:
        with patch.object(self.server, "require_allowed"), patch.object(
            self.server, "evidence_get_bundle", return_value={"found": False}
        ):
            out = self.server.jira_create_ticket("INC-MISS")

        self.assertFalse(out["found"])
        self.assertEqual(out["correlation_id"], "corr-1")

    def test_jira_create_ticket_rbac_denied_raises(self) -> None:
        with patch.object(
            self.server, "require_allowed", side_effect=RuntimeError("Role 'viewer' is not allowed to call 'jira.create_ticket'.")
        ):
            with self.assertRaises(RuntimeError):
                self.server.jira_create_ticket("INC-RBAC")

    def test_jira_list_projects_success(self) -> None:
        provider = Mock()
        provider.list_projects.return_value = [
            {"id": "10000", "key": "SCRUM", "name": "Scrum Project"},
            {"id": "10001", "key": "INC", "name": "Incident Management"},
        ]
        with patch.object(self.server, "provider_name", return_value="cloud"), patch.object(
            self.server, "get_provider", return_value=provider
        ):
            out = self.server.jira_list_projects()

        provider.list_projects.assert_called_once()
        self.assertEqual(out["correlation_id"], "corr-1")
        self.assertTrue(out["ok"])
        self.assertEqual(out["provider"], "cloud")
        self.assertEqual(len(out["projects"]), 2)
        self.assertEqual(out["projects"][0]["key"], "SCRUM")

    def test_jira_list_projects_error(self) -> None:
        with patch.object(self.server, "provider_name", return_value="cloud"), patch.object(
            self.server, "get_provider", side_effect=RuntimeError("jira unavailable")
        ):
            out = self.server.jira_list_projects()

        self.assertEqual(out["correlation_id"], "corr-1")
        self.assertFalse(out["ok"])
        self.assertEqual(out["projects"], [])
        self.assertEqual(out["error"], "jira unavailable")

    def test_jira_list_issue_types_defaults_project_key(self) -> None:
        provider = Mock()
        provider.list_issue_types.return_value = [
            {"id": "1", "name": "Task", "subtask": False},
            {"id": "2", "name": "Bug", "subtask": False},
        ]
        with patch.object(self.server, "provider_name", return_value="cloud"), patch.object(
            self.server, "get_provider", return_value=provider
        ):
            out = self.server.jira_list_issue_types()

        provider.list_issue_types.assert_called_once_with("SCRUM")
        self.assertEqual(out["correlation_id"], "corr-1")
        self.assertTrue(out["ok"])
        self.assertEqual(out["project_key"], "SCRUM")
        self.assertEqual(out["issue_types"][0]["name"], "Task")

    def test_jira_list_issue_types_override_project_key(self) -> None:
        provider = Mock()
        provider.list_issue_types.return_value = [{"id": "1", "name": "Task", "subtask": False}]
        with patch.object(self.server, "provider_name", return_value="cloud"), patch.object(
            self.server, "get_provider", return_value=provider
        ):
            out = self.server.jira_list_issue_types("PAY")

        provider.list_issue_types.assert_called_once_with("PAY")
        self.assertEqual(out["project_key"], "PAY")
        self.assertTrue(out["ok"])

    def test_jira_list_issue_types_error(self) -> None:
        with patch.object(self.server, "provider_name", return_value="cloud"), patch.object(
            self.server, "get_provider", side_effect=RuntimeError("invalid project")
        ):
            out = self.server.jira_list_issue_types("NOPE")

        self.assertEqual(out["correlation_id"], "corr-1")
        self.assertFalse(out["ok"])
        self.assertEqual(out["project_key"], "NOPE")
        self.assertEqual(out["issue_types"], [])
        self.assertEqual(out["error"], "invalid project")

    def test_jira_validate_credentials_not_cloud(self) -> None:
        with patch.object(self.server, "provider_name", return_value="mock"):
            out = self.server.jira_validate_credentials()

        self.assertEqual(out["correlation_id"], "corr-1")
        self.assertFalse(out["ok"])
        self.assertIn("Set JIRA_PROVIDER=cloud", out["error"])

    def test_jira_validate_credentials_cloud_ok(self) -> None:
        provider = Mock()
        provider.validate.return_value = {"accountId": "abc123", "displayName": "Felix"}
        with patch.object(self.server, "provider_name", return_value="cloud"), patch.object(
            self.server, "get_provider", return_value=provider
        ):
            out = self.server.jira_validate_credentials()

        provider.validate.assert_called_once()
        self.assertEqual(out["correlation_id"], "corr-1")
        self.assertTrue(out["ok"])
        self.assertEqual(out["displayName"], "Felix")

    def test_jira_validate_credentials_servicenow_ok(self) -> None:
        provider = Mock()
        provider.validate.return_value = {
            "accountId": "user-1",
            "displayName": "Incident Bot",
            "provider": "servicenow",
        }
        with patch.object(self.server, "provider_name", return_value="servicenow"), patch.object(
            self.server, "get_provider", return_value=provider
        ):
            out = self.server.jira_validate_credentials()

        provider.validate.assert_called_once()
        self.assertEqual(out["correlation_id"], "corr-1")
        self.assertTrue(out["ok"])
        self.assertEqual(out["provider"], "servicenow")

    def test_jira_validate_credentials_cloud_error(self) -> None:
        with patch.object(self.server, "provider_name", return_value="cloud"), patch.object(
            self.server, "get_provider", side_effect=RuntimeError("auth failed")
        ):
            out = self.server.jira_validate_credentials()

        self.assertEqual(out["correlation_id"], "corr-1")
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"], "auth failed")


if __name__ == "__main__":
    unittest.main()
