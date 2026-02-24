# incident-triage-mcp

`incident-triage-mcp` is a **Model Context Protocol (MCP) server** for incident response workflows.

It exposes auditable, tool-based incident triage capabilities that AI hosts/agents can call over MCP (`stdio` or `streamable-http`) without giving the model direct infrastructure access.

## What It Provides

- MCP tools for incident triage and evidence retrieval
- Deterministic incident summaries from normalized evidence bundles
- Safe action gating (RBAC, confirm tokens, audit logging)
- Ticketing integrations (Jira / ServiceNow)
- Notification integrations (Slack / Teams)
- Optional Airflow workflow trigger integration
- Standalone mode (no Airflow required)

## Typical Architecture

- **Agent/LLM host** calls MCP tools only
- **MCP server** enforces guardrails and orchestrates triage actions
- **Airflow (optional)** collects/normalizes evidence into an `EvidenceBundle v1`
- **Evidence backend** can be filesystem (local) or S3-compatible storage (prod)

## Install

```bash
pip install incident-triage-mcp
```

Optional AWS extras (S3 / CloudWatch / X-Ray related integrations):

```bash
pip install "incident-triage-mcp[aws]"
```

## Run

### MCP server (stdio)

```bash
MCP_TRANSPORT=stdio incident-triage-mcp
```

### MCP server (HTTP)

```bash
MCP_TRANSPORT=streamable-http MCP_HTTP_AUTH_MODE=api_key MCP_HTTP_API_KEY=change-me incident-triage-mcp
```

### Local LangGraph agent CLI

```bash
incident-triage-agent --incident-id INC-123 --service payments-api
```

## Core Configuration (overview)

- `WORKFLOW_BACKEND=none|airflow`
- `EVIDENCE_BACKEND=fs|s3|none` (legacy `airflow` mode still supported)
- `MCP_TRANSPORT=stdio|streamable-http`
- `MCP_HTTP_AUTH_MODE=none|api_key|jwt_hs256`
- `JIRA_PROVIDER=mock|cloud|servicenow`
- `NOTIFY_PROVIDER=slack|teams`

## Project Links

- GitHub: https://github.com/felixkwasisarpong/incident-triage-mcp
- Issues: https://github.com/felixkwasisarpong/incident-triage-mcp/issues

For full setup (Docker, Kubernetes, Airflow, Helm, provider configs, and demos), see the repository `README.md`.
