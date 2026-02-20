from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TestPackagingEntrypoints(unittest.TestCase):
    def test_pyproject_declares_console_scripts(self) -> None:
        pyproject_text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        scripts_block_match = re.search(
            r"^\[project\.scripts\]\n(?P<body>(?:.+\n)+?)(?:\n\[|\Z)",
            pyproject_text,
            flags=re.MULTILINE,
        )
        self.assertIsNotNone(scripts_block_match, "Missing [project.scripts] section in pyproject.toml")

        scripts_body = scripts_block_match.group("body")
        self.assertIn('incident-triage-mcp = "incident_triage_mcp.server:main"', scripts_body)
        self.assertIn('incident-triage-agent = "incident_triage_mcp.agents.langgraph_agent:main"', scripts_body)

    def test_dockerfile_uses_packaged_entrypoint_wrapper(self) -> None:
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

        self.assertIn("COPY scripts/docker-entrypoint.sh /usr/local/bin/incident-triage-entrypoint", dockerfile)
        self.assertIn('ENTRYPOINT ["incident-triage-entrypoint"]', dockerfile)
        self.assertIn("incident-triage-mcp", (ROOT / "scripts" / "docker-entrypoint.sh").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
