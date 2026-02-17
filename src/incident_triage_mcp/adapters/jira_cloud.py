from __future__ import annotations

import os
from typing import Any, Dict

import requests


class JiraCloudProvider:
    def __init__(self) -> None:
        self.base_url = os.getenv("JIRA_BASE_URL")
        self.email = os.getenv("JIRA_EMAIL")
        self.api_token = os.getenv("JIRA_API_TOKEN")
        if not self.base_url or not self.email or not self.api_token:
            raise RuntimeError("JiraCloudProvider requires JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN")

    def create_issue(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = self.base_url.rstrip("/") + "/rest/api/3/issue"
        auth = (self.email, self.api_token)

        fields = {
            "project": {"key": payload["project_key"]},
            "issuetype": {"name": payload.get("issue_type", "Incident")},
            "summary": payload["title"],
            "description": {
                "type": "doc",
                "version": 1,
                "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": payload["description_md"]}]}
                ],
            },
            "labels": payload.get("labels", []),
        }

        r = requests.post(url, json={"fields": fields}, auth=auth, timeout=20)
        r.raise_for_status()
        data = r.json()
        key = data.get("key")
        return {
            "created": True,
            "provider": "cloud",
            "issue_key": key,
            "browse_url": self.base_url.rstrip("/") + f"/browse/{key}" if key else None,
        }

    def validate(self) -> Dict[str, Any]:
        url = self.base_url.rstrip("/") + "/rest/api/3/myself"
        r = requests.get(url, auth=(self.email, self.api_token), timeout=20)
        r.raise_for_status()
        data = r.json()
        return {"accountId": data.get("accountId"), "displayName": data.get("displayName")}
