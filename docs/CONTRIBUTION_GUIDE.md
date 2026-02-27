# Contribution Guide (Quickstart)

This is the fastest path to your first PR in `incident-triage-mcp`.

## 1) Set Up Locally

```bash
git clone https://github.com/felixkwasisarpong/incident-triage-mcp.git
cd incident-triage-mcp
python -m venv .venv
source .venv/bin/activate
pip install -e .
pip install pytest
```

## 2) Pick a Small Change

Good first PR options:
- Clarify docs or examples
- Add missing tests
- Fix a small bug with a focused patch

## 3) Validate

```bash
pytest -q
```

If behavior changed, add tests and docs in the same PR.

## 4) Open a Pull Request

- Use `.github/PULL_REQUEST_TEMPLATE.md`
- Keep scope focused
- Link related issue(s)
- Note AI assistance if used

## 5) Follow Project Rules

- Read [CONTRIBUTING.md](../CONTRIBUTING.md)
- Follow [CODE_OF_CONDUCT.md](../CODE_OF_CONDUCT.md)
- For vulnerabilities, use [SECURITY.md](../SECURITY.md)

## 6) Need Help?

Use GitHub Discussions:
- https://github.com/felixkwasisarpong/incident-triage-mcp/discussions
