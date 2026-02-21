# Incident Triage MCP

<!-- mcp-name: io.github.felixkwasisarpong/incident-triage-mcp -->

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
- **Built-in service telemetry:** request/adaptor counters + latency via `mcp_health` and `mcp_metrics`
- **HTTP health endpoints:** `/healthz` and `/metrics` for streamable-http deployments
- **Guardrails:** RBAC + safe-action allowlists (WIP / expanding)
- **Pluggable integrations:** mock-first, real adapters added progressively (env-based provider selection)
- **Safe ticketing:** draft Jira tickets + gated create (dry-run by default, RBAC + confirm token)
- **Real idempotency for creates:** reusing `idempotency_key` returns the existing issue
- **Slack/Teams updates:** post incident summary + ticket context (safe dry-run by default)
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
  deploy/
    profiles/
      local.env.example
      staging.env.example
      prod.env.example
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
JIRA_PROVIDER=mock|cloud|servicenow
JIRA_PROJECT_KEY=INC
JIRA_ISSUE_TYPE=Task

# Jira Cloud (required when JIRA_PROVIDER=cloud)
JIRA_BASE_URL=https://your-domain.atlassian.net
JIRA_EMAIL=you@example.com
JIRA_API_TOKEN=***

# ServiceNow (required when JIRA_PROVIDER=servicenow)
SERVICENOW_BASE_URL=https://your-instance.service-now.com
SERVICENOW_USERNAME=incident_bot
SERVICENOW_PASSWORD=***
SERVICENOW_TABLE=incident

# from repo root
pip install -e .

# if you plan to use AWS-backed adapters/backends (CloudWatch, X-Ray, S3 evidence)
pip install -e ".[aws]"

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
DEPLOYMENT_PROFILE=local|staging|prod
MCP_TRANSPORT=stdio|streamable-http
MCP_HOST=0.0.0.0
MCP_PORT=3333

# HTTP auth boundary (applies only when MCP_TRANSPORT=streamable-http)
MCP_HTTP_AUTH_MODE=none|api_key|jwt_hs256
MCP_HTTP_API_KEY=<required-when-mode-is-api_key>
MCP_HTTP_JWT_SECRET=<required-when-mode-is-jwt_hs256>
MCP_HTTP_JWT_ISSUER=<optional-expected-iss-claim>
MCP_HTTP_JWT_AUDIENCE=<optional-expected-aud-claim>
MCP_HTTP_JWT_LEEWAY_SECONDS=30
# Optional request correlation headers from caller:
#   x-request-id or x-correlation-id

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
AIRFLOW_USERNAME=<airflow-username>
AIRFLOW_PASSWORD=<airflow-password>

# S3-compatible artifact store (required when EVIDENCE_BACKEND=s3)
# Requires optional extra: pip install "incident-triage-mcp[aws]"
S3_ENDPOINT_URL=http://localhost:9000
S3_BUCKET=triage-artifacts
S3_REGION=us-east-1
AWS_ACCESS_KEY_ID=minioadmin
AWS_SECRET_ACCESS_KEY=minioadmin

# Ticket provider selection
JIRA_PROVIDER=mock|cloud|servicenow

# Jira ticket defaults
JIRA_PROJECT_KEY=INC
JIRA_ISSUE_TYPE=Task

# Jira Cloud credentials (required when JIRA_PROVIDER=cloud)
JIRA_BASE_URL=https://your-domain.atlassian.net
JIRA_EMAIL=you@example.com
JIRA_API_TOKEN=***

# ServiceNow credentials (required when JIRA_PROVIDER=servicenow)
SERVICENOW_BASE_URL=https://your-instance.service-now.com
SERVICENOW_USERNAME=incident_bot
SERVICENOW_PASSWORD=***
SERVICENOW_TABLE=incident
SERVICENOW_CATEGORY=inquiry

# Notification provider
NOTIFY_PROVIDER=slack|teams

# Slack notifications (used when NOTIFY_PROVIDER=slack)
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
SLACK_DEFAULT_CHANNEL=#incident-triage

