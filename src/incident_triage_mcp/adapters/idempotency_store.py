from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from typing import Any, Dict


class FileIdempotencyStore:
    """
    Minimal file-backed key/value store for idempotent ticket creation.
    Stored shape:
    {
      "<idempotency_key>": {
        "created": true,
        "provider": "cloud",
        "issue_key": "SCRUM-123",
        "browse_url": "https://.../browse/SCRUM-123"
      }
    }
    """

    def __init__(self, path: str) -> None:
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def _read_all(self) -> Dict[str, Dict[str, Any]]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except json.JSONDecodeError:
            return {}

        if isinstance(raw, dict):
            return raw
        return {}

    def _write_all(self, data: Dict[str, Dict[str, Any]]) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def get(self, key: str) -> Dict[str, Any] | None:
        if not key:
            return None
        with self._lock:
            return self._read_all().get(key)

    def set(self, key: str, value: Dict[str, Any]) -> None:
        if not key:
            return
        with self._lock:
            data = self._read_all()
            data[key] = value
            self._write_all(data)
