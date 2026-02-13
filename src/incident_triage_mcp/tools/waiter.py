from __future__ import annotations

import time
from typing import Any, Dict, Callable

def wait_for(
    getter: Callable[[str], Dict[str, Any]],
    incident_id: str,
    timeout_seconds: int = 30,
    poll_seconds: int = 2,
) -> Dict[str, Any]:
    deadline = time.time() + timeout_seconds
    attempts = 0

    while time.time() < deadline:
        attempts += 1
        out = getter(incident_id)
        if out.get("found"):
            out["attempts"] = attempts
            out["waited_seconds"] = int(timeout_seconds - max(0, deadline - time.time()))
            return out
        time.sleep(poll_seconds)

    return {
        "found": False,
        "incident_id": incident_id,
        "attempts": attempts,
        "timeout_seconds": timeout_seconds,
        "poll_seconds": poll_seconds,
    }