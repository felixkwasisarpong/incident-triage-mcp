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
- **Pluggable integrations:** mock-first, real adapters added progressively (env-based provider selection)
- **Safe ticketing:** draft Jira tickets + gated create (dry-run by default, RBAC + confirm token)
- **Real idempotency for creates:** reusing `idempotency_key` returns the existing issue
- **Slack updates:** post incident summary + ticket context (safe dry-run by default)
- **Jira discovery tools:** list accessible projects and project-specific issue types (read-only)
- **Jira Cloud rich text:** draft content renders as clean ADF (H2 section headings + bullet lists + inline bold/code)
- **Demo-friendly tools:** `evidence.wait_for_bundle` and deterministic `incident.triage_summary`
- **Local LangGraph CLI agent:** run end-to-end triage without Claude Desktop restarts
- **Automated tests:** unit tests cover all MCP tools in `server.py`

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
# RBAC + safe actions
MCP_ROLE=viewer|triager|responder|admin
CONFIRM_TOKEN=CHANGE_ME_12345   # required for non-dry-run safe actions

# Jira provider selection
JIRA_PROVIDER=mock|cloud
JIRA_PROJECT_KEY=INC
JIRA_ISSUE_TYPE=Task

# Jira Cloud (required when JIRA_PROVIDER=cloud)
JIRA_BASE_URL=https://your-domain.atlassian.net
JIRA_EMAIL=you@example.com
JIRA_API_TOKEN=***

# from repo root
pip install -e .

# stdio transport (for Claude Desktop)
MCP_TRANSPORT=stdio incident-triage-mcp
```

### Packaging entrypoints (pip + docker)

Pip console scripts:

```bash
# MCP server
incident-triage-mcp

# Local LangGraph runner
incident-triage-agent --incident-id INC-123 --service payments-api --artifact-store fs --artifact-dir ./evidence
```

Docker image entrypoint:

```bash
# Default: starts MCP server (streamable-http on :3333)
docker run --rm -p 3333:3333 incident-triage-mcp:latest

# Override command: runs via uv in-project env
docker run --rm incident-triage-mcp:latest incident-triage-agent --incident-id INC-123 --service payments-api
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

# Local runbooks (real data source, no creds)
RUNBOOKS_DIR=./runbooks

# Evidence backend (standalone-first)
#   fs      -> read/write local Evidence Bundle JSON files
#   s3      -> read/write via S3 API (MinIO/S3)
#   airflow -> expose airflow_* tools (requires Airflow env vars)
#   none    -> disable evidence reads entirely
EVIDENCE_BACKEND=fs|s3|airflow|none

# Local evidence directory for fs backend
EVIDENCE_DIR=./evidence

# Legacy alias still supported (maps to fs|s3 when EVIDENCE_BACKEND is unset)
ARTIFACT_STORE=fs|s3

# Airflow API (required only when EVIDENCE_BACKEND=airflow)
AIRFLOW_BASE_URL=http://localhost:8080
AIRFLOW_USERNAME=admin
AIRFLOW_PASSWORD=admin

# S3-compatible artifact store (required when EVIDENCE_BACKEND=s3)
S3_ENDPOINT_URL=http://localhost:9000
S3_BUCKET=triage-artifacts
S3_REGION=us-east-1
AWS_ACCESS_KEY_ID=minioadmin
AWS_SECRET_ACCESS_KEY=minioadmin

# Jira ticket defaults
JIRA_PROJECT_KEY=INC
JIRA_ISSUE_TYPE=Task

# Slack notifications
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
SLACK_DEFAULT_CHANNEL=#incident-triage

