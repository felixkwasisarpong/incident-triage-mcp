# Versioning Strategy

## Package Versioning

Code packages use Semantic Versioning (`MAJOR.MINOR.PATCH`).

- PATCH: bug fixes and non-breaking maintenance changes.
- MINOR: backward-compatible features and additive capabilities.
- MAJOR: breaking API/behavior changes.

Current package version source of truth:
- `pyproject.toml` (`project.version`) for `incident-triage-mcp`.

## Spec Versioning

Spec versions are independent from code package versions.

- `spec/evidence-bundle.v1.schema.json`
- `spec/mcp-tools.v1.json`

Code releases reference supported spec versions, but spec major bumps do not require immediate package major bumps if compatibility is preserved via dual-read support.

## Release Tags

Releases are tagged as `vX.Y.Z`.

Examples:
- `v0.2.8`
- `v1.0.0`

## Cross-Component Compatibility

As the platform grows (MCP server, agent, evidence SDK, dispatcher, Airflow DAGs):
- Each component may have its own SemVer lifecycle.
- Shared compatibility boundary is enforced by contracts in `spec/`.
- Components in any language are supported if they honor spec contracts and pass contract tests.

## Compatibility Meaning

A release is considered compatible when:
- `EvidenceBundle v1` artifacts remain readable by supported MCP releases.
- MCP tool contracts in `mcp-tools.v1.json` remain valid for existing clients.
- Safety model guarantees remain intact unless an accepted RFC defines changes.
