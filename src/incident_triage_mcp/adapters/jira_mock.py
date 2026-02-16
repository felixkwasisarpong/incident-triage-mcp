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