# Idempotency storage for ticket create retries
IDEMPOTENCY_STORE_PATH=./data/jira_idempotency.json
```

---

## Standalone Mode (No Airflow)

Boot MCP standalone with only stdio + local runbooks:

```bash
MCP_TRANSPORT=stdio \
RUNBOOKS_DIR=./runbooks \
EVIDENCE_BACKEND=fs \
EVIDENCE_DIR=./evidence \
incident-triage-mcp
```

Offline demo flow (no Airflow required):

1. Seed deterministic evidence:
   - `evidence_seed_sample(incident_id="INC-123", service="payments-api", window_minutes=30)`
2. Summarize incident:
   - `incident_triage_summary(incident_id="INC-123")`
3. Draft Jira ticket from local evidence:
   - `jira_draft_ticket(incident_id="INC-123")`

Notes:
- `airflow_*` tools are only registered when `EVIDENCE_BACKEND=airflow`.
- If `EVIDENCE_BACKEND=airflow` but Airflow env vars are missing, server still starts and Airflow tool calls return a clear `airflow_disabled` error.

Quick verification tests:

```bash
# standalone behavior (no airflow required)
UV_CACHE_DIR=.uv-cache /opt/anaconda3/bin/uv run --project . \
  python -m unittest tests.test_standalone_mode -v
```

One-command standalone smoke check:

```bash
./scripts/smoke_standalone.sh INC-123 payments-api
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

Standalone Docker mode (no Airflow, no MinIO):

```bash
mkdir -p data evidence runbooks
docker compose --profile standalone up --build incident-triage-mcp-standalone
```

- MCP endpoint: `http://localhost:3334`

---

## Testing

Run all tests:

```bash
UV_CACHE_DIR=.uv-cache /opt/anaconda3/bin/uv run --project . \
  python -m unittest discover -s tests -p 'test_*.py' -v
```

The suite currently covers all MCP tools defined in `src/incident_triage_mcp/server.py`.

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
   - `airflow_trigger_incident_dag(incident_id="INC-123", service="payments-api")`
2) Wait for the Evidence Bundle:
   - `evidence_wait_for_bundle(incident_id="INC-123", timeout_seconds=90, poll_seconds=2)`
3) Generate a deterministic triage summary (no LLM required):
   - `incident_triage_summary(incident_id="INC-123")`
4) Optional one-call orchestration (safe ticket dry-run hook):
   - `incident_triage_run(incident_id="INC-123", service="payments-api", include_ticket=true)`
   - Override project key for the ticket hook: `incident_triage_run(incident_id="INC-123", service="payments-api", include_ticket=true, project_key="PAY")`
5) Optional Slack notification hook (safe dry-run by default):
   - `incident_triage_run(incident_id="INC-123", service="payments-api", notify_slack=true)`
   - Set channel and send for real: `incident_triage_run(incident_id="INC-123", service="payments-api", notify_slack=true, slack_channel="#incident-triage", slack_dry_run=false)`

---

## Jira ticketing demo

0) Validate Jira Cloud credentials (cloud provider only):
   - `jira_validate_credentials()`

1) Discover Jira metadata first (recommended):
   - `jira_list_projects()`
   - `jira_list_issue_types()`  # uses `JIRA_PROJECT_KEY` default
   - `jira_list_issue_types(project_key="SCRUM")`

2) Draft a ticket (no credentials required, uses `JIRA_PROJECT_KEY` by default):
   - `jira_draft_ticket(incident_id="INC-123")`
   - Override project key per call: `jira_draft_ticket(incident_id="INC-123", project_key="PAY")`

3) Safe create (mock provider by default):
   - Dry run (default):
     - `jira_create_ticket(incident_id="INC-123")`
     - Override project key per call: `jira_create_ticket(incident_id="INC-123", project_key="PAY")`
   - Create (requires explicit approval inputs):
     - `jira_create_ticket(incident_id="INC-123", dry_run=false, reason="Track incident timeline and coordinate responders", confirm_token="CHANGE_ME_12345", idempotency_key="INC-123-PAY-1")`

Notes:
- Non-dry-run is blocked unless **RBAC** allows it (`MCP_ROLE=responder|admin`) and `CONFIRM_TOKEN` is provided.
- Swap providers via env: `JIRA_PROVIDER=mock` (demo) or `JIRA_PROVIDER=cloud` (real Jira Cloud).
- `JIRA_ISSUE_TYPE` defaults to `Task` (used for creates unless overridden in code).
- Jira Cloud descriptions are sent as ADF and render section headers/bullets/inline formatting in the Jira UI.
- Reusing the same `idempotency_key` on non-dry-run `jira_create_ticket` returns the existing issue instead of creating a duplicate.

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

- ✅ Ticketing: Jira draft + gated create (mock provider); add Jira Cloud provider wiring + richer formatting
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