# Teams notifications (used when NOTIFY_PROVIDER=teams)
TEAMS_WEBHOOK_URL=https://outlook.office.com/webhook/...
TEAMS_DEFAULT_CHANNEL="Incident Triage"

# Idempotency storage for ticket create retries
# file (default) keeps local/dev behavior; redis/postgres are durable backends for prod.
IDEMPOTENCY_BACKEND=file|redis|postgres|none

# File backend (IDEMPOTENCY_BACKEND=file)
IDEMPOTENCY_STORE_PATH=./data/jira_idempotency.json

# Redis backend (IDEMPOTENCY_BACKEND=redis)
IDEMPOTENCY_REDIS_URL=redis://localhost:6379/0
IDEMPOTENCY_REDIS_KEY_PREFIX=incident-triage:idempotency:
IDEMPOTENCY_REDIS_TTL_SECONDS=604800

# Postgres backend (IDEMPOTENCY_BACKEND=postgres)
IDEMPOTENCY_POSTGRES_DSN=postgresql://user:pass@localhost:5432/incident_triage
IDEMPOTENCY_POSTGRES_TABLE=jira_idempotency

# Adapter provider selection (prod scaffold; defaults are mock)
ALERTS_PROVIDER=mock|datadog|cloudwatch|prometheus|pagerduty|opsgenie
METRICS_PROVIDER=mock|datadog|cloudwatch|prometheus
LOGS_PROVIDER=mock|datadog|cloudwatch|elk|none
TRACES_PROVIDER=mock|datadog|cloudwatch|xray|otel|none

# Datadog credentials (required when ALERTS_PROVIDER or METRICS_PROVIDER is datadog)
DATADOG_API_KEY=<datadog-api-key>
DATADOG_APP_KEY=<datadog-application-key>
DATADOG_SITE=datadoghq.com

# CloudWatch settings (used when ALERTS_PROVIDER or METRICS_PROVIDER is cloudwatch)
# Requires optional extra: pip install "incident-triage-mcp[aws]"
# Auth can come from env credentials below or IAM role/default AWS credential chain.
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=<optional-static-key>
AWS_SECRET_ACCESS_KEY=<optional-static-secret>
CLOUDWATCH_NAMESPACE=IncidentTriage
CLOUDWATCH_DIMENSION_NAME=Service
CLOUDWATCH_ERROR_RATE_METRIC=ErrorRate
CLOUDWATCH_LATENCY_P95_METRIC=LatencyP95
CLOUDWATCH_RPS_METRIC=RequestsPerSecond
CLOUDWATCH_PERIOD_SECONDS=60

# Prometheus settings (used when ALERTS_PROVIDER or METRICS_PROVIDER is prometheus)
PROMETHEUS_BASE_URL=http://localhost:9090
PROMETHEUS_BEARER_TOKEN=<optional-bearer-token>
PROMETHEUS_USERNAME=<optional-basic-auth-username>
PROMETHEUS_PASSWORD=<optional-basic-auth-password>
PROMETHEUS_SERVICE_LABEL=service
PROMETHEUS_QUERY_STEP_SECONDS=60
PROMETHEUS_ERROR_RATE_QUERY=sum(rate(http_server_errors_total{service="{service}"}[5m])) / clamp_min(sum(rate(http_server_requests_total{service="{service}"}[5m])), 1)
PROMETHEUS_LATENCY_P95_MS_QUERY=histogram_quantile(0.95, sum(rate(http_server_request_duration_seconds_bucket{service="{service}"}[5m])) by (le)) * 1000
PROMETHEUS_RPS_QUERY=sum(rate(http_server_requests_total{service="{service}"}[5m]))

# PagerDuty settings (used when ALERTS_PROVIDER=pagerduty)
PAGERDUTY_API_TOKEN=<pagerduty-rest-api-token>
PAGERDUTY_BASE_URL=https://api.pagerduty.com
PAGERDUTY_HTTP_TIMEOUT_SECONDS=10

