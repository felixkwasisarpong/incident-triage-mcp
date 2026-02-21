from __future__ import annotations

from html import escape
from typing import Any

import requests


def build_teams_message_card(title: str, message: str) -> dict[str, Any]:
    # Teams MessageCard text supports simple HTML line breaks.
    safe_text = escape(message).replace("\n", "<br>")
    return {
        "@type": "MessageCard",
        "@context": "https://schema.org/extensions",
        "summary": title,
        "themeColor": "0076D7",
        "title": title,
        "text": safe_text,
    }


def post_teams_webhook(webhook_url: str, payload: dict[str, Any], timeout_seconds: float = 15.0) -> None:
    response = requests.post(webhook_url, json=payload, timeout=timeout_seconds)
    response.raise_for_status()
