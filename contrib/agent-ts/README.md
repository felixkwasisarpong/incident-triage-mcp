# agent-ts (placeholder)

## Purpose

Experimental TypeScript contribution area for agent-host logic that calls MCP tools.

## Expected Inputs / Outputs

Inputs:
- incident context (incident_id, service)
- MCP endpoint/auth configuration

Outputs:
- MCP tool invocations and normalized decision output
- optional ticket/notification decisions (respecting safety controls)

## Hello World (placeholder)

```bash
# Example placeholder only
cd contrib/agent-ts
# npm init -y
# npm run start
```

## How to Test

- TODO: add agent-host integration tests against MCP tool contracts.
- Validate contract assumptions against `spec/mcp-tools.v1.json`.

## Secrets

Do not add provider credentials here; keep secrets out of the repo.
