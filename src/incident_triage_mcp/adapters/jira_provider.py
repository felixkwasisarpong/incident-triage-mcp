from __future__ import annotations
from typing import Protocol, Dict, Any
import os

class JiraProvider(Protocol):
    def create_issue(self, payload: Dict[str, Any]) -> Dict[str, Any]: ...

def provider_name() -> str:
    return (os.getenv("JIRA_PROVIDER", "mock") or "mock").lower()

from incident_triage_mcp.adapters.jira_mock import JiraMockProvider

def get_provider() -> JiraProvider:
    name = provider_name()
    if name == "mock":
        return JiraMockProvider()
    # later: add JiraCloudProvider()
    raise RuntimeError(f"Unsupported JIRA_PROVIDER='{name}'. Use 'mock' for now.")