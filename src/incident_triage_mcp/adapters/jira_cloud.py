from __future__ import annotations

import os
import re
from typing import Any, Dict

import requests


_INLINE_TOKEN_RE = re.compile(r"(\*\*[^*]+\*\*|`[^`]+`)")


def _inline_nodes(text: str) -> list[Dict[str, Any]]:
    nodes: list[Dict[str, Any]] = []
    for token in _INLINE_TOKEN_RE.split(text):
        if not token:
            continue
        if token.startswith("**") and token.endswith("**") and len(token) > 4:
            nodes.append({"type": "text", "text": token[2:-2], "marks": [{"type": "strong"}]})
            continue
        if token.startswith("`") and token.endswith("`") and len(token) > 2:
            nodes.append({"type": "text", "text": token[1:-1], "marks": [{"type": "code"}]})
            continue
        nodes.append({"type": "text", "text": token})
    return nodes or [{"type": "text", "text": ""}]


def _paragraph_node(text: str) -> Dict[str, Any]:
    return {"type": "paragraph", "content": _inline_nodes(text)}


def _heading_node(text: str, level: int = 2) -> Dict[str, Any]:
    return {"type": "heading", "attrs": {"level": level}, "content": _inline_nodes(text)}


def _bullet_list_node(items: list[str]) -> Dict[str, Any]:
    return {
        "type": "bulletList",
        "content": [
            {"type": "listItem", "content": [_paragraph_node(item)]}
            for item in items
        ],
    }


def _markdown_to_adf(markdown: str) -> Dict[str, Any]:
    content: list[Dict[str, Any]] = []
    bullets: list[str] = []

    def flush_bullets() -> None:
        if bullets:
            content.append(_bullet_list_node(bullets.copy()))
            bullets.clear()

    for raw_line in (markdown or "").splitlines():
        line = raw_line.strip()

        if not line:
            flush_bullets()
            continue

        if line.startswith("## "):
            flush_bullets()
            content.append(_heading_node(line[3:].strip(), level=2))
            continue

        if line.startswith("- "):
            bullets.append(line[2:].strip())
            continue

        flush_bullets()
        content.append(_paragraph_node(line))

    flush_bullets()

    if not content:
        content.append(_paragraph_node("No details provided."))

    return {"type": "doc", "version": 1, "content": content}


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
            "issuetype": {"name": payload.get("issue_type", "Task")},
            "summary": payload["title"],
            "description": _markdown_to_adf(payload.get("description_md", "")),
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
