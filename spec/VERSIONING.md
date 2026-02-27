# Spec Versioning and Compatibility

This project maintains versioned contracts under `spec/`.

## EvidenceBundle `v1`

- `spec/evidence-bundle.v1.schema.json` is stable.
- Changes to `v1` must remain backward compatible.
- Within `v1`, additive fields are allowed.
- Removing/renaming required fields in `v1` is not allowed.

## Introducing EvidenceBundle `v2`

To introduce a new major contract version:

1. Add a new schema file (for example `spec/evidence-bundle.v2.schema.json`).
2. Keep `v1` available during a dual-read compatibility period.
3. Add/update migration tooling and examples for `v1 -> v2`.
4. Add contract tests for both versions until `v1` is retired.
5. Publish migration notes in docs and release notes.

## MCP Tool Schema Versioning

- `spec/mcp-tools.v1.json` defines high-level tool compatibility commitments.
- Tool contract changes that break existing consumers require a new major spec version (for example `mcp-tools.v2.json`).
- Additive non-breaking fields may be added within the same major version.

## Deprecation Policy

- Deprecations must be documented before removal.
- Minimum deprecation window: 90 days or two minor releases, whichever is longer.
- Deprecated fields/contracts should include migration guidance and target removal release.
