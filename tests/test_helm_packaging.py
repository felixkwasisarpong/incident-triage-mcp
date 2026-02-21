from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))


class TestHelmPackaging(unittest.TestCase):
    def test_chart_scaffold_files_exist(self) -> None:
        chart_dir = ROOT / "charts" / "incident-triage-mcp"
        expected = [
            chart_dir / "Chart.yaml",
            chart_dir / "values.yaml",
            chart_dir / "templates" / "deployment.yaml",
            chart_dir / "templates" / "service.yaml",
            chart_dir / "templates" / "_helpers.tpl",
            chart_dir / "templates" / "secret-env.yaml",
        ]
        for path in expected:
            self.assertTrue(path.exists(), f"missing expected chart file: {path}")

    def test_chart_metadata_contains_name_and_version(self) -> None:
        content = (ROOT / "charts" / "incident-triage-mcp" / "Chart.yaml").read_text(encoding="utf-8")
        self.assertIn("name: incident-triage-mcp", content)
        self.assertIn("apiVersion: v2", content)
        self.assertIn("appVersion:", content)

    def test_values_has_required_runtime_keys(self) -> None:
        content = (ROOT / "charts" / "incident-triage-mcp" / "values.yaml").read_text(encoding="utf-8")
        self.assertIn("image:", content)
        self.assertIn("service:", content)
        self.assertIn("env:", content)
        self.assertIn("secretEnv:", content)


if __name__ == "__main__":
    unittest.main()
