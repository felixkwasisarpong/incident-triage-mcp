from __future__ import annotations

from pathlib import Path
import re
import math

def _tokenize(s: str) -> list[str]:
    return [t for t in re.split(r"[^a-zA-Z0-9]+", s.lower()) if t]

def _score(query_tokens: list[str], text: str) -> float:
    hay = text.lower()
    hits = sum(1 for t in query_tokens if t in hay)
    return 1.0 - math.exp(-hits / 4.0)

def search_runbooks(runbooks_dir: str, query: str, limit: int = 5) -> list[dict]:
    base = Path(runbooks_dir)
    if not base.exists():
        return []
    q = _tokenize(query)
    scored = []
    for p in base.glob("*.md"):
        body = p.read_text(encoding="utf-8", errors="ignore")
        s = _score(q, body)
        if s > 0:
            title = body.splitlines()[0].lstrip("# ").strip() if body.strip() else p.stem
            summary = " ".join(body.splitlines()[0:20])[:220]
            scored.append((s, {"doc_id": p.stem, "title": title, "score": round(s, 3), "summary": summary}))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [d for _, d in scored[:limit]]