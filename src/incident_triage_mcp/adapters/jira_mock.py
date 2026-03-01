from __future__ import annotations
from typing import Dict, Any
import uuid

class JiraMockProvider:
    def create_issue(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        key = f"{payload.get('project_key','INC')}-{str(uuid.uuid4())[:8].upper()}"
        return {
            "created": True,
            "provider": "mock",
            "issue_key": key,
            "browse_url": f"https://example.local/jira/browse/{key}",
            "payload": payload,
        }

    def add_comment(self, issue_key: str, body_md: str) -> Dict[str, Any]:
        _ = body_md
        return {
            "added": True,
            "issue_key": issue_key,
            "comment_id": "mock-comment-1",
        }

    def transition_issue(self, issue_key: str, transition_name: str) -> Dict[str, Any]:
        return {
            "transitioned": True,
            "issue_key": issue_key,
            "transition": transition_name,
        }

    def validate(self) -> Dict[str, Any]:
        return {"accountId": "mock-account", "displayName": "Mock Jira User"}

    def list_projects(self) -> list[Dict[str, Any]]:
        return [
            {
                "id": "10000",
                "key": "SCRUM",
                "name": "Scrum Project",
                "project_type_key": "software",
                "simplified": False,
            },
            {
                "id": "10001",
                "key": "INC",
                "name": "Incident Management",
                "project_type_key": "service_desk",
                "simplified": True,
            },
        ]

    def list_issue_types(self, project_key: str) -> list[Dict[str, Any]]:
        _ = project_key
        return [
            {"id": "1", "name": "Task", "description": "A task that needs to be done.", "subtask": False},
            {"id": "2", "name": "Bug", "description": "A problem that impairs functionality.", "subtask": False},
            {"id": "3", "name": "Story", "description": "A feature request.", "subtask": False},
        ]
