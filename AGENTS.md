# AI-Assisted Contribution Rules

This file defines repository policy for AI-assisted contributions in `incident-triage-mcp`.

## Principles

- Human maintainers are accountable for all merged changes.
- AI can draft code, docs, and tests, but humans review and validate final behavior.
- Keep changes small, traceable, and reproducible.

## Required for AI-Assisted PRs

- State where AI was used (drafting, refactoring, tests, docs).
- Add or update tests for behavior changes.
- Update docs for interface or workflow changes.
- Ensure generated code does not introduce secrets or sensitive incident data.

## Safety Requirements for Mutating Tools

AI-generated changes must not weaken mutation guardrails. Keep all of the following:
- Safe `dry_run` path
- `confirm_token` requirement for non-dry-run execution
- Audit logging for mutation attempts
- Idempotency protections where applicable
- RBAC checks for privileged actions

## Interface and Spec Stability

- Do not break `EvidenceBundle v1` contract shape or semantics.
- Do not introduce breaking MCP tool schema changes without a migration plan.
- Prefer implementing provider adapters in Airflow (evidence plane) rather than MCP, unless a direct MCP integration is clearly justified.

## Prohibited

- Auto-merging AI-generated output without human review
- Removing guardrails to make demos easier
- Fabricating test results, benchmarks, or incident evidence