# Opsgenie settings (used when ALERTS_PROVIDER=opsgenie)
OPSGENIE_API_KEY=<opsgenie-api-key>
OPSGENIE_BASE_URL=https://api.opsgenie.com
OPSGENIE_HTTP_TIMEOUT_SECONDS=10

# ELK/OpenSearch settings (used when LOGS_PROVIDER=elk)
ELASTICSEARCH_BASE_URL=http://localhost:9200
ELASTICSEARCH_LOG_INDEX=logs-*
ELASTICSEARCH_TIMESTAMP_FIELD=@timestamp
ELASTICSEARCH_SERVICE_FIELD=service.name
ELASTICSEARCH_MESSAGE_FIELDS=message,log.original,event.original
ELASTICSEARCH_API_KEY=<optional-api-key>
ELASTICSEARCH_USERNAME=<optional-basic-auth-username>
ELASTICSEARCH_PASSWORD=<optional-basic-auth-password>
ELASTICSEARCH_HTTP_TIMEOUT_SECONDS=10

# X-Ray settings (used when TRACES_PROVIDER=xray)
# Requires optional extra: pip install "incident-triage-mcp[aws]"
# Auth can come from env credentials below or IAM role/default AWS credential chain.
XRAY_REGION=us-east-1
AWS_ACCESS_KEY_ID=<optional-static-key>
AWS_SECRET_ACCESS_KEY=<optional-static-secret>

# Secrets loader
SECRET_PROVIDER=env|secret-manager
```

---

## Deployment profiles (`local`, `staging`, `prod`)

Use profile templates from `deploy/profiles/`:

```bash
cp deploy/profiles/local.env.example .env.local
cp deploy/profiles/staging.env.example .env.staging
cp deploy/profiles/prod.env.example .env.prod
```

Run with a profile env file:

```bash
# Docker Compose
docker compose --env-file .env.local up --build

# Direct
set -a; source .env.staging; set +a
incident-triage-mcp
```

Smoke-check all three profile templates locally:

```bash
./scripts/smoke_profiles.sh
```

Profile guardrails enforced by config:

| Profile | Guardrails |
|---|---|
| `local` | Mock providers and file idempotency are allowed for fast dev loops. |
| `staging` | If `MCP_TRANSPORT=streamable-http`, auth cannot be `none`; provider-specific env vars are validated. |
| `prod` | `AUDIT_MODE=stdout`; alerts/metrics providers cannot be `mock`; evidence backend cannot be `none`; idempotency backend must be `redis` or `postgres`. |

Adapter env matrix (validated when selected in `staging`/`prod`):

| Provider | Required env vars |
|---|---|
| `datadog` | `DATADOG_API_KEY`, `DATADOG_APP_KEY` |
| `prometheus` | `PROMETHEUS_BASE_URL` |
| `pagerduty` | `PAGERDUTY_API_TOKEN` |
| `opsgenie` | `OPSGENIE_API_KEY` |
| `elk` | `ELASTICSEARCH_BASE_URL` |
| `cloudwatch` | Uses AWS auth chain (or `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`) |
| `xray` | Uses AWS auth chain (or `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`) |

Ticket provider env matrix (validated when selected in `staging`/`prod`):

| Provider (`JIRA_PROVIDER`) | Required env vars |
|---|---|
| `cloud` | `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN` |
| `servicenow` | `SERVICENOW_BASE_URL`, `SERVICENOW_USERNAME`, `SERVICENOW_PASSWORD` |

---

## Prod Mode (deployment checklist)

Use `DEPLOYMENT_PROFILE=prod` with `deploy/profiles/prod.env.example` as your baseline.

1) Prepare production env file

```bash
cp deploy/profiles/prod.env.example .env.prod
# fill real secrets/hosts (no placeholders)
```

2) Start with strict prod guardrails enabled

```bash
set -a; source .env.prod; set +a
incident-triage-mcp
```

The process will fail fast if prod requirements are not met (for example mock alerts/metrics providers, missing durable idempotency backend, or missing HTTP auth config for streamable HTTP).

3) Verify service telemetry and posture from your MCP client

- `mcp_health()`
- `mcp_metrics()`
- `jira_create_ticket(incident_id="INC-123", dry_run=true)` (safe action smoke check)

4) Rollout recommendation

- Deploy to staging first with the same providers/secrets model.
- Keep `dry_run=true` for mutating tools in initial production canaries.
- Alert on `mcp_metrics().totals.adapter_errors_total` and `mcp_metrics().totals.auth_denied_total`.

---

## Adapter onboarding (<30 min)

Use this path to add a new provider with minimal risk.

1) Implement adapter class

- Create `src/incident_triage_mcp/adapters/<provider>_real.py`.
- Implement the contract methods you need (`fetch_active_alerts`, `health_snapshot`, optional `fetch_logs`, `fetch_traces`).

2) Register provider

- Wire it in `src/incident_triage_mcp/adapters/registry.py` inside `_register_builtin_providers()`.

3) Add provider flag support

- Add provider name to allowed sets in `src/incident_triage_mcp/config.py` (`ALERTS_PROVIDER`, `METRICS_PROVIDER`, etc.).
- Add required env validation for `staging`/`prod` profile if the provider needs secrets/URLs.

4) Add tests

- Contract tests at registry level (`tests/test_adapter_scaffold.py` style).
- Provider-specific unit tests with fake HTTP/AWS clients.
- Tool-path tests in `tests/test_server_tools.py` for success + failure normalization.

5) Document env vars + usage

- Add env vars to `README.md` “Key environment variables”.
- If provider needs optional SDKs, add/update `pyproject.toml` extras and install instructions.
- Add one demo call in “Demo flow (agent/host)” if relevant.

Minimal skeleton:

```python
class NewProviderAPI:
    def __init__(self, secrets):
        self.api_key = secrets.get("NEW_PROVIDER_API_KEY", required=True)

    def fetch_active_alerts(self, services, since_minutes, max_alerts):
        ...

    def health_snapshot(self, service, start_iso, end_iso):
        ...
