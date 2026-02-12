from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from airflow import DAG
from airflow.decorators import task

ARTIFACT_DIR = os.getenv("INCIDENT_ARTIFACT_DIR", "/opt/airflow/dags/artifacts")

with DAG(
    dag_id="incident_evidence_v1",
    start_date=datetime(2024, 1, 1),
    schedule=None,
    catchup=False,
    tags=["incident", "triage"],
) as dag:

    @task
    def build_evidence(incident_id: str, service: str) -> str:
        """
        Creates a small JSON artifact that simulates an evidence bundle.
        In real life this would query logs/metrics/traces and assemble a report.
        """
        os.makedirs(ARTIFACT_DIR, exist_ok=True)

        payload = {
            "incident_id": incident_id,
            "service": service,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "signals": {
                "error_rate": 0.12,
                "latency_p95_ms": 840,
                "top_endpoint": "POST /checkout",
            },
            "hypotheses": [
                "Recent deploy regression",
                "Downstream dependency timeout",
                "DB connection pool saturation",
            ],
            "recommended_next_queries": [
                "search logs for trace_id spikes",
                "check deploys in last 30 minutes",
                "verify dependency health",
            ],
        }

        path = os.path.join(ARTIFACT_DIR, f"{incident_id}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        return path

    # Default example params (Airflow will override at trigger time)
    build_evidence(incident_id="INC-LOCAL-001", service="payments-api")