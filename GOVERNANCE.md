# Governance

`incident-triage-mcp` uses a maintainer-led model with transparent decisions and lightweight process.

## Roles

### Contributor

- Opens issues and pull requests
- Improves code, docs, tests, or operations
- Follows repository policies and review feedback

### Maintainer

- Reviews and merges pull requests
- Triages issues and releases updates
- Protects interface stability and safety guardrails

### Lead Maintainer

- Final decision maker when consensus is unclear
- Appoints/removes maintainers
- Owns release and security escalation decisions

Current maintainers are listed in [MAINTAINERS.md](MAINTAINERS.md).

## Decision-Making

- Routine changes: lazy consensus through PR review
- Significant changes: discuss in issues/PRs before implementation
- Breaking changes (tool schemas, `EvidenceBundle v1`, or safety controls): require an approved migration plan and explicit maintainer approval before merge

When disagreement persists, the Lead Maintainer makes the final call with rationale documented in the PR/issue.

## Becoming a Maintainer

A contributor may be invited when they consistently demonstrate:
- High-quality contributions over time
- Reliable review and issue triage participation
- Good judgment on safety and compatibility
- Respectful collaboration

Process:
1. Nomination by a maintainer (issue or PR comment)
2. Public feedback period (minimum 7 days)
3. Lead Maintainer decision and update to [MAINTAINERS.md](MAINTAINERS.md)

## Maintainer Inactivity or Removal

Maintainers may be marked inactive after extended inactivity (typically 90+ days without review/triage activity). They can return to active status at any time by resuming participation.

Lead Maintainer may remove maintainer access for policy violations, security risk, or sustained unresponsiveness.
