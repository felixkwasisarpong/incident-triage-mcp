from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from incident_triage_mcp.domain_models import EvidenceBundle


def load_bundle(artifact_dir: str, incident_id: str) -> Dict[str, Any]:
    base = Path(artifact_dir)
    path = base / f"{incident_id}.json"

    if not path.exists():
        return {"found": False, "path": str(path)}

    raw = json.loads(path.read_text(encoding="utf-8"))
    bundle = EvidenceBundle.model_validate(raw)
    return {"found": True, "path": str(path), "bundle": bundle.model_dump()}