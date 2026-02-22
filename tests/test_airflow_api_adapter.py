from __future__ import annotations

import os
import unittest
from unittest.mock import Mock, patch

from incident_triage_mcp.adapters.airflow_api import AirflowAPI


def _response(status_code: int, payload: dict | None = None) -> Mock:
    resp = Mock()
    resp.status_code = status_code
    resp.json.return_value = payload or {}
    if status_code >= 400:
        resp.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    else:
        resp.raise_for_status.return_value = None
    return resp


class TestAirflowAPIAdapter(unittest.TestCase):
    def setUp(self) -> None:
        self.base_env = {
            "AIRFLOW_USERNAME": "admin",
            "AIRFLOW_PASSWORD": "admin",
        }

    @patch.dict(os.environ, {}, clear=True)
    def test_missing_credentials_rejected(self) -> None:
        with self.assertRaises(RuntimeError):
            AirflowAPI("http://airflow")

    @patch("incident_triage_mcp.adapters.airflow_api.requests.request")
    def test_trigger_dag_v1_uses_basic_auth(self, request_mock: Mock) -> None:
        request_mock.return_value = _response(200, {"dag_run_id": "manual__1"})
        with patch.dict(
            os.environ,
            {**self.base_env, "AIRFLOW_API_VERSION": "v1"},
            clear=True,
        ):
            client = AirflowAPI("http://airflow")
            result = client.trigger_dag("incident_evidence_v1", {"incident_id": "INC-123"})

        self.assertEqual(result["dag_run_id"], "manual__1")
        request_mock.assert_called_once()
        args, kwargs = request_mock.call_args
        self.assertEqual(args[0], "POST")
        self.assertEqual(args[1], "http://airflow/api/v1/dags/incident_evidence_v1/dagRuns")
        self.assertEqual(kwargs["json"], {"conf": {"incident_id": "INC-123"}})
        self.assertEqual(kwargs["auth"], ("admin", "admin"))
        self.assertNotIn("headers", kwargs)

    @patch("incident_triage_mcp.adapters.airflow_api.requests.request")
    @patch("incident_triage_mcp.adapters.airflow_api.requests.post")
    def test_trigger_dag_v2_uses_token_and_logical_date(
        self, post_mock: Mock, request_mock: Mock
    ) -> None:
        post_mock.return_value = _response(200, {"access_token": "jwt-token"})
        request_mock.return_value = _response(200, {"dag_run_id": "manual__2"})
        with patch.dict(
            os.environ,
            {**self.base_env, "AIRFLOW_API_VERSION": "v2", "AIRFLOW_AUTH_MODE": "token"},
            clear=True,
        ):
            client = AirflowAPI("http://airflow")
            result = client.trigger_dag("incident_evidence_v1", {"incident_id": "INC-123"})

        self.assertEqual(result["dag_run_id"], "manual__2")
        post_mock.assert_called_once()
        post_args, post_kwargs = post_mock.call_args
        self.assertEqual(post_args[0], "http://airflow/auth/token")
        self.assertEqual(
            post_kwargs["json"],
            {"username": "admin", "password": "admin"},
        )

        request_mock.assert_called_once()
        args, kwargs = request_mock.call_args
        self.assertEqual(args[0], "POST")
        self.assertEqual(args[1], "http://airflow/api/v2/dags/incident_evidence_v1/dagRuns")
        self.assertEqual(
            kwargs["json"],
            {"conf": {"incident_id": "INC-123"}, "logical_date": None},
        )
        self.assertEqual(kwargs["headers"], {"Authorization": "Bearer jwt-token"})
        self.assertNotIn("auth", kwargs)

    @patch("incident_triage_mcp.adapters.airflow_api.requests.request")
    @patch("incident_triage_mcp.adapters.airflow_api.requests.post")
    def test_get_dag_run_v2_uses_bearer_auth(self, post_mock: Mock, request_mock: Mock) -> None:
        post_mock.return_value = _response(200, {"access_token": "jwt-token"})
        request_mock.return_value = _response(200, {"dag_run_id": "manual__2", "state": "success"})
        with patch.dict(
            os.environ,
            {**self.base_env, "AIRFLOW_API_VERSION": "v2"},
            clear=True,
        ):
            client = AirflowAPI("http://airflow")
            result = client.get_dag_run("incident_evidence_v1", "manual__2")

        self.assertEqual(result["state"], "success")
        args, kwargs = request_mock.call_args
        self.assertEqual(args[0], "GET")
        self.assertEqual(
            args[1],
            "http://airflow/api/v2/dags/incident_evidence_v1/dagRuns/manual__2",
        )
        self.assertEqual(kwargs["headers"], {"Authorization": "Bearer jwt-token"})


if __name__ == "__main__":
    unittest.main()
