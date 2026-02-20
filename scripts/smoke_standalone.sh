#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

INCIDENT_ID="${1:-INC-STANDALONE-001}"
SERVICE="${2:-payments-api}"

export MCP_TRANSPORT="${MCP_TRANSPORT:-stdio}"
export RUNBOOKS_DIR="${RUNBOOKS_DIR:-./runbooks}"
export EVIDENCE_BACKEND="${EVIDENCE_BACKEND:-fs}"
export EVIDENCE_DIR="${EVIDENCE_DIR:-./evidence}"
export INCIDENT_ID_ARG="${INCIDENT_ID}"
export SERVICE_ARG="${SERVICE}"

mkdir -p "${EVIDENCE_DIR}"

if command -v uv >/dev/null 2>&1; then
  PYTHON_CMD=(uv run --project . python)
else
  PYTHON_CMD=(python)
fi

"${PYTHON_CMD[@]}" - <<'PY'
from __future__ import annotations

import json
import os

from incident_triage_mcp import server

incident_id = os.environ.get("INCIDENT_ID_ARG", "INC-STANDALONE-001")
service = os.environ.get("SERVICE_ARG", "payments-api")

seed = server.evidence_seed_sample(incident_id=incident_id, service=service, window_minutes=30)
summary = server.incident_triage_summary(incident_id=incident_id)

if not seed.get("seeded"):
    raise SystemExit("seed failed")
if summary.get("incident_id") != incident_id:
    raise SystemExit("summary incident_id mismatch")

print(
    json.dumps(
        {
            "ok": True,
            "incident_id": incident_id,
            "service": service,
            "backend": summary.get("backend", "fs"),
            "headline": summary.get("headline"),
            "evidence_path": seed.get("path"),
        },
        ensure_ascii=False,
        indent=2,
    )
)
PY
