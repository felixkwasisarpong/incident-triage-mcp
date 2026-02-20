from __future__ import annotations

import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TestPackagingEntrypoints(unittest.TestCase):
    def test_pyproject_declares_console_scripts(self) -> None:
        pyproject = ROOT / "pyproject.toml"
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        scripts = data.get("project", {}).get("scripts", {})

        self.assertEqual(scripts.get("incident-triage-mcp"), "incident_triage_mcp.server:main")
        self.assertEqual(scripts.get("incident-triage-agent"), "incident_triage_mcp.agents.langgraph_agent:main")

    def test_dockerfile_uses_packaged_entrypoint_wrapper(self) -> None:
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

        self.assertIn("COPY scripts/docker-entrypoint.sh /usr/local/bin/incident-triage-entrypoint", dockerfile)
        self.assertIn('ENTRYPOINT ["incident-triage-entrypoint"]', dockerfile)
        self.assertIn("incident-triage-mcp", (ROOT / "scripts" / "docker-entrypoint.sh").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
