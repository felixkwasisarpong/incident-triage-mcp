# Contributing to incident-triage-mcp

Thanks for contributing. This guide is optimized for first-time contributors and small, reviewable pull requests.

## Quickstart (<10 minutes)

1. Fork and clone `incident-triage-mcp`.
2. Create a branch: `git checkout -b feat/short-name`.
3. Set up a local environment:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
pip install pytest
```

4. Run tests: `pytest -q`.
5. Make your change and add/update tests.
6. Open a PR using `.github/PULL_REQUEST_TEMPLATE.md`.

## Contribution Scope

Good first contributions:
- Documentation and examples
- Test coverage improvements
- Bug fixes
- Integration hardening that preserves public contracts

Open an issue before starting large features, architecture changes, or breaking changes.

## Development Expectations

- Keep MCP tool interfaces backward compatible unless a maintainer approves a migration plan.
- Preserve the `EvidenceBundle v1` contract.
- Do not weaken mutation guardrails:
  - `dry_run` safe path
  - `confirm_token` for non-dry-run execution
  - audit logging
  - idempotency where applicable
- Add or update tests for behavior changes.
- Update docs when behavior, configuration, or interfaces change.

## Polyglot Contributions Welcome

Contributions in any language/runtime are welcome when they fit this repository's boundaries.

Rules:
- Must not break the `EvidenceBundle v1` contract.
- Must not bypass MCP guardrails for mutations.
- Must include tests and docs.
- Prefer adding provider adapters in Airflow (not MCP) unless justified.

## Pull Request Process

- Keep PRs focused and avoid unrelated refactors.
- Link issues in the PR description (for example: `Closes #123`).
- Fill out the PR template completely.
- Ensure tests pass before requesting review.
- Be responsive to review feedback.

## Community Standards

- By participating, you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).
- Security issues must follow [SECURITY.md](SECURITY.md) and should not be reported publicly.
- Project roles and decisions are documented in [GOVERNANCE.md](GOVERNANCE.md) and [MAINTAINERS.md](MAINTAINERS.md).
