
# Incident Triage MCP

![Python Version](https://img.shields.io/badge/python-3.10%2B-blue.svg)
![MCP Server](https://img.shields.io/badge/MCP-Compatible-brightgreen)
![Status](https://img.shields.io/badge/status-MVP%20In%20Progress-yellow)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

Incident Triage MCP is a Model Context Protocol–native incident‑response tool server.  
It exposes structured triage tools — alerts, service health, runbook search, ticket creation, and more — to enable AI agents or LLM hosts to diagnose and respond to outages safely.

## 🚀 Features

- True MCP transport support (stdio + streamable HTTP)
- Auto‑discovered tools via `tools/list`
- Structured tool schemas using Pydantic
- Mock integrations (Datadog, Jira, Runbooks) for demo‑ready workflows
- Audit‑first design (JSONL append‑only log)
- Extensible policy engine (RBAC + safe‑action allowlists)
- Clean modular architecture (tools / adapters / policy / domain models)

## 📁 Project Structure

```
incident-triage-mcp/
  pyproject.toml
  README.md
  src/
    incident_triage_mcp/
      server.py
      audit.py
      domain_models.py
      tools/
      adapters/
      policy/
```

## 🛠️ Running the MCP Server

### Stdio Mode (recommended for local development)
```
incident-triage-mcp
```

### Streamable HTTP Mode
```
MCP_TRANSPORT=streamable-http incident-triage-mcp
```

## 📚 Documentation

Full tool descriptions and schemas are located in `domain_models.py` and `tools/`.

## 🤝 Contributing

Pull requests and improvements are welcome. This project is designed to be modular and easy to extend.

## 📝 License

MIT License.

￼￼