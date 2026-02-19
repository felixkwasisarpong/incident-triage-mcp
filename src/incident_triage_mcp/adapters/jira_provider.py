from __future__ import annotations
from typing import Protocol, Dict, Any
from incident_triage_mcp.adapters.jira_cloud import JiraCloudProvider
import os

class JiraProvider(Protocol):
    def create_issue(self, payload: Dict[str, Any]) -> Dict[str, Any]: ...
    def validate(self) -> Dict[str, Any]: ...
    def list_projects(self) -> list[Dict[str, Any]]: ...
    def list_issue_types(self, project_key: str) -> list[Dict[str, Any]]: ...

def provider_name() -> str:
    return (os.getenv("JIRA_PROVIDER", "mock") or "mock").lower()

from incident_triage_mcp.adapters.jira_mock import JiraMockProvider

def get_provider() -> JiraProvider:
    name = provider_name()
    if name == "mock":
        return JiraMockProvider()
    if name == "cloud":
        return JiraCloudProvider()
    raise RuntimeError(f"Unsupported JIRA_PROVIDER='{name}'. Use 'mock' or 'cloud'.")
