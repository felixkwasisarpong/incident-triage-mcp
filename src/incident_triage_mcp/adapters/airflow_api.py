from __future__ import annotations
from typing import Any, Dict
import os
import requests

class AirflowAPI:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = os.getenv("AIRFLOW_USERNAME", "admin")
        self.password = os.getenv("AIRFLOW_PASSWORD", "admin")
        self.auth = (self.username, self.password)

    def trigger_dag(self, dag_id: str, conf: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.base_url}/api/v1/dags/{dag_id}/dagRuns"
        r = requests.post(url, json={"conf": conf}, auth=self.auth, timeout=15)
        # Helpful error visibility
        if r.status_code == 401:
            raise RuntimeError(
                f"Airflow API 401 UNAUTHORIZED. Check AIRFLOW_USERNAME/AIRFLOW_PASSWORD. "
                f"URL={url}"
            )
        r.raise_for_status()
        return r.json()

    def get_dag_run(self, dag_id: str, dag_run_id: str) -> Dict[str, Any]:
        url = f"{self.base_url}/api/v1/dags/{dag_id}/dagRuns/{dag_run_id}"
        r = requests.get(url, auth=self.auth, timeout=15)
        if r.status_code == 401:
            raise RuntimeError(
                f"Airflow API 401 UNAUTHORIZED. Check AIRFLOW_USERNAME/AIRFLOW_PASSWORD. "
                f"URL={url}"
            )
        r.raise_for_status()
        return r.json()