```

Definition of done:

- Provider selectable via env only (no code changes for users).
- Missing/invalid provider config fails clearly at startup in `staging`/`prod`.
- Tests pass and `mcp_health()` / `mcp_metrics()` still report expected values.

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

Deployment profile smoke checks:

```bash
./scripts/smoke_profiles.sh
```

---

## Automated Releases

This repo supports automated tag-based release publishing for both PyPI and GHCR.

Release workflow:
- Trigger: push a Git tag like `v0.2.0`
- Publishes:
  - Python package to PyPI
  - Docker image to `ghcr.io/<owner>/incident-triage-mcp`
  - GitHub Release with generated notes

Required repository secret:
- `PYPI_API_TOKEN` (PyPI API token with publish permission)

Release command:

```bash
# 1) bump version in pyproject.toml first, then:
git tag v0.2.0
git push origin v0.2.0
```

Notes:
- The workflow validates that tag `vX.Y.Z` matches `project.version` in `pyproject.toml`.
- GHCR publish uses the built-in `GITHUB_TOKEN`.

---

## MCP Registry Listing

This repo includes official MCP Registry metadata in `server.json`.

Validation/publish commands:

```bash
# Install mcp-publisher (example: macOS arm64)
curl -LsSf https://github.com/modelcontextprotocol/registry/releases/latest/download/mcp-publisher_darwin_arm64.tar.gz -o /tmp/mcp-publisher.tgz
tar -xzf /tmp/mcp-publisher.tgz -C /tmp
sudo mv /tmp/mcp-publisher /usr/local/bin/mcp-publisher

# Validate + publish
mcp-publisher validate server.json
mcp-publisher login github
mcp-publisher publish
```

Notes:
- Server name is `io.github.felixkwasisarpong/incident-triage-mcp`.
- PyPI verification marker is embedded in this README (`mcp-name: ...`).
- OCI verification is provided via Docker image label (`io.modelcontextprotocol.server.name`).
- Use the matching binary asset for your OS/arch from:
  `https://github.com/modelcontextprotocol/registry/releases/latest`

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

