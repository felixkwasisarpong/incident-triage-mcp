import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS_SPEC_PATH = ROOT / "spec" / "mcp-tools.v1.json"

REQUIRED_TOOL_NAMES = {
    "evidence_get_bundle",
    "evidence_wait_for_bundle",
    "incident_triage_summary",
    "jira_draft_ticket",
    "jira_create_ticket",
}


def _load_spec() -> dict:
    return json.loads(TOOLS_SPEC_PATH.read_text(encoding="utf-8"))


def test_mcp_tools_v1_contains_required_tool_entries() -> None:
    spec = _load_spec()

    assert spec["schema_version"] == "v1"
    tools = spec["tools"]
    names = {tool["name"] for tool in tools}

    assert REQUIRED_TOOL_NAMES.issubset(names)


def test_tool_entries_have_required_contract_fields() -> None:
    spec = _load_spec()
    required_fields = {
        "name",
        "purpose",
        "inputs",
        "outputs",
        "mutating",
        "requires_confirm_token",
        "idempotent",
    }

    for tool in spec["tools"]:
        assert required_fields.issubset(tool.keys())
        assert isinstance(tool["inputs"], dict)
        assert isinstance(tool["outputs"], dict)


def test_mutating_tools_require_confirm_token_and_idempotency() -> None:
    spec = _load_spec()

    for tool in spec["tools"]:
        if tool["mutating"]:
            assert tool["requires_confirm_token"] is True, tool["name"]
            assert tool["idempotent"] is True, tool["name"]

    jira_create = next(t for t in spec["tools"] if t["name"] == "jira_create_ticket")
    assert jira_create["mutating"] is True
    assert jira_create["requires_confirm_token"] is True
    assert jira_create["idempotent"] is True
