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
