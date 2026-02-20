# AGENTS.md — Incident Triage MCP contributor guide

## Goals
- Ship a **standalone MCP server** that runs without Apache Airflow.
- Keep Airflow/workflow integrations **optional** and behind config flags.
- Provide safe, auditable incident triage tools suitable for LLM hosts (Claude Desktop, etc).

## Non-negotiables
- MCP must boot with only:
  - `MCP_TRANSPORT=stdio`
  - `RUNBOOKS_DIR=./runbooks` (optional but recommended)
- Airflow is **never required** for standalone mode.
- Airflow tools must be **registered only** when `EVIDENCE_BACKEND=airflow` and required env vars exist.

## Key config
- `EVIDENCE_BACKEND=none|fs|s3|airflow` (default: fs or none)
- `EVIDENCE_DIR=./evidence` (used when backend=fs)
- `AUDIT_MODE=stdout|file` (default: stdout)

## Local dev
```bash
uv venv && uv pip install -e .
MCP_TRANSPORT=stdio EVIDENCE_BACKEND=fs EVIDENCE_DIR=./evidence RUNBOOKS_DIR=./runbooks \
  python -m incident_triage_mcp.server