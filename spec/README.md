# Contract Specs

This directory contains versioned, language-agnostic interface contracts for `incident-triage-mcp`.

## Files

- `evidence-bundle.v1.schema.json`: JSON Schema for canonical `EvidenceBundle v1` artifacts.
- `mcp-tools.v1.json`: high-level MCP tool contract for core triage/ticket tools.

## Compatibility Rules

- `v1` contracts are stable and backward-compatible.
- Within `v1`, additive fields are allowed.
- Required fields and required tool names in `v1` must not be removed or renamed.
- Implementations in any language must continue to accept valid `v1` artifacts.

## Versioning Rules

When introducing a new major contract version:

1. Add new files (for example, `evidence-bundle.v2.schema.json`, `mcp-tools.v2.json`).
2. Keep `v1` files unchanged for existing integrations.
3. Add examples and tests for the new version.
4. Document migration guidance before removing old-version support.
