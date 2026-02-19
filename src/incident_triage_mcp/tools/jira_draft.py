
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from incident_triage_mcp.domain_models import EvidenceBundle, JiraDraftTicket


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_jira_draft(
    bundle_dict: Dict[str, Any],
    project_key: str = "INC",
    issue_type: str = "Task",
    evidence_uri: str | None = None,
) -> Dict[str, Any]:
    bundle = EvidenceBundle.model_validate(bundle_dict)

    # Priority: pick best from alerts if present, else P3
    prios = [a.priority for a in bundle.alerts] or ["P3"]
    priority = sorted(prios, key=lambda p: {"P1": 1, "P2": 2, "P3": 3, "P4": 4}.get(p, 99))[0]

    title = f"[{priority}] {bundle.service} incident – {bundle.incident_id}"

    labels = ["incident", bundle.service.replace("_", "-").replace(" ", "-")]
    if any(a.status == "triggered" for a in bundle.alerts):
        labels.append("triggered")

    # Keep ticket body intentionally simple for clean Jira rendering:
    # H2 section headings and flat bullet lists only.
    lines: list[str] = [
        "## Summary",
        f"- Service: **{bundle.service}**",
        f"- Incident: **{bundle.incident_id}**",
        f"- Window: **{bundle.time_window.start_iso} to {bundle.time_window.end_iso}**",
    ]
    if evidence_uri:
        lines.append(f"- Evidence Bundle: `{evidence_uri}`")

    if bundle.alerts:
        lines.extend(["", "## Alerts"])
        for a in bundle.alerts[:5]:
            lines.append(f"- **{a.name}** ({a.provider}) - `{a.status}` / `{a.priority}`")

    if bundle.signals:
        lines.extend(["", "## Signals"])
        for s in bundle.signals[:8]:
            src = getattr(s, "source", None) or getattr(s, "provider", None) or getattr(s, "origin", None)
            if src:
                lines.append(f"- `{s.key}`: **{s.value}** ({src})")
            else:
                lines.append(f"- `{s.key}`: **{s.value}**")

    if bundle.runbook_hits:
        lines.extend(["", "## Runbook Hits"])
        for r in sorted(bundle.runbook_hits, key=lambda x: x.score, reverse=True)[:5]:
            ref = (
                getattr(r, "path", None)
                or getattr(r, "doc_id", None)
                or getattr(r, "id", None)
                or ""
            )
            extra = getattr(r, "summary", None)

            entry = f"**{r.title}** (score={r.score})"
            if ref:
                entry += f" - `{ref}`"
            if extra:
                entry += f" - {extra}"
            lines.append(f"- {entry}")

    if bundle.recommended_next_steps:
        lines.extend(["", "## Recommended Next Steps"])
        for step in bundle.recommended_next_steps[:8]:
            lines.append(f"- {step}")

    if bundle.links:
        lines.extend(["", "## Links"])
        for l in bundle.links:
            ltype = l.get("type") if isinstance(l, dict) else getattr(l, "type", None)
            url = l.get("url") if isinstance(l, dict) else getattr(l, "url", None)
            if not url:
                continue
            lines.append(f"- **{ltype or 'link'}**: {url}")

    draft = JiraDraftTicket(
        incident_id=bundle.incident_id,
        project_key=project_key,
        issue_type=issue_type,
        title=title,
        priority=priority,
        labels=labels,
        description_md="\n".join(lines).strip() + "\n",
        evidence_uri=evidence_uri,
        generated_at_iso=_now(),
    )
    return draft.model_dump()
