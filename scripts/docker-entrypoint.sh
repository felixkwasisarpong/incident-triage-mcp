#!/usr/bin/env sh
set -eu

# If a command is provided, run it inside the project environment.
if [ "$#" -gt 0 ]; then
  exec uv run --project /app "$@"
fi

# Default container behavior: run MCP server via pip console script.
exec uv run --project /app incident-triage-mcp
