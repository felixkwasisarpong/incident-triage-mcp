# Incident Triage MCP

<!-- mcp-name: io.github.felixkwasisarpong/incident-triage-mcp -->

![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)
![MCP](https://img.shields.io/badge/MCP-compatible-brightgreen)
![Transport](https://img.shields.io/badge/transport-stdio%20%7C%20streamable--http-blueviolet)
![Docker](https://img.shields.io/badge/docker-ready-2496ED?logo=docker&logoColor=white)
![Kubernetes](https://img.shields.io/badge/kubernetes-ready-326CE5?logo=kubernetes&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

Incident Triage MCP is a Model Context Protocol (MCP) server for incident triage. It provides safe, auditable tools for evidence retrieval, deterministic summaries, ticket workflows, and notifications.

## What This Project Is

- MCP control plane for incident triage tools.
- Compatible with local (`stdio`) and networked (`streamable-http`) MCP clients.
- Designed for standalone mode, Docker Compose, and Kubernetes.

## What This Project Is Not

- Not a standalone LLM agent platform.
- Not a provider credentials vault.
- Not a replacement for your evidence pipeline; it consumes normalized evidence bundles.

## Architecture Snapshot

- MCP server stays thin and policy-focused.
- Evidence collection runs in Airflow (optional) and writes EvidenceBundle artifacts.
- Agents call MCP tools only.
- Contract stability is defined under `spec/`.

For full details, see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Core Tools

| Tool | Purpose | Mutating |
|---|---|---|
| `evidence_get_bundle` | Fetch normalized EvidenceBundle for an incident | No |
| `evidence_wait_for_bundle` | Poll until bundle is available | No |
| `incident_triage_summary` | Build deterministic triage summary from bundle | No |
| `jira_draft_ticket` | Build non-mutating ticket draft | No |
| `jira_create_ticket` | Create ticket with safety gates | Yes |

Mutating actions are guarded by RBAC, `dry_run`, `confirm_token`, audit logging, and idempotency.

## Provider Matrix

| Area | Supported providers |
|---|---|
| Alerts | `mock`, `datadog`, `cloudwatch`, `prometheus`, `pagerduty`, `opsgenie` |
| Metrics | `mock`, `datadog`, `cloudwatch`, `prometheus` |
| Logs | `mock`, `datadog`, `cloudwatch`, `elk`, `none` |
| Traces | `mock`, `datadog`, `cloudwatch`, `xray`, `otel`, `none` |
| Ticketing (`JIRA_PROVIDER`) | `mock`, `cloud`, `servicenow` |
| Notify (`NOTIFY_PROVIDER`) | `slack`, `teams` |

## Quick Start

### Local (stdio)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .

MCP_TRANSPORT=stdio \
WORKFLOW_BACKEND=none \
EVIDENCE_BACKEND=fs \
EVIDENCE_DIR=./evidence \
incident-triage-mcp
```

### Local agent run (single incident)

```bash
incident-triage-agent \
  --incident-id INC-123 \
  --service payments-api \
  --artifact-store fs \
  --artifact-dir ./evidence \
  --compact
```

### Docker (streamable-http)

```bash
docker run --rm -p 3333:3333 \
  -e MCP_TRANSPORT=streamable-http \
  -e WORKFLOW_BACKEND=none \
  -e EVIDENCE_BACKEND=fs \
  ghcr.io/felixkwasisarpong/incident-triage-mcp:latest
```

Optional local stack (Airflow + Postgres + MinIO + MCP):

```bash
docker compose up --build
```

## Kubernetes: One Agent Job Per Trigger

This is the recommended runtime pattern:

1. Incoming trigger (webhook/manual) arrives.
2. Dispatcher (or operator) creates one Kubernetes `Job` per incident.
3. Job runs `incident-triage-agent` once and exits.
4. Agent calls MCP tools over HTTP.
5. MCP optionally triggers Airflow DAG (`incident_evidence_v1`) and consumes bundle from `fs`/`s3`.

### Deploy MCP server (Helm)

```bash
helm upgrade --install incident-triage-mcp ./charts/incident-triage-mcp \
  --namespace incident-triage --create-namespace \
  --set image.repository=ghcr.io/felixkwasisarpong/incident-triage-mcp \
  --set image.tag=0.2.8 \
  --set env.MCP_TRANSPORT=streamable-http \
  --set env.MCP_HTTP_AUTH_MODE=api_key \
  --set secretEnv.MCP_HTTP_API_KEY=change-me
```

### Trigger one incident with a single-run agent Job

```bash
kubectl -n incident-triage create job triage-inc-123 \
  --image=ghcr.io/felixkwasisarpong/incident-triage-mcp:0.2.8 \
  -- incident-triage-agent \
  --incident-id INC-123 \
  --service payments-api \
  --mcp-url http://incident-triage-mcp/mcp \
  --mcp-api-key change-me \
  --compact
```

### Ensure single-run behavior

- Use deterministic job names per incident (`triage-inc-<incident_id>`).
- Reject duplicates at dispatcher level if job already exists.
- Keep ticket creates idempotent with `idempotency_key`.
- Configure Job lifecycle controls (`backoffLimit`, `activeDeadlineSeconds`, `ttlSecondsAfterFinished`).

## Configuration Essentials

| Variable | Meaning |
|---|---|
| `MCP_TRANSPORT` | `stdio` or `streamable-http` |
| `WORKFLOW_BACKEND` | `none` or `airflow` |
| `EVIDENCE_BACKEND` | `none`, `fs`, `s3`, `airflow` |
| `EVIDENCE_DIR` | Local bundle directory when using `fs` |
| `AIRFLOW_BASE_URL` | Required for Airflow trigger/read tools |
| `MCP_HTTP_AUTH_MODE` | `none`, `api_key`, `jwt_hs256` |
| `AUDIT_MODE` | `stdout` (recommended in k8s) or `file` |
| `DEPLOYMENT_PROFILE` | `local`, `staging`, `prod` |

Profile templates live in `deploy/profiles/`:

- `local.env.example`
- `staging.env.example`
- `prod.env.example`

## Testing

Run full tests:

```bash
pytest -q
```

Run contract checks only:

```bash
pytest -q tests/test_contract_evidence_bundle.py tests/test_contract_mcp_tools.py
python scripts/validate_contrib.py
```

## Releases

### Install from PyPI

```bash
pip install incident-triage-mcp==X.Y.Z
```

### Pull container image

```bash
docker pull ghcr.io/felixkwasisarpong/incident-triage-mcp:X.Y.Z
```

Supported image tags:

- `X.Y.Z` (exact)
- `X.Y` (minor stream)
- `latest`

For release workflow details, see [docs/RELEASING.md](docs/RELEASING.md).

## Project Layout

```text
incident-triage-mcp/
  src/incident_triage_mcp/      # MCP server + tools + adapters
  spec/                         # versioned contracts
  airflow/dags/                 # evidence pipeline
  charts/incident-triage-mcp/   # Helm chart
  k8s/                          # Kubernetes manifests
  contrib/                      # polyglot contribution area
  docs/                         # architecture, release, governance docs
```

## Support And Triage

- Discussions: https://github.com/felixkwasisarpong/incident-triage-mcp/discussions
- Issues: https://github.com/felixkwasisarpong/incident-triage-mcp/issues
- Security reports: [SECURITY.md](SECURITY.md)

## Documentation Index

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- [docs/CONTRIBUTION_GUIDE.md](docs/CONTRIBUTION_GUIDE.md)
- [docs/REPO_LAYOUT.md](docs/REPO_LAYOUT.md)
- [docs/VERSIONING.md](docs/VERSIONING.md)
- [docs/RELEASING.md](docs/RELEASING.md)
- [docs/MAINTAINERS_RUNBOOK.md](docs/MAINTAINERS_RUNBOOK.md)

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a PR.

## License

MIT
