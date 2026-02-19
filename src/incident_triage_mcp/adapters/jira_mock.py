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
