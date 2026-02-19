from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from incident_triage_mcp.adapters.jira_cloud import _markdown_to_adf
from incident_triage_mcp.tools.jira_draft import build_jira_draft


def _sample_bundle() -> dict:
    return {
        "schema_version": "v1",
        "incident_id": "INC-123",
        "service": "payments-api",
        "time_window": {
            "start_iso": "2026-01-01T00:00:00Z",
            "end_iso": "2026-01-01T00:30:00Z",
        },
        "alerts": [
            {
                "alert_id": "dd_101",
                "provider": "datadog",
                "service": "payments-api",
                "name": "5xx rate high",
                "status": "triggered",
                "started_at_iso": "2026-01-01T00:05:00Z",
                "priority": "P1",
                "signal": {"metric": "http.server.errors", "value": 0.12, "threshold": 0.05},
            }
        ],
        "signals": [
            {"key": "error_rate", "value": 0.12, "unit": "ratio"},
            {"key": "latency_p95_ms", "value": 840},
        ],
        "runbook_hits": [
            {"doc_id": "rb-1", "title": "Payments Error Budget", "score": 0.94, "summary": "Rollback last deploy"},
        ],
        "hypotheses": ["Recent deployment introduced regression"],
        "recommended_next_steps": ["Rollback to previous stable build", "Scale payments workers"],
        "links": [{"type": "dashboard", "url": "https://monitoring.example/payments"}],
        "generated_at_iso": "2026-01-01T00:31:00Z",
    }


class TestJiraFormatting(unittest.TestCase):
    def test_draft_markdown_is_h2_and_bullets(self) -> None:
        draft = build_jira_draft(
            _sample_bundle(),
            project_key="SCRUM",
            issue_type="Task",
            evidence_uri="s3://triage-artifacts/evidence/v1/INC-123.json",
        )
        body = draft["description_md"]

        self.assertIn("## Summary", body)
        self.assertIn("## Alerts", body)
        self.assertIn("## Signals", body)
        self.assertIn("## Runbook Hits", body)
        self.assertIn("## Recommended Next Steps", body)
        self.assertIn("## Links", body)

        for line in body.splitlines():
            if not line:
                continue
            if line.startswith("## "):
                continue
            self.assertTrue(line.startswith("- "), f"Expected bullet line, got: {line}")

        self.assertNotIn("\n  - ", body)

    def test_adf_render_is_headings_and_bullet_lists(self) -> None:
        draft = build_jira_draft(_sample_bundle(), evidence_uri="s3://triage-artifacts/evidence/v1/INC-123.json")
        adf = _markdown_to_adf(draft["description_md"])

        self.assertEqual(adf["type"], "doc")
        self.assertEqual(adf["version"], 1)

        node_types = [n["type"] for n in adf["content"]]
        self.assertIn("heading", node_types)
        self.assertIn("bulletList", node_types)
        self.assertTrue(set(node_types).issubset({"heading", "bulletList"}), node_types)

        for node in adf["content"]:
            if node["type"] == "heading":
                self.assertEqual(node.get("attrs", {}).get("level"), 2)


if __name__ == "__main__":
    unittest.main()
