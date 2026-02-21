from __future__ import annotations

import os
from typing import Any, Dict

import requests


class ServiceNowProvider:
    def __init__(self) -> None:
        self.base_url = (os.getenv("SERVICENOW_BASE_URL") or "").strip().rstrip("/")
        self.username = (os.getenv("SERVICENOW_USERNAME") or "").strip()
        self.password = (os.getenv("SERVICENOW_PASSWORD") or "").strip()
        self.table = (os.getenv("SERVICENOW_TABLE", "incident") or "incident").strip()

        missing: list[str] = []
        if not self.base_url:
            missing.append("SERVICENOW_BASE_URL")
        if not self.username:
            missing.append("SERVICENOW_USERNAME")
        if not self.password:
            missing.append("SERVICENOW_PASSWORD")
        if missing:
            raise RuntimeError(
                "ServiceNow provider requires " + ", ".join(missing)
            )

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    @staticmethod
    def _priority_map(priority: str) -> tuple[str, str]:
        normalized = (priority or "").strip().upper()
        if normalized == "P1":
            return "1", "1"
        if normalized == "P2":
            return "1", "2"
        if normalized == "P4":
            return "3", "3"
        return "2", "2"

    def _auth(self) -> tuple[str, str]:
        return (self.username, self.password)

    def create_issue(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        urgency, impact = self._priority_map(str(payload.get("priority") or "P3"))
        body: dict[str, Any] = {
            "short_description": payload.get("title") or "Incident",
            "description": payload.get("description_md") or "",
            "urgency": urgency,
            "impact": impact,
            "category": (os.getenv("SERVICENOW_CATEGORY", "inquiry") or "inquiry").strip(),
            "u_source": "incident-triage-mcp",
        }
        idempotency_key = payload.get("idempotency_key")
        if idempotency_key:
            body["u_idempotency_key"] = str(idempotency_key)

        labels = payload.get("labels")
        if isinstance(labels, list) and labels:
            body["u_labels"] = ",".join(str(label) for label in labels if str(label).strip())

        response = requests.post(
            self._url(f"/api/now/table/{self.table}"),
            auth=self._auth(),
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            json=body,
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
        result = data.get("result") if isinstance(data, dict) else {}
        if not isinstance(result, dict):
            result = {}

        number = str(result.get("number") or "").strip()
        sys_id = str(result.get("sys_id") or "").strip()
        issue_key = number or sys_id or None
        browse_url = (
            self._url(f"/nav_to.do?uri={self.table}.do?sys_id={sys_id}")
            if sys_id
            else None
        )
        return {
            "created": True,
            "provider": "servicenow",
            "issue_key": issue_key,
            "browse_url": browse_url,
            "sys_id": sys_id or None,
            "number": number or None,
        }

    def validate(self) -> Dict[str, Any]:
        response = requests.get(
            self._url("/api/now/table/sys_user"),
            auth=self._auth(),
            headers={"Accept": "application/json"},
            params={"sysparm_limit": 1, "sysparm_fields": "sys_id,user_name,name,email"},
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
        rows = data.get("result") if isinstance(data, dict) else []
        first = rows[0] if isinstance(rows, list) and rows else {}
        if not isinstance(first, dict):
            first = {}
        return {
            "accountId": first.get("sys_id"),
            "displayName": first.get("name") or first.get("user_name"),
            "email": first.get("email"),
            "provider": "servicenow",
        }

    def list_projects(self) -> list[Dict[str, Any]]:
        return [
            {
                "id": "servicenow",
                "key": "SNOW",
                "name": "ServiceNow",
                "project_type_key": "itsm",
                "simplified": True,
            }
        ]

    def list_issue_types(self, project_key: str) -> list[Dict[str, Any]]:
        configured = (os.getenv("SERVICENOW_ISSUE_TYPES", "Incident") or "Incident").strip()
        names = [name.strip() for name in configured.split(",") if name.strip()]
        if not names:
            names = ["Incident"]
        return [
            {
                "id": name.lower().replace(" ", "_"),
                "name": name,
                "description": f"ServiceNow {name}",
                "subtask": False,
                "project_key": project_key,
            }
            for name in names
        ]
