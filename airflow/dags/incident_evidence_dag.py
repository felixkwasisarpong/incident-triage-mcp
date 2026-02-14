from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from incident_evidence_v1 import search_runbooks
from airflow import DAG
from airflow.decorators import task
from airflow.operators.python import get_current_context
import boto3


ARTIFACT_DIR = os.getenv("INCIDENT_ARTIFACT_DIR", "/opt/airflow/dags/artifacts")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


with DAG(
    dag_id="incident_evidence_v1",
    start_date=datetime(2024, 1, 1),
    schedule=None,
    catchup=False,
    tags=["incident", "triage"],
) as dag:

    @task
    def build_bundle(window_minutes: int = 30) -> str:
        """
        MVP evidence collector:
        - Uses local/demo data (no external creds)
        - Writes a single EvidenceBundle JSON to ARTIFACT_DIR/<incident_id>.json
        """

        ARTIFACT_STORE = os.getenv("ARTIFACT_STORE", "fs").lower()
        S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL")
        S3_BUCKET = os.getenv("S3_BUCKET", "triage-artifacts")
        S3_REGION = os.getenv("S3_REGION", "us-east-1")


        context = get_current_context()
        conf = (context.get("dag_run") or {}).conf or {}
        incident_id = conf.get("incident_id", "unknown_incident")
        service = conf.get("service", "unknown_service")

        os.makedirs(ARTIFACT_DIR, exist_ok=True)

        end = datetime.now(timezone.utc)
        start = end - timedelta(minutes=window_minutes)
        query = f"{service} 5xx latency timeout db"
        runbook_hits = search_runbooks(query=query, limit=5)
        bundle = {
            "schema_version": "v1",
            "incident_id": incident_id,
            "service": service,
            "time_window": {"start_iso": start.isoformat(), "end_iso": end.isoformat()},
            "alerts": [
                {
                    "alert_id": "mock_501",
                    "provider": "mock",
                    "service": service,
                    "name": "5xx rate high",
                    "status": "triggered",
                    "started_at_iso": (end - timedelta(minutes=6)).isoformat(),
                    "priority": "P1",
                    "signal": {"metric": "http.server.errors", "value": 0.12, "threshold": 0.05},
                }
            ],
            "signals": [
                {"key": "error_rate", "value": 0.12, "unit": "ratio"},
                {"key": "latency_p95_ms", "value": 840, "unit": "ms"},
                {"key": "rps", "value": 2100, "unit": "rps"},
                {"key": "top_endpoint", "value": "POST /checkout"},
            ],
            "runbook_hits": runbook_hits,
            "hypotheses": [
                "Recent deploy regression",
                "Downstream dependency timeout",
                "DB connection pool saturation",
            ],
            "recommended_next_steps": [
                "Confirm if a deploy happened in the last 30 minutes",
                "Check dependency health and error budgets",
                "Inspect logs for top failing endpoint",
            ],
            "links": [
                {"type": "dashboard", "url": "https://example.local/dashboards/payments"},
                {"type": "logs", "url": "https://example.local/logs?q=5xx"},
            ],
            "generated_at_iso": utc_now_iso(),
        }

        
        key = f"evidence/v1/{incident_id}.json"
        payload = json.dumps(bundle, ensure_ascii=False, indent=2).encode("utf-8")

        if ARTIFACT_STORE == "s3":
            s3 = boto3.client(
                "s3",
                endpoint_url=S3_ENDPOINT_URL,
                region_name=S3_REGION,
            )
            s3.put_object(
                Bucket=S3_BUCKET,
                Key=key,
                Body=payload,
                ContentType="application/json",
            )
            return f"s3://{S3_BUCKET}/{key}"
        path = os.path.join(ARTIFACT_DIR, f"{incident_id}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(bundle, f, ensure_ascii=False, indent=2)

        return path

    # Create the task in the DAG.
    build_bundle()
