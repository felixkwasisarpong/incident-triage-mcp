
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from incident_triage_mcp.domain_models import EvidenceBundle, JiraDraftTicket


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_jira_draft(bundle_dict: Dict[str, Any], evidence_uri: str | None = None) -> Dict[str, Any]:
    bundle = EvidenceBundle.model_validate(bundle_dict)

    # Priority: pick best from alerts if present, else P3
    prios = [a.priority for a in bundle.alerts] or ["P3"]
    priority = sorted(prios, key=lambda p: {"P1": 1, "P2": 2, "P3": 3, "P4": 4}.get(p, 99))[0]

    title = f"[{priority}] {bundle.service} incident – {bundle.incident_id}"

    labels = ["incident", bundle.service.replace("_", "-").replace(" ", "-")]
    if any(a.status == "triggered" for a in bundle.alerts):
        labels.append("triggered")

    # Build markdown body
    lines = []
    lines.append(f"## Summary\nService: **{bundle.service}**\nIncident: **{bundle.incident_id}**\nWindow: **{bundle.time_window.start_iso} → {bundle.time_window.end_iso}**\n")
    if evidence_uri:
        lines.append(f"Evidence Bundle: `{evidence_uri}`\n")

    if bundle.alerts:
        lines.append("## Alerts\n")
        for a in bundle.alerts[:5]:
            lines.append(f"- **{a.name}** ({a.provider}) — `{a.status}` / `{a.priority}`")

    if bundle.signals:
        lines.append("\n## Signals\n")
        for s in bundle.signals[:6]:
            lines.append(f"- `{s.key}`: **{s.value}** ({s.source})")

    if bundle.runbook_hits:
        lines.append("\n## Runbook hits\n")
        for r in sorted(bundle.runbook_hits, key=lambda x: x.score, reverse=True)[:5]:
            lines.append(f"- **{r.title}** (score={r.score}) — {r.path}")

    if bundle.recommended_next_steps:
        lines.append("\n## Recommended next steps\n")
        for step in bundle.recommended_next_steps[:8]:
            lines.append(f"- {step}")

    if bundle.links:
        lines.append("\n## Links\n")
        for l in bundle.links:
            lines.append(f"- **{l.type}**: {l.url}")

    draft = JiraDraftTicket(
        incident_id=bundle.incident_id,
        title=title,
        priority=priority,
        labels=labels,
        description_md="\n".join(lines).strip() + "\n",
        evidence_uri=evidence_uri,
        generated_at_iso=_now(),
    )
    return draft.model_dump()