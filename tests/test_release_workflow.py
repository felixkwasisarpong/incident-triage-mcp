from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TestReleaseWorkflow(unittest.TestCase):
    def test_release_workflow_builds_multi_arch_images(self) -> None:
        content = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        self.assertIn("docker/setup-qemu-action@v3", content)
        self.assertIn("platforms: linux/amd64,linux/arm64", content)


if __name__ == "__main__":
    unittest.main()
