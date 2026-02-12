from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, Optional
from datetime import datetime, timezone
from pathlib import Path
import json
import uuid

@dataclass
class AuditEvents:
    ts: str
    correlation_id: str
    tool: str
    arguments: Dict[str, Any]
    ok: bool
    meta: Dict[str,Any]



class AuditLog:
    def __init__(self, path: str = "audit.jsonl") -> None:
        self.path = Path(path)
        # Ensure the directory exists for absolute or nested paths.
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(
            self,
            tool: str,
            arguments: Dict[str, Any],
            ok: bool,
            meta: Optional[Dict[str,Any]] = None,
            correlation_id: Optional[str] = None
    ) ->str:
        corr = correlation_id or f"corr_{uuid.uuid4().hex}"
        evt = AuditEvents(
            ts = datetime.now(timezone.utc).isoformat(),
            correlation_id=corr,
            tool=tool,
            arguments=arguments,
            ok=ok,
            meta=meta or {},

        )
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(evt.__dict__,ensure_ascii=False) + "\n")
        return corr
