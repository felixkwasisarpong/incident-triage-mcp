from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from incident_triage_mcp.tools.incidents import triage_incident_run


class TestTriageIncidentRun(unittest.TestCase):
    def test_waits_for_bundle_after_initial_artifact_miss(self) -> None:
        alerts_fetch_active = Mock(return_value={"alerts": []})
        airflow_trigger_incident_dag = Mock(return_value={"dag_run_id": "manual__1", "state": "queued"})
        airflow_get_incident_artifact = Mock(return_value={"found": False, "path": "/tmp/INC-1.json"})
        evidence_wait_for_bundle = Mock(
            return_value={"found": True, "path": "/tmp/INC-1.json", "bundle": {"incident_id": "INC-1"}}
        )

        out = triage_incident_run(
            incident_id="INC-1",
            service="payments-api",
            alerts_fetch_active=alerts_fetch_active,
            airflow_trigger_incident_dag=airflow_trigger_incident_dag,
            airflow_get_incident_artifact=airflow_get_incident_artifact,
            evidence_wait_for_bundle=evidence_wait_for_bundle,
        )

        evidence_wait_for_bundle.assert_called_once_with(
            incident_id="INC-1",
            timeout_seconds=30,
            poll_seconds=2,
        )
        self.assertTrue(out["artifact"]["found"])
        self.assertTrue(out["summary"]["artifact_found"])

    def test_skips_wait_when_airflow_trigger_is_disabled(self) -> None:
        alerts_fetch_active = Mock(return_value={"alerts": []})
        airflow_trigger_incident_dag = Mock(
            return_value={"enabled": False, "dag_run": None, "error": "airflow_disabled: missing config"}
        )
        airflow_get_incident_artifact = Mock(return_value={"found": False, "path": "/tmp/INC-2.json"})
        evidence_wait_for_bundle = Mock()

        out = triage_incident_run(
            incident_id="INC-2",
            service="payments-api",
            alerts_fetch_active=alerts_fetch_active,
            airflow_trigger_incident_dag=airflow_trigger_incident_dag,
            airflow_get_incident_artifact=airflow_get_incident_artifact,
            evidence_wait_for_bundle=evidence_wait_for_bundle,
        )

        evidence_wait_for_bundle.assert_not_called()
        self.assertFalse(out["artifact"]["found"])
        self.assertFalse(out["summary"]["artifact_found"])


if __name__ == "__main__":
    unittest.main()
