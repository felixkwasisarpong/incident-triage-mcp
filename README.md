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
- **Artifact store:** filesystem (dev) or S3-compatible (MinIO/S3) for Docker/Kubernetes
- **Audit-first:** JSONL audit events (stdout by default for k8s)
- **Guardrails:** RBAC + safe-action allowlists (WIP / expanding)
- **Pluggable integrations:** mock-first, real adapters added progressively
- **Demo-friendly tools:** `evidence.wait_for_bundle` and deterministic `incident.triage_summary`

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

# Evidence artifacts (recommended for Docker/K8s)
# Choose storage backend:
#   ARTIFACT_STORE=fs  -> read/write local filesystem artifacts (fast local dev)
#   ARTIFACT_STORE=s3  -> read/write via S3 API (MinIO locally, S3 in cloud)
ARTIFACT_STORE=fs|s3

# S3-compatible artifact store (required when ARTIFACT_STORE=s3)
S3_ENDPOINT_URL=http://localhost:9000
S3_BUCKET=triage-artifacts
S3_REGION=us-east-1
AWS_ACCESS_KEY_ID=minioadmin
AWS_SECRET_ACCESS_KEY=minioadmin
```

---

## Docker Compose (Airflow + Postgres + MCP)

This repo supports a local dev stack where:
- **Airflow** runs evidence workflows
- **MinIO (S3-compatible)** stores Evidence Bundles so the setup also works in Kubernetes
- **MCP server** reads Evidence Bundles from MinIO/S3 (or filesystem in dev mode)

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

### MinIO (artifact store)

- S3 API: `http://localhost:9000`
- Console UI: `http://localhost:9001`
- Credentials (dev): `minioadmin / minioadmin`

Check artifacts:

```bash
docker run --rm --network incident-triage-mcp_default \
  -e MC_HOST_local=http://minioadmin:minioadmin@minio:9000 \
  minio/mc:latest ls local/triage-artifacts/evidence/v1/
```

---

## Evidence Bundle workflow

**Airflow produces** a single artifact per incident:

- `fs: ./airflow/artifacts/<INCIDENT_ID>.json` (dev)
- `s3: s3://triage-artifacts/evidence/v1/<INCIDENT_ID>.json` (Docker/K8s)

The MCP server exposes tools to:
- trigger evidence DAGs
- fetch evidence bundles
- search runbooks

This is the intended flow:

1) Agent/host triggers evidence collection (Airflow DAG)
2) Airflow writes the Evidence Bundle JSON artifact
2.5) Agent/host optionally calls `evidence.wait_for_bundle` to poll until the artifact exists
3) Agent/host reads the bundle via MCP tools
4) (later) ticket creation + safe actions use the same bundle

---

## Demo flow (agent/host)

Typical demo sequence:

1) Trigger evidence collection:
   - `airflow_trigger_incident_dag(incident_id="INC-123", service="payments-api", window_minutes=30)`
2) Wait for the Evidence Bundle:
   - `evidence_wait_for_bundle(incident_id="INC-123", timeout_seconds=90, poll_seconds=2)`
3) Generate a deterministic triage summary (no LLM required):
   - `incident_triage_summary(incident_id="INC-123")`

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

> If MinIO is running in Docker on your Mac and MCP is running in kind, set `S3_ENDPOINT_URL` to `http://host.docker.internal:9000` in the Kubernetes Deployment.

---

## Roadmap (next)

- Replace mocks with **real adapters** (Jira/Datadog/etc.) via env-based provider selection
- ✅ Artifact store for Docker/K8s via MinIO/S3 (filesystem remains for fast local dev)
- Add a Helm chart + GitHub Actions to build/push multi-arch Docker images
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