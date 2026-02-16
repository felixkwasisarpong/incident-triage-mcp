from __future__ import annotations
import os

class RBACError(RuntimeError):
    pass

# simplest roles for now
ROLE = os.getenv("MCP_ROLE", "viewer").lower()

ROLE_ALLOW = {
    "viewer": set(),
    "triager": {"jira.draft_ticket"},
    "responder": {"jira.draft_ticket", "jira.create_ticket"},
    "admin": {"*"},
}

def role() -> str:
    return ROLE

def require_allowed(tool_name: str) -> None:
    allow = ROLE_ALLOW.get(ROLE, set())
    if "*" in allow:
        return
    if tool_name not in allow:
        raise RBACError(f"Role '{ROLE}' is not allowed to call '{tool_name}'.")