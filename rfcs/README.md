# RFC Process

This directory tracks architecture and compatibility decisions that affect multiple contributors and components.

## When an RFC is required

Open an RFC before implementing changes that impact shared contracts or safety guarantees, including:
- Breaking or potentially breaking changes in `spec/` (for example `evidence-bundle.v1.schema.json`).
- Changes to MCP tool schema contracts (`spec/mcp-tools.v1.json`) or tool compatibility expectations.
- Changes to mutation safety/security model (`dry_run`, `confirm_token`, RBAC, audit, idempotency).
- Cross-component boundary changes (MCP server, agent, evidence SDK, dispatcher, Airflow DAGs).

An RFC is usually not required for:
- Typos and doc-only wording fixes.
- Internal refactors with no contract or behavior impact.
- Test-only changes that do not alter contracts.

## File naming

- New RFCs use `NNNN-short-title.md` (for example `0001-evidence-bundle-v2.md`).
- Use [0000-template.md](0000-template.md) as the starting point.

## Lifecycle

1. Proposal:
   - Open a PR adding the RFC in `rfcs/`.
   - Link the RFC from any implementation PR (`RFC: rfcs/NNNN-...`).
2. Discussion:
   - Maintainers and contributors review tradeoffs and migration plan.
3. Accepted (or Rejected/Superseded):
   - Update RFC status in the document header.
4. Implemented:
   - Link implementation PR(s), tests, and rollout details.

## Decision standard

RFCs should favor:
- Backward compatibility by default.
- Clear migration and deprecation timelines.
- Minimal risk to safety guardrails and interoperability.
