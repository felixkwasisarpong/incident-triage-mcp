from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER_NAME = "io.github.felixkwasisarpong/incident-triage-mcp"


def _project_version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'(?m)^version\s*=\s*"([^"]+)"', text)
    if not match:
        raise AssertionError("Could not read project version from pyproject.toml")
    return match.group(1)


class TestRegistryMetadata(unittest.TestCase):
    def test_server_json_matches_project_version(self) -> None:
        data = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))
        version = _project_version()

        self.assertEqual(data["name"], SERVER_NAME)
        self.assertEqual(data["version"], version)
        self.assertEqual(data["repository"]["source"], "github")

        packages = data.get("packages", [])
        self.assertGreaterEqual(len(packages), 2)

        pypi_pkg = next((p for p in packages if p.get("registryType") == "pypi"), None)
        self.assertIsNotNone(pypi_pkg)
        self.assertEqual(pypi_pkg["identifier"], "incident-triage-mcp")
        self.assertEqual(pypi_pkg["version"], version)
        self.assertEqual(pypi_pkg["transport"]["type"], "stdio")

        oci_pkg = next((p for p in packages if p.get("registryType") == "oci"), None)
        self.assertIsNotNone(oci_pkg)
        self.assertIn(f":{version}", oci_pkg["identifier"])
        self.assertEqual(oci_pkg["transport"]["type"], "stdio")

    def test_readme_and_docker_include_registry_verification_markers(self) -> None:
        readme_text = (ROOT / "README.md").read_text(encoding="utf-8")
        dockerfile_text = (ROOT / "Dockerfile").read_text(encoding="utf-8")

        self.assertIn(f"mcp-name: {SERVER_NAME}", readme_text)
        self.assertIn(f'io.modelcontextprotocol.server.name="{SERVER_NAME}"', dockerfile_text)


if __name__ == "__main__":
    unittest.main()
