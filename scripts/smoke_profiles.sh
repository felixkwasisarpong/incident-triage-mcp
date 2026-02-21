#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

run_profile_smoke() {
  local profile="$1"
  local env_file="deploy/profiles/${profile}.env.example"

  if [[ ! -f "${env_file}" ]]; then
    echo "missing env file: ${env_file}" >&2
    return 1
  fi

  echo "==> smoke: ${profile} (${env_file})"
  (
    set -a
    # shellcheck source=/dev/null
    source "${env_file}"
    set +a

    uv run --project . python - <<'PY'
import os

from incident_triage_mcp.config import load_config

cfg = load_config()
expected = os.environ.get("DEPLOYMENT_PROFILE")
if cfg.deployment_profile != expected:
    raise SystemExit(f"profile mismatch: cfg={cfg.deployment_profile} env={expected}")

# Import server to ensure startup path is profile-safe.
import incident_triage_mcp.server as _server  # noqa: F401

print(
    f"ok profile={cfg.deployment_profile} transport={cfg.mcp_transport} "
    f"evidence_backend={cfg.evidence_backend}"
)
PY
  )
}

run_profile_smoke "local"
run_profile_smoke "staging"
run_profile_smoke "prod"

echo "profile smoke checks passed"
