from __future__ import annotations
from typing import List, Dict, Any
import math

class RunbooksLocal:
    def __init__(self) -> None:
        self._docs = [
            {"doc_id": "rb_42", "title": "Payments DB timeout mitigation",
             "text": "If DB timeouts spike after deploy: rollback, scale read replicas, check connection pool."},
            {"doc_id": "rb_07", "title": "5xx spike checklist",
             "text": "Check recent deploys, dependency health, and top failing endpoints; confirm feature flags."},
        ]

    def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        q = [t for t in query.lower().split() if t.strip()]
        scored = []
        for d in self._docs:
            hay = (d["title"] + " " + d["text"]).lower()
            hits = sum(1 for t in q if t in hay)
            score = 1.0 - math.exp(-hits / 3.0)
            if hits:
                scored.append((score, d))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [{
            "doc_id": d["doc_id"],
            "title": d["title"],
            "score": round(s, 3),
            "summary": d["text"][:180] + ("..." if len(d["text"]) > 180 else "")
        } for s, d in scored[:limit]]