0) Check MCP service health/metrics:
   - `mcp_health()`
   - `mcp_metrics()`
   - HTTP checks (streamable-http): `GET /healthz`, `GET /metrics`
1) Trigger evidence collection:
   - `airflow_trigger_incident_dag(incident_id="INC-123", service="payments-api")`
2) Wait for the Evidence Bundle:
   - `evidence_wait_for_bundle(incident_id="INC-123", timeout_seconds=90, poll_seconds=2)`
3) Generate a deterministic triage summary (no LLM required):
   - `incident_triage_summary(incident_id="INC-123")`
3.5) Optional log pull for the same window:
   - `logs_fetch_recent(service="payments-api", start_iso="2026-01-01T00:00:00Z", end_iso="2026-01-01T00:30:00Z", limit=50)`
3.6) Optional trace pull for the same window:
   - `traces_fetch_recent(service="payments-api", start_iso="2026-01-01T00:00:00Z", end_iso="2026-01-01T00:30:00Z", limit=25)`
4) Optional one-call orchestration (safe ticket dry-run hook):
   - `incident_triage_run(incident_id="INC-123", service="payments-api", include_ticket=true)`
   - Override project key for the ticket hook: `incident_triage_run(incident_id="INC-123", service="payments-api", include_ticket=true, project_key="PAY")`
5) Optional notification hook (safe dry-run by default):
   - Provider-agnostic notify tool: `notify_post_update(incident_id="INC-123", service="payments-api", provider="slack")`
   - Teams via generic tool: `notify_post_update(incident_id="INC-123", service="payments-api", provider="teams", channel="Incident Triage", dry_run=false)`
   - `incident_triage_run(incident_id="INC-123", service="payments-api", notify_slack=true)`
   - Slack live send: `incident_triage_run(incident_id="INC-123", service="payments-api", notify_slack=true, notify_provider="slack", slack_channel="#incident-triage", slack_dry_run=false)`
   - Teams live send: `incident_triage_run(incident_id="INC-123", service="payments-api", notify_slack=true, notify_provider="teams", slack_channel="Incident Triage", slack_dry_run=false)`

---

## Jira ticketing demo

0) Validate ticket provider credentials (`cloud` or `servicenow`):
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
- Non-dry-run `jira_create_ticket` also requires `idempotency_key` (prevents duplicate tickets on retries).
- Approval tokens support single and rotated forms:
  - `CONFIRM_TOKEN` (legacy single token)
  - `CONFIRM_TOKENS` (comma-separated tokens)
  - `CONFIRM_TOKEN_SHA256` / `CONFIRM_TOKENS_SHA256` (sha256 digests instead of plaintext)
- Non-dry-run Slack posts are RBAC-gated (`slack.post_update`, allowed for `MCP_ROLE=responder|admin`).
- Non-dry-run Teams posts are RBAC-gated (`teams.post_update`, allowed for `MCP_ROLE=responder|admin`).
- Swap providers via env: `JIRA_PROVIDER=mock` (demo), `JIRA_PROVIDER=cloud` (real Jira Cloud), or `JIRA_PROVIDER=servicenow` (real ServiceNow).
- `JIRA_ISSUE_TYPE` defaults to `Task` (used for creates unless overridden in code).
- Jira Cloud descriptions are sent as ADF and render section headers/bullets/inline formatting in the Jira UI.
- ServiceNow creates records in `/api/now/table/incident` by default (override with `SERVICENOW_TABLE`).
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
- ✅ Deployment profiles (`local`/`staging`/`prod`) with guardrails and env templates
- ✅ Built-in MCP observability tools (`mcp_health`, `mcp_metrics`)
- Add a Helm chart + GitHub Actions to build/push multi-arch Docker images
- Expand **RBAC + safe actions** with preconditions and approval tokens
- Add richer **tracing** for MCP internals (OpenTelemetry/OTLP export)

---

## Contributing

PRs welcome. If you add an integration, prefer this pattern:

- define a provider contract (interface)
- implement `mock` + `real`
- select via env vars (no code changes for users)

---

## License

MIT
