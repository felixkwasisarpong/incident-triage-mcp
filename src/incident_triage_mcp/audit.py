from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, Optional
from datetime import datetime, timezone
from pathlib import Path
import json
import uuid
import os
import sys

@dataclass
class AuditEvents:
    ts: str
    correlation_id: str
    tool: str
    arguments: Dict[str, Any]
    ok: bool
    meta: Dict[str,Any]



class AuditLog:

    """
    k8s-friendly audit logger.
    - AUDIT_MODE=stdout (default): writes JSONL events to stdout
    - AUDIT_MODE=file: writes JSONL to AUDIT_PATH
    """
    def __init__(self) -> None:
        self.mode = os.getenv("AUDIT_MODE", "stdout").lower()
        self.path = os.getenv("AUDIT_PATH", "audit.jsonl")

        if self.mode == "file":
            p = Path(self.path).expanduser()
            p.parent.mkdir(parents=True, exist_ok=True)
            self._file_path = p
        else:
            self._file_path = None

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


        line = json.dumps(evt.__dict__, ensure_ascii=False)


        if self.mode == "file" and self._file_path is not None:
            with self._file_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        else:
            # stdout for k8s log collectors
            print(line, file=sys.stdout, flush=True)

        return corr
