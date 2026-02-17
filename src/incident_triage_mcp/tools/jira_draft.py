
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from incident_triage_mcp.domain_models import EvidenceBundle, JiraDraftTicket


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_jira_draft(bundle_dict: Dict[str, Any],project_key: str = "INC", evidence_uri: str | None = None) -> Dict[str, Any]:
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
        for s in bundle.signals[:8]:
            # Some schemas don't include `source`; keep it optional
            src = getattr(s, "source", None) or getattr(s, "provider", None) or getattr(s, "origin", None)
            if src:
                lines.append(f"- `{s.key}`: **{s.value}** ({src})")
            else:
                lines.append(f"- `{s.key}`: **{s.value}**")

    if bundle.runbook_hits:
        lines.append("\n## Runbook hits")
        for r in sorted(bundle.runbook_hits, key=lambda x: x.score, reverse=True)[:5]:
            # Support different schemas: some have `path`, others have `doc_id`/`summary`
            ref = (
                getattr(r, "path", None)
                or getattr(r, "doc_id", None)
                or getattr(r, "id", None)
                or ""
            )
            extra = getattr(r, "summary", None)

            line = f"- **{r.title}** (score={r.score})"
            if ref:
                line += f" — `{ref}`"
            if extra:
                line += f"\n  - {extra}"
            lines.append(line)

    if bundle.recommended_next_steps:
        lines.append("\n## Recommended next steps\n")
        for step in bundle.recommended_next_steps[:8]:
            lines.append(f"- {step}")

    if bundle.links:
        lines.append("\n## Links")
        for l in bundle.links:
            ltype = l.get("type") if isinstance(l, dict) else getattr(l, "type", None)
            url = l.get("url") if isinstance(l, dict) else getattr(l, "url", None)
            if not url:
                continue
            lines.append(f"- **{ltype or 'link'}**: {url}")

    draft = JiraDraftTicket(
        incident_id=bundle.incident_id,
        project_key=project_key,
        title=title,
        priority=priority,
        labels=labels,
        description_md="\n".join(lines).strip() + "\n",
        evidence_uri=evidence_uri,
        generated_at_iso=_now(),
    )
    return draft.model_dump()
