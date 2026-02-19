from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch
import os


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


class _FakeServer:
    def __init__(self, result=None, error: Exception | None = None) -> None:
        self._result = result or {"status": "ok"}
        self._error = error
        self.calls = []

    def incident_triage_run(self, **kwargs):
        self.calls.append(kwargs)
        if self._error:
            raise self._error
        return self._result


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
            )

        self.assertIn("result", state)
        self.assertEqual(state["result"]["summary"]["status"], "triage_started")
        self.assertNotIn("error", state)
        self.assertEqual(len(fake_server.calls), 1)
        self.assertEqual(fake_server.calls[0]["incident_id"], "INC-123")
        self.assertEqual(fake_server.calls[0]["service"], "payments-api")
        self.assertTrue(fake_server.calls[0]["include_ticket"])
        self.assertEqual(fake_server.calls[0]["project_key"], "SCRUM")
        self.assertTrue(fake_server.calls[0]["notify_slack"])
        self.assertEqual(fake_server.calls[0]["slack_channel"], "#incident-triage")
        self.assertFalse(fake_server.calls[0]["slack_dry_run"])

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

        with patch.object(agent, "run_agent", return_value={"result": {"status": "ok"}}) as run_mock, patch(
            "builtins.print"
        ) as print_mock:
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
        )
        print_mock.assert_called_once()

    def test_main_returns_nonzero_on_error(self) -> None:
        from incident_triage_mcp.agents import langgraph_agent as agent

        with patch.object(agent, "run_agent", return_value={"error": "failed"}), patch("builtins.print"):
            code = agent.main(["--incident-id", "INC-55", "--service", "payments-api"])

        self.assertEqual(code, 1)

    def test_main_sets_fs_artifact_env_defaults(self) -> None:
        from incident_triage_mcp.agents import langgraph_agent as agent

        with patch.dict(os.environ, {}, clear=True), patch.object(
            agent, "run_agent", return_value={"result": {"status": "ok"}}
        ), patch("builtins.print"):
            code = agent.main(["--incident-id", "INC-66", "--service", "payments-api"])

        self.assertEqual(code, 0)
        self.assertEqual(os.environ["ARTIFACT_STORE"], "fs")
        self.assertEqual(os.environ["AIRFLOW_ARTIFACT_DIR"], "./airflow/artifacts")


if __name__ == "__main__":
    unittest.main()
