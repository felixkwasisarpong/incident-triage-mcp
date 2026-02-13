
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
# Incident Triage MCP

![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)
![MCP](https://img.shields.io/badge/MCP-compatible-brightgreen)
![Transport](https://img.shields.io/badge/transport-stdio%20%7C%20streamable--http-blueviolet)
![Docker](https://img.shields.io/badge/docker-ready-2496ED?logo=docker&logoColor=white)
![Kubernetes](https://img.shields.io/badge/kubernetes-ready-326CE5?logo=kubernetes&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

Incident Triage MCP is a **Model Context Protocol (MCP)** tool server for incident response.

It exposes structured, auditable triage tools (evidence collection, runbook search, safe actions, ticketing integrations, etc.) so AI agents (or LLM hosts) can diagnose and respond to outages **with guardrails**.

---

## What this project is (and isn’t)

- ✅ **Is:** an MCP server that provides incident-triage tools + a workflow-friendly “evidence bundle” artifact.
- ✅ **Is:** designed to run locally (Claude Desktop stdio), via Docker (HTTP), and in Kubernetes.
- ❌ **Is not:** an LLM agent by itself. Agents/hosts call these tools.

---

## Features

- **True MCP transports:** `stdio` and `streamable-http`
- **Tool discovery:** tools are auto-discovered by MCP clients (e.g., `tools/list`)
- **Structured schemas:** Pydantic models for tool inputs/outputs
- **Evidence Bundle artifact:** a single JSON “source of truth” produced by workflows
- **Audit-first:** JSONL audit events (stdout by default for k8s)
- **Guardrails:** RBAC + safe-action allowlists (WIP / expanding)
- **Pluggable integrations:** mock-first, real adapters added progressively

---

## Project layout

```text
incident-triage-mcp/
  pyproject.toml
  README.md
  docker-compose.yml
  airflow/
    dags/
    artifacts/
  runbooks/
  src/
    incident_triage_mcp/
      __init__.py
      server.py
      audit.py
      domain_models.py
      tools/
      adapters/
      policy/
  k8s/
    deployment.yaml
    service.yaml
    airflow-creds.yaml
```

---

## Quick start (local)

### 1) Install + run (stdio)

```bash
# from repo root
pip install -e .

# stdio transport (for Claude Desktop)
MCP_TRANSPORT=stdio python -m incident_triage_mcp.server
```

### 2) Key environment variables

```bash
# MCP
MCP_TRANSPORT=stdio|streamable-http
MCP_HOST=0.0.0.0
MCP_PORT=3333

# Audit logging (k8s-friendly)
AUDIT_MODE=stdout|file         # default: stdout
AUDIT_PATH=/data/audit.jsonl   # only used when AUDIT_MODE=file

# Airflow API (optional; used for workflow-trigger tools)
AIRFLOW_BASE_URL=http://localhost:8080
AIRFLOW_USERNAME=admin
AIRFLOW_PASSWORD=admin

# Local runbooks (real data source, no creds)
RUNBOOKS_DIR=./runbooks

# Evidence artifacts (when reading local artifacts)
AIRFLOW_ARTIFACT_DIR=./airflow/artifacts
```

---

## Docker Compose (Airflow + Postgres + MCP)

This repo supports a local dev stack where:
- **Airflow** runs evidence workflows
- **Artifacts** are written to a shared folder (`./airflow/artifacts`)
- **MCP server** reads those artifacts and exposes them as tools

### Start

```bash
mkdir -p airflow/dags airflow/artifacts airflow/logs airflow/plugins data runbooks

docker compose up --build
```

### Airflow UI

- URL: `http://localhost:8080`
- Login: `admin / admin`

### MCP (HTTP)

- Default: `http://localhost:3333` (streamable HTTP transport)

> Tip: Claude Desktop usually spawns MCP servers via **stdio**. For Docker/HTTP, you typically use an MCP client that supports HTTP or add a small local stdio→HTTP bridge.

---

## Evidence Bundle workflow

**Airflow produces** a single artifact per incident:

- `./airflow/artifacts/<INCIDENT_ID>.json`

The MCP server exposes tools to:
- trigger evidence DAGs
- fetch evidence bundles
- search runbooks

This is the intended flow:

1) Agent/host triggers evidence collection (Airflow DAG)
2) Airflow writes the Evidence Bundle JSON artifact
3) Agent/host reads the bundle via MCP tools
4) (later) ticket creation + safe actions use the same bundle

---

## Runbooks (local Markdown)

Put Markdown runbooks in:

- `./runbooks/*.md`

Then use the MCP tool (example):

- `runbooks_search(query="5xx latency timeout", limit=5)`

---

## Kubernetes (local or remote)

You can deploy the MCP server into Kubernetes (local via **kind/minikube** or remote like EKS/GKE/AKS).

### Local Kubernetes with kind (example)

```bash
brew install kind kubectl
kind create cluster --name triage

# build image
docker build -t incident-triage-mcp:0.1.0 .

# load into kind
kind load docker-image incident-triage-mcp:0.1.0 --name triage

# update k8s/deployment.yaml to use image: incident-triage-mcp:0.1.0
kubectl apply -f k8s/

kubectl port-forward svc/incident-triage-mcp 3333:80
```

Now the MCP service is reachable at `http://localhost:3333`.

> Note: In Kubernetes, `AUDIT_MODE=stdout` is recommended so log collectors can capture audit events.

---

## Roadmap (next)

- Replace mocks with **real adapters** (Jira/Datadog/etc.) via env-based provider selection
- Add **artifact store** that works in k8s (S3/MinIO) instead of filesystem-only
- Expand **RBAC + safe actions** with preconditions and approval tokens
- Add richer **observability** (metrics + structured tracing)

---

## Contributing

PRs welcome. If you add an integration, prefer this pattern:

- define a provider contract (interface)
- implement `mock` + `real`
- select via env vars (no code changes for users)

---

## License

MIT