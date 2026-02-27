# Architecture

`incident-triage-mcp` uses a split-plane design:

- MCP thin control plane
- Airflow evidence plane
- Agents/hosts call MCP only

## High-Level Flow

1. Agent/host invokes MCP tools.
2. MCP validates input and policy (RBAC + safety gates).
3. MCP reads or triggers evidence workflows through configured backends.
4. Airflow (or evidence backend) produces/serves `EvidenceBundle v1` artifacts.
5. MCP returns normalized outputs and records audit events for sensitive actions.

## Plane Responsibilities

### MCP Thin Control Plane

- Stable MCP tool interfaces
- Request validation and normalization
- Policy enforcement (`dry_run`, `confirm_token`, RBAC, idempotency)
- Audit logging
- Minimal provider-specific logic

### Airflow Evidence Plane

- Provider-specific evidence collection/orchestration
- Evidence normalization into `EvidenceBundle v1`
- Workflow retries/scheduling and artifact production
- Integration adapters for external systems (preferred extension point)

## Contract Boundary

- `EvidenceBundle v1` is the interoperability contract between Airflow and MCP.
- MCP tools should remain backward compatible.
- Agents should not call provider APIs directly; they should call MCP tools.

## Contract Versioning

- `EvidenceBundle v1` is the canonical artifact shape and is defined in `spec/evidence-bundle.v1.schema.json`.
- Bundle-only mode keeps the agent surface focused on MCP bundle tools (`evidence_get_bundle`, `evidence_wait_for_bundle`, `incident_triage_summary`) instead of direct provider API calls.
- Contract files are versioned under `spec/` and examples live under `examples/evidence/`.

To introduce `EvidenceBundle v2`:

1. Add `spec/evidence-bundle.v2.schema.json` without modifying `v1`.
2. Add `spec/mcp-tools.v2.json` if tool contract semantics change.
3. Add passing/failing v2 examples and contract tests.
4. Document migration and compatibility expectations before deprecating older versions.

## Mutation Safety Model

Non-dry-run mutating actions must preserve all gates:
- RBAC authorization
- Explicit reason/context
- Valid `confirm_token`
- Audit event emission
- Idempotency controls where required

## Extension Guidance

- Prefer adding new provider adapters in Airflow instead of MCP.
- Add MCP-side provider logic only when direct MCP access is required and justified.
- Any contract-affecting change requires tests, docs, and maintainer approval.
