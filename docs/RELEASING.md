# Releasing

This project publishes:
- Python package: PyPI (`incident-triage-mcp`)
- Container images: GHCR (`ghcr.io/felixkwasisarpong/incident-triage-mcp`)
- Optional mirror: Docker Hub (when secrets are configured)

Release automation is driven by Git tags in the form `vX.Y.Z`.
`pyproject.toml` is the single source of truth for package versioning.

## 1) Prepare a release

1. Ensure `pyproject.toml` has the target `project.version`.
2. Update `CHANGELOG.md`:
   - Move relevant entries from `[Unreleased]` into `[X.Y.Z]`.
   - Add release date.
3. Run local checks:

```bash
pytest -q
ruff check src tests
```

## 2) Tag and push

```bash
git checkout main
git pull --ff-only
git tag vX.Y.Z
git push origin vX.Y.Z
```

Pushing a tag triggers `.github/workflows/release.yml`.

## 3) What the release workflow does

- Validates tag/version consistency (`vX.Y.Z` must match `pyproject.toml`).
- Builds Python sdist/wheel and publishes to PyPI:
  - Preferred: Trusted Publishing (PyPI OIDC).
  - Fallback: `PYPI_API_TOKEN` secret if present.
- Builds and pushes multi-arch Docker images (`linux/amd64`, `linux/arm64`) to GHCR.
- Optionally pushes the same tags to Docker Hub when both secrets are set:
  - `DOCKERHUB_USERNAME`
  - `DOCKERHUB_TOKEN`
- Emits supply-chain metadata:
  - BuildKit provenance attestation
  - SBOM attestation (`sbom: true`)
  - SPDX SBOM file attached to the GitHub Release

## 4) Create/verify GitHub Release

The workflow creates a GitHub Release automatically for the tag and uploads:
- Python artifacts (`dist/*`)
- Docker SBOM (`docker-image.sbom.spdx.json`)

Manual fallback:
1. Open `Releases` in GitHub.
2. Click `Draft a new release`.
3. Select tag `vX.Y.Z`, add notes from `CHANGELOG.md`, and publish.

After completion, verify:
1. PyPI version exists and can be installed.
2. GHCR image is available for `X.Y.Z`, `X.Y`, and `latest` tags.
3. Release notes and assets are present on GitHub.

## Optional: keyless signing

The workflow attempts keyless cosign signing via GitHub OIDC in non-blocking mode. If signing is unavailable, the release still succeeds.
