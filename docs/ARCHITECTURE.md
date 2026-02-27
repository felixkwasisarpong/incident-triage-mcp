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
