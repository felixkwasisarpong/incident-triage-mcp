from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROFILE_DIR = ROOT / "deploy" / "profiles"


class TestDeploymentProfiles(unittest.TestCase):
    def test_profile_templates_exist_with_profile_name(self) -> None:
        expected = {
            "local": PROFILE_DIR / "local.env.example",
            "staging": PROFILE_DIR / "staging.env.example",
            "prod": PROFILE_DIR / "prod.env.example",
        }
        for profile, path in expected.items():
            self.assertTrue(path.exists(), f"missing template: {path}")
            content = path.read_text(encoding="utf-8")
            self.assertIn(f"DEPLOYMENT_PROFILE={profile}", content)


if __name__ == "__main__":
    unittest.main()
