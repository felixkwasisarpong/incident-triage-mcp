# Security Policy

## Supported Versions

We currently provide security fixes for:

| Version | Supported |
| --- | --- |
| `main` (latest commit) | :white_check_mark: |
| Latest `0.2.x` release | :white_check_mark: |
| Older releases | :x: |

## Reporting a Vulnerability

Do not open public issues for security reports.

Report privately using one of these channels:

1. GitHub Security Advisories for this repository: `Security` tab -> `Report a vulnerability`
2. Direct maintainer contact on GitHub: [@felixkwasisarpong](https://github.com/felixkwasisarpong)

Please include:
- Affected version, commit SHA, or deployment profile
- Reproduction steps or proof of concept
- Expected impact and severity
- Any known mitigations

## Response Targets

- Acknowledge report: within 3 business days
- Initial triage: within 7 business days
- Ongoing updates: at least weekly until closure

## Scope

In scope:
- Authn/authz bypasses in MCP HTTP mode
- Bypasses of mutation safety controls (`dry_run`, `confirm_token`, audit, idempotency)
- Privilege escalation, data exposure, and code execution bugs in this repository
- Dependency vulnerabilities with a realistic exploit path for `incident-triage-mcp`

Out of scope:
- Public test/demo credentials or local-only misconfiguration
- Vulnerabilities in third-party platforms without a project-specific exploit path
- Reports without actionable reproduction details

## Disclosure Policy

After a fix is available, maintainers will:
- Publish a security advisory or release note
- Credit reporters if requested
- Document upgrade or mitigation steps
