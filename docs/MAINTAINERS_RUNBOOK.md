# Maintainers Runbook

Lightweight operational checklist for repository maintainers.

## Issue Triage

1. Confirm reproduction details or missing context.
2. Apply labels by area (`area/*`), type (`kind/*`), and priority (`priority/*`).
3. Route to owners when needed (`CODEOWNERS` / reviewers).
4. Close duplicates with a link to the canonical issue.

## Label Meanings

- Area labels:
  - `area/mcp`, `area/airflow`, `area/agent`, `area/spec`, `area/infra`, `area/docs`
- Kind labels:
  - `kind/bug`, `kind/feature`, `kind/docs`, `kind/chore`
- Priority labels:
  - `priority/p0` to `priority/p3`

## Dependabot and Hygiene Automation

- Dependabot runs weekly for GitHub Actions, pip, and Docker.
- Path-based auto-labeling runs on pull requests.
- PR title check is warning-only and can be tightened later if desired.
- Stale workflow applies to issues only (not PRs) with a long inactivity window.

## Release Steps

Follow the release runbook in [RELEASING.md](RELEASING.md).

## Security Reports

Follow [SECURITY.md](../SECURITY.md) for private vulnerability handling and disclosure workflow.
