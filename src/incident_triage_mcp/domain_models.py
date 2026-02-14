from __future__ import annotations

from typing import Any, Literal, Optional
from pydantic import BaseModel, Field


class TimeWindow(BaseModel):
    start_iso: str = Field(..., description="Inclusive start of evidence window (UTC ISO-8601).")
    end_iso: str = Field(..., description="Exclusive end of evidence window (UTC ISO-8601).")


class Signal(BaseModel):
    key: str
    value: Any
    unit: Optional[str] = None


class Alert(BaseModel):
    alert_id: str
    provider: Literal["datadog", "mock", "other"] = "mock"
    service: str
    name: str
    status: Literal["triggered", "warning", "resolved"] = "triggered"
    started_at_iso: str
    priority: Literal["P1", "P2", "P3", "P4"] = "P2"
    signal: Optional[dict[str, Any]] = None


class RunbookHit(BaseModel):
    doc_id: str
    title: str
    score: float = Field(..., ge=0.0, le=1.0)
    summary: str


class TriageSummary(BaseModel):
    incident_id: str
    service: str
    priority: str
    status: str
    time_window: TimeWindow

    headline: str
    key_findings: list[str] = Field(default_factory=list)
    top_signals: list[Signal] = Field(default_factory=list)
    top_alerts: list[Alert] = Field(default_factory=list)
    runbook_hits: list[RunbookHit] = Field(default_factory=list)

    likely_causes: list[str] = Field(default_factory=list)
    recommended_next_steps: list[str] = Field(default_factory=list)

    evidence_uri: Optional[str] = None
    generated_at_iso: str

class EvidenceBundle(BaseModel):
    """
    The single source of truth produced by Airflow, consumed by MCP tools,
    and later used to create Jira tickets or execute safe actions.
    """
    schema_version: str = "v1"
    incident_id: str
    service: str
    time_window: TimeWindow

    alerts: list[Alert] = Field(default_factory=list)
    signals: list[Signal] = Field(default_factory=list)
    runbook_hits: list[RunbookHit] = Field(default_factory=list)

    hypotheses: list[str] = Field(default_factory=list)
    recommended_next_steps: list[str] = Field(default_factory=list)

    links: list[dict[str, str]] = Field(
        default_factory=list,
        description='List of {"type": "...", "url": "..."} links'
    )
    generated_at_iso: str