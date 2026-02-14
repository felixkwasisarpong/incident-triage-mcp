from __future__ import annotations
from typing import Any, Dict, List, Tuple
from datetime import datetime, timezone
from incident_triage_mcp.domain_models import EvidenceBundle, TriageSummary, Signal


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pick_priority(bundle: EvidenceBundle) -> str:
    prios = [a.priority for a in bundle.alerts] or ["P3"]
    order = {"P1":1, "P2": 2, "P3": 3, "P4": 4}
    prios_sorted = sorted(prios, key=lambda p: order.get(p,99))
    return prios_sorted(0)

def _pick_status(bundle: EvidenceBundle) -> str:
    if not bundle.alerts:
        return "unknown"
    # If any triggered => triggered, else warning, else resolved
    statuses = {a.status for a in bundle.alerts}
    if "triggered" in statuses:
        return "triggered"
    if "warning" in statuses:
        return "warning"
    if "resolved" in statuses:
        return "resolved"
    return "unknown"


def _select_top_signals(signals: List[Signal], limit: int = 4) -> List[Signal]:
    # Prefer common triage signals if present
    preferred_keys = {"error_rate", "latency_p95_ms", "rps", "cpu", "memory", "db_timeouts", "top_endpoint"}
    preferred = [s for s in signals if s.key in preferred_keys]
    others = [s for s in signals if s.key not in preferred_keys]
    return (preferred + others)[:limit]


def _headline(bundle: EvidenceBundle, status: str, priority: str) -> str:
    # Build a readable headline from known signals
    sig = {s.key: s.value for s in bundle.signals}
    bits = []
    if "error_rate" in sig:
        bits.append(f"error_rate={sig['error_rate']}")
    if "latency_p95_ms" in sig:
        bits.append(f"p95={sig['latency_p95_ms']}ms")
    tail = f" ({', '.join(bits)})" if bits else ""
    return f"[{priority}] {bundle.service} incident is {status}{tail}".strip()


def build_triage_summary(bundle_dict: Dict[str, Any], evidence_uri: str | None = None) -> Dict[str, Any]:
    bundle = EvidenceBundle.model_validate(bundle_dict)

    priority = _pick_priority(bundle)
    status = _pick_status(bundle)
    top_signals = _select_top_signals(bundle.signals, limit=4)
    top_alerts = bundle.alerts[:3]
    runbooks = sorted(bundle.runbook_hits, key=lambda r: r.score, reverse=True)[:3]

    findings = []
    if top_alerts:
        findings.append(f"{len(bundle.alerts)} alert(s) in window; top: {top_alerts[0].name}")
    if any(s.key == "top_endpoint" for s in bundle.signals):
        ep = next((s.value for s in bundle.signals if s.key == "top_endpoint"), None)
        if ep:
            findings.append(f"Top impacted endpoint: {ep}")
    if runbooks:
        findings.append(f"Top runbook match: {runbooks[0].title} (score={runbooks[0].score})")

    summary = TriageSummary(
        incident_id=bundle.incident_id,
        service=bundle.service,
        priority=priority,
        status=status,
        time_window=bundle.time_window,
        headline=_headline(bundle, status, priority),
        key_findings=findings,
        top_signals=top_signals,
        top_alerts=top_alerts,
        runbook_hits=runbooks,
        likely_causes=bundle.hypotheses[:3],
        recommended_next_steps=(bundle.recommended_next_steps[:5] or [
            "Confirm if a deploy occurred in the incident window",
            "Check downstream dependencies and DB health",
            "Inspect logs for top failing endpoint and error codes",
        ]),
        evidence_uri=evidence_uri,
        generated_at_iso=_utc_now_iso(),
    )

    return summary.model_dump()