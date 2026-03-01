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

    def list_projects(self) -> list[Dict[str, Any]]:
        auth = (self.email, self.api_token)
        url = self.base_url.rstrip("/") + "/rest/api/3/project/search"
        start_at = 0
        out: list[Dict[str, Any]] = []

        while True:
            r = requests.get(
                url,
                auth=auth,
                params={"startAt": start_at, "maxResults": 50},
                timeout=20,
            )
            r.raise_for_status()
            data = r.json()

            values = data.get("values") or data.get("projects") or []
            for p in values:
                out.append(
                    {
                        "id": p.get("id"),
                        "key": p.get("key"),
                        "name": p.get("name"),
                        "project_type_key": p.get("projectTypeKey"),
                        "simplified": p.get("simplified"),
                    }
                )

            if data.get("isLast", True):
                break

            if not values:
                break

            start_at = int(data.get("startAt", start_at)) + int(data.get("maxResults", len(values)))

        return out

    def add_comment(self, issue_key: str, body_md: str) -> Dict[str, Any]:
        url = self.base_url.rstrip("/") + f"/rest/api/3/issue/{issue_key}/comment"
        auth = (self.email, self.api_token)
        body = _markdown_to_adf(body_md)
        r = requests.post(url, json={"body": body}, auth=auth, timeout=20)
        r.raise_for_status()
        data = r.json()
        return {
            "added": True,
            "issue_key": issue_key,
            "comment_id": data.get("id"),
        }

    def transition_issue(self, issue_key: str, transition_name: str) -> Dict[str, Any]:
        auth = (self.email, self.api_token)
        transitions_url = self.base_url.rstrip("/") + f"/rest/api/3/issue/{issue_key}/transitions"

        r = requests.get(transitions_url, auth=auth, timeout=20)
        r.raise_for_status()
        transitions = r.json().get("transitions") or []

        match = next(
            (t for t in transitions if t.get("name", "").lower() == transition_name.lower()),
            None,
        )
        if match is None:
            available = [t.get("name") for t in transitions]
            raise RuntimeError(
                f"Transition '{transition_name}' not found for {issue_key}. "
                f"Available: {available}"
            )

        r = requests.post(
            transitions_url,
            json={"transition": {"id": match["id"]}},
            auth=auth,
            timeout=20,
        )
        r.raise_for_status()
        return {
            "transitioned": True,
            "issue_key": issue_key,
            "transition": transition_name,
        }

    def list_issue_types(self, project_key: str) -> list[Dict[str, Any]]:
        auth = (self.email, self.api_token)
        issue_types: list[Dict[str, Any]] = []

        # Preferred endpoint in modern Jira Cloud.
        primary_url = self.base_url.rstrip("/") + f"/rest/api/3/issue/createmeta/{project_key}/issuetypes"
        r = requests.get(primary_url, auth=auth, timeout=20)
        if r.status_code != 404:
            r.raise_for_status()
            data = r.json()
            values = data.get("values") if isinstance(data, dict) else data
            for it in (values or []):
                issue_types.append(
                    {
                        "id": it.get("id"),
                        "name": it.get("name"),
                        "description": it.get("description"),
                        "subtask": bool(it.get("subtask", False)),
                    }
                )
            return issue_types

        # Backward-compatible fallback endpoint.
        fallback_url = self.base_url.rstrip("/") + "/rest/api/3/issue/createmeta"
        r = requests.get(
            fallback_url,
            auth=auth,
            params={"projectKeys": project_key, "expand": "projects.issuetypes"},
            timeout=20,
        )
        r.raise_for_status()
        data = r.json()
        projects = data.get("projects") or []
        project = projects[0] if projects else {}
        for it in (project.get("issuetypes") or []):
            issue_types.append(
                {
                    "id": it.get("id"),
                    "name": it.get("name"),
                    "description": it.get("description"),
                    "subtask": bool(it.get("subtask", False)),
                }
            )
        return issue_types
