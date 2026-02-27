# Polyglot Contributions (contrib/)

Polyglot contributions are welcome.

This folder is the landing zone for components implemented in other languages (Go/TypeScript/Rust/etc.) without changing the current Python MCP server packaging.

## Contract Requirements

All implementations in `contrib/` MUST conform to repository contracts in `spec/`:

- Evidence artifact contract:
  - `spec/evidence-bundle.v1.schema.json`
- MCP tool compatibility contract (when applicable):
  - `spec/mcp-tools.v1.json`

If your contribution changes contract behavior, open an RFC first under `rfcs/`.

## Suggested Component Boundaries

- Dispatcher:
  - webhook/event ingest and Kubernetes Job creation/orchestration hooks
- Agent host:
  - LangGraph or other orchestration/runtime host that calls MCP tools
- Evidence SDK/providers:
  - provider adapters and normalization logic used by Airflow/evidence plane

Keep MCP server responsibilities thin and contract-focused.

## Local Contract Validation

From repo root:

```bash
# Validate contract tests
pytest -q tests/test_contract_evidence_bundle.py tests/test_contract_mcp_tools.py

# Optional: run full project tests
pytest -q
```

For non-Python implementations, ensure your generated artifacts are validated against:
- `spec/evidence-bundle.v1.schema.json`
- `spec/mcp-tools.v1.json` (if your component exposes or depends on tool shapes)

## Security Note

Do not add provider credentials, API keys, or tokens in this directory.
Use environment variables and secret managers outside the repository.
