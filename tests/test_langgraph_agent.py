from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


class _FakeServer:
    def __init__(
        self,
        result=None,
        error: Exception | None = None,
        ticket_result=None,
        ticket_error: Exception | None = None,
    ) -> None:
        self._result = result or {"status": "ok"}
        self._error = error
        self._ticket_result = ticket_result or {"created": True, "issue_key": "SCRUM-123"}
        self._ticket_error = ticket_error
        self.calls = []
        self.ticket_calls = []

    def incident_triage_run(self, **kwargs):
        self.calls.append(kwargs)
        if self._error:
            raise self._error
        return self._result

    def jira_create_ticket(self, **kwargs):
        self.ticket_calls.append(kwargs)
        if self._ticket_error:
            raise self._ticket_error
        return self._ticket_result


class TestLangGraphAgent(unittest.TestCase):
    def test_run_agent_success(self) -> None:
        from incident_triage_mcp.agents import langgraph_agent as agent

        fake_server = _FakeServer(result={"summary": {"status": "triage_started"}})
        with patch.object(agent, "_load_server_module", return_value=fake_server):
            state = agent.run_agent(
                incident_id="INC-123",
                service="payments-api",
                include_ticket=True,
                project_key="SCRUM",
                notify_slack=True,
                slack_channel="#incident-triage",
                slack_dry_run=False,
                create_ticket_live=False,
                ticket_reason=None,
                confirm_token=None,
                idempotency_key=None,
            )

        self.assertIn("result", state)
        self.assertEqual(state["result"]["summary"]["status"], "triage_started")
        self.assertNotIn("error", state)
        self.assertEqual(len(fake_server.calls), 1)
        self.assertEqual(fake_server.calls[0]["incident_id"], "INC-123")
        self.assertEqual(fake_server.calls[0]["service"], "payments-api")
        self.assertEqual(fake_server.ticket_calls, [])

    def test_run_agent_with_live_ticket(self) -> None:
        from incident_triage_mcp.agents import langgraph_agent as agent

        fake_server = _FakeServer(
            result={"summary": {"status": "triage_started"}},
            ticket_result={"created": True, "issue_key": "SCRUM-777"},
        )
        with patch.object(agent, "_load_server_module", return_value=fake_server):
            state = agent.run_agent(
                incident_id="INC-700",
                service="payments-api",
                project_key="SCRUM",
                create_ticket_live=True,
                ticket_reason="Create live ticket for incident command workflow",
                confirm_token="test-confirm-token",
            )

        self.assertNotIn("error", state)
        self.assertIn("result", state)
        self.assertEqual(state["result"]["live_ticket"]["issue_key"], "SCRUM-777")
        self.assertEqual(len(fake_server.ticket_calls), 1)
        self.assertEqual(fake_server.ticket_calls[0]["idempotency_key"], "INC-700-SCRUM-live")

    def test_run_agent_live_ticket_failure(self) -> None:
        from incident_triage_mcp.agents import langgraph_agent as agent

        fake_server = _FakeServer(ticket_error=RuntimeError("ticket create failed"))
        with patch.object(agent, "_load_server_module", return_value=fake_server):
            state = agent.run_agent(
                incident_id="INC-701",
                service="payments-api",
                create_ticket_live=True,
                ticket_reason="create",
                confirm_token="token",
            )

        self.assertIn("error", state)
        self.assertIn("ticket create failed", state["error"])

    def test_run_agent_failure(self) -> None:
        from incident_triage_mcp.agents import langgraph_agent as agent

        fake_server = _FakeServer(error=RuntimeError("boom"))
        with patch.object(agent, "_load_server_module", return_value=fake_server):
            state = agent.run_agent(incident_id="INC-404", service="orders-api")

        self.assertNotIn("result", state)
        self.assertIn("error", state)
        self.assertIn("boom", state["error"])

    def test_main_slack_live_flag_sets_dry_run_false(self) -> None:
        from incident_triage_mcp.agents import langgraph_agent as agent

        with patch.dict(os.environ, {}, clear=True), patch.object(
            agent, "run_agent", return_value={"result": {"status": "ok"}}
        ) as run_mock, patch("builtins.print") as print_mock:
            code = agent.main(
                [
                    "--incident-id",
                    "INC-55",
                    "--service",
                    "payments-api",
                    "--notify-slack",
                    "--slack-channel",
                    "#incident-triage",
                    "--slack-live",
                    "--compact",
                ]
            )

        self.assertEqual(code, 0)
        run_mock.assert_called_once_with(
            incident_id="INC-55",
            service="payments-api",
            include_ticket=False,
            project_key=None,
            notify_slack=True,
            slack_channel="#incident-triage",
            slack_dry_run=False,
            create_ticket_live=False,
            ticket_reason=None,
            confirm_token=None,
            idempotency_key=None,
        )
        print_mock.assert_called_once()

    def test_main_returns_nonzero_on_error(self) -> None:
        from incident_triage_mcp.agents import langgraph_agent as agent

        with patch.dict(os.environ, {}, clear=True), patch.object(
            agent, "run_agent", return_value={"error": "failed"}
        ), patch("builtins.print"):
            code = agent.main(["--incident-id", "INC-55", "--service", "payments-api"])

        self.assertEqual(code, 1)

    def test_main_live_ticket_requires_reason(self) -> None:
        from incident_triage_mcp.agents import langgraph_agent as agent

        with patch.dict(os.environ, {}, clear=True), self.assertRaises(SystemExit) as ctx:
            agent.main(
                [
                    "--incident-id",
                    "INC-88",
                    "--service",
                    "payments-api",
                    "--create-ticket-live",
                    "--confirm-token",
                    "token",
                ]
            )

        self.assertEqual(ctx.exception.code, 2)

    def test_main_live_ticket_requires_confirm_token(self) -> None:
        from incident_triage_mcp.agents import langgraph_agent as agent

        with patch.dict(os.environ, {}, clear=True), self.assertRaises(SystemExit) as ctx:
            agent.main(
                [
                    "--incident-id",
                    "INC-89",
                    "--service",
                    "payments-api",
                    "--create-ticket-live",
                    "--ticket-reason",
                    "create ticket",
                ]
            )

        self.assertEqual(ctx.exception.code, 2)

    def test_main_live_ticket_uses_confirm_token_env(self) -> None:
        from incident_triage_mcp.agents import langgraph_agent as agent

        with patch.dict(os.environ, {"CONFIRM_TOKEN": "env-token"}, clear=True), patch.object(
            agent, "run_agent", return_value={"result": {"status": "ok"}}
        ) as run_mock, patch("builtins.print"):
            code = agent.main(
                [
                    "--incident-id",
                    "INC-90",
                    "--service",
                    "payments-api",
                    "--create-ticket-live",
                    "--ticket-reason",
                    "Create live ticket after triage",
                ]
            )

        self.assertEqual(code, 0)
        run_mock.assert_called_once_with(
            incident_id="INC-90",
            service="payments-api",
            include_ticket=False,
            project_key=None,
            notify_slack=False,
            slack_channel=None,
            slack_dry_run=True,
            create_ticket_live=True,
            ticket_reason="Create live ticket after triage",
            confirm_token="env-token",
            idempotency_key=None,
        )

    def test_main_sets_fs_artifact_env_defaults(self) -> None:
        from incident_triage_mcp.agents import langgraph_agent as agent

        with patch.dict(os.environ, {}, clear=True), patch.object(
            agent, "run_agent", return_value={"result": {"status": "ok"}}
        ), patch("builtins.print"):
            code = agent.main(["--incident-id", "INC-66", "--service", "payments-api"])
            self.assertEqual(os.environ["EVIDENCE_BACKEND"], "fs")
            self.assertEqual(os.environ["ARTIFACT_STORE"], "fs")
            self.assertEqual(os.environ["EVIDENCE_DIR"], "./airflow/artifacts")
            self.assertEqual(os.environ["AIRFLOW_ARTIFACT_DIR"], "./airflow/artifacts")

        self.assertEqual(code, 0)

    def test_main_allows_s3_artifact_store(self) -> None:
        from incident_triage_mcp.agents import langgraph_agent as agent

        with patch.dict(os.environ, {}, clear=True), patch.object(
            agent, "run_agent", return_value={"result": {"status": "ok"}}
        ), patch("builtins.print"):
            code = agent.main(
                [
                    "--incident-id",
                    "INC-67",
                    "--service",
                    "payments-api",
                    "--artifact-store",
                    "s3",
                ]
            )
            self.assertEqual(os.environ["EVIDENCE_BACKEND"], "s3")
            self.assertEqual(os.environ["ARTIFACT_STORE"], "s3")
            self.assertNotIn("EVIDENCE_DIR", os.environ)
            self.assertNotIn("AIRFLOW_ARTIFACT_DIR", os.environ)

        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()

