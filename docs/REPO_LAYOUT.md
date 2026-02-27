# Platform Repository Layout Plan

This document defines the target platform layout for future scaling. It is a planning guide only; files are not being moved yet.

## Target Structure

```text
incident-triage-mcp/
  spec/                       # Shared versioned contracts
  rfcs/                       # Architecture and compatibility proposals
  packages/
    mcp-server-python/        # incident-triage-mcp MCP server
    agent-langgraph/          # incident-triage-agent logic
    evidence-sdk/             # Provider adapters used by Airflow/evidence plane
    dispatcher/               # Webhook/event ingest and routing
    airflow-dags/             # incident_evidence_v1 and related DAGs
  contrib/                    # Polyglot component contributions (no package moves required)
  examples/                   # Sample artifacts and integration examples
  docs/                       # Architecture, governance, release, runbooks
  .github/                    # CI/CD and repo automation
```

## Boundary Guidance

- Keep MCP server thin (control plane, policies, contract enforcement).
- Prefer provider adapters in Airflow/evidence SDK (evidence plane).
- Dispatcher should focus on ingest/routing, not contract ownership.
- Contracts in `spec/` are the interoperability source of truth.

## Polyglot Contributions

Any language/runtime is acceptable if changes:
- Conform to `spec/` contracts.
- Preserve compatibility guarantees.
- Pass contract tests and CI checks.
- Include migration notes when introducing versioned changes.
