from __future__ import annotations

import os
from typing import Any, Dict

import requests


class AirflowAPI:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = os.getenv("AIRFLOW_USERNAME")
        self.password = os.getenv("AIRFLOW_PASSWORD")
        if not self.username or not self.password:
            raise RuntimeError(
                "Missing Airflow credentials. Set AIRFLOW_USERNAME and AIRFLOW_PASSWORD."
            )
        self._basic_auth = (self.username, self.password)
        self._api_version = (os.getenv("AIRFLOW_API_VERSION") or "auto").strip().lower()
        self._auth_mode = (os.getenv("AIRFLOW_AUTH_MODE") or "auto").strip().lower()
        self._access_token = (os.getenv("AIRFLOW_ACCESS_TOKEN") or "").strip() or None
        self._timeout = 15

    def _v1_url(self, path: str) -> str:
        return f"{self.base_url}/api/v1{path}"

    def _v2_url(self, path: str) -> str:
        return f"{self.base_url}/api/v2{path}"

    def _raise_for_auth(self, response: requests.Response, url: str, api_version: str) -> None:
        if response.status_code != 401:
            return
        if api_version == "v2":
            raise RuntimeError(
                "Airflow API 401 UNAUTHORIZED for Airflow v2 API. "
                "Check AIRFLOW_USERNAME/AIRFLOW_PASSWORD (used for /auth/token) or "
                "AIRFLOW_ACCESS_TOKEN. URL="
                f"{url}"
            )
        raise RuntimeError(
            "Airflow API 401 UNAUTHORIZED. Check AIRFLOW_USERNAME/AIRFLOW_PASSWORD. "
            f"URL={url}"
        )

    def _login_v2(self) -> str:
        if self._access_token:
            return self._access_token
        url = f"{self.base_url}/auth/token"
        response = requests.post(
            url,
            json={"username": self.username, "password": self.password},
            timeout=self._timeout,
        )
        self._raise_for_auth(response, url, "v2")
        response.raise_for_status()
        payload = response.json()
        token = payload.get("access_token")
        if not isinstance(token, str) or not token.strip():
            raise RuntimeError("Airflow /auth/token did not return access_token.")
        self._access_token = token.strip()
        return self._access_token

    def _request_v1(self, method: str, path: str, *, json_body: dict[str, Any] | None = None) -> requests.Response:
        url = self._v1_url(path)
        response = requests.request(
            method,
            url,
            json=json_body,
            auth=self._basic_auth,
            timeout=self._timeout,
        )
        self._raise_for_auth(response, url, "v1")
        return response

    def _request_v2(self, method: str, path: str, *, json_body: dict[str, Any] | None = None) -> requests.Response:
        url = self._v2_url(path)
        token = self._login_v2()
        headers = {"Authorization": f"Bearer {token}"}
        response = requests.request(
            method,
            url,
            json=json_body,
            headers=headers,
            timeout=self._timeout,
        )
        if response.status_code == 401 and self._auth_mode in {"auto", "token"}:
            # Token may be expired/invalid; refresh once when credentials are available.
            self._access_token = None
            token = self._login_v2()
            headers = {"Authorization": f"Bearer {token}"}
            response = requests.request(
                method,
                url,
                json=json_body,
                headers=headers,
                timeout=self._timeout,
            )
        self._raise_for_auth(response, url, "v2")
        return response

    def _request_auto(
        self, method: str, path: str, *, json_v1: dict[str, Any] | None = None, json_v2: dict[str, Any] | None = None
    ) -> requests.Response:
        # Prefer v2 first because Airflow 3 removed /api/v1 entirely.
        try:
            response = self._request_v2(method, path, json_body=json_v2)
            if response.status_code < 500:
                return response
        except requests.RequestException:
            pass
        except RuntimeError as exc:
            if "access_token" not in str(exc).lower() and "/auth/token" not in str(exc):
                raise
        response = self._request_v1(method, path, json_body=json_v1)
        return response

    def _request(
        self, method: str, path: str, *, json_v1: dict[str, Any] | None = None, json_v2: dict[str, Any] | None = None
    ) -> requests.Response:
        version = self._api_version
        if version == "v1":
            return self._request_v1(method, path, json_body=json_v1)
        if version == "v2":
            return self._request_v2(method, path, json_body=json_v2)
        return self._request_auto(method, path, json_v1=json_v1, json_v2=json_v2)

    def trigger_dag(self, dag_id: str, conf: Dict[str, Any]) -> Dict[str, Any]:
        path = f"/dags/{dag_id}/dagRuns"
        # Airflow 3 /api/v2 requires logical_date to be present (nullable is allowed).
        r = self._request(
            "POST",
            path,
            json_v1={"conf": conf},
            json_v2={"conf": conf, "logical_date": None},
        )
        r.raise_for_status()
        return r.json()

    def get_dag_run(self, dag_id: str, dag_run_id: str) -> Dict[str, Any]:
        path = f"/dags/{dag_id}/dagRuns/{dag_run_id}"
        r = self._request("GET", path)
        r.raise_for_status()
        return r.json()
