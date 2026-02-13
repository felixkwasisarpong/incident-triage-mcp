from __future__ import annotations
from typing import Protocol, Any

class AlertsProvider(Protocol):
    def fetch_active_alerts(self, services: list[str], since_minutes: int, max_alerts: int) -> list[dict[str, Any]]: ...

class TicketingProvider(Protocol):
    def create_ticket(self, title: str, body: str, severity: str) -> dict[str, Any]: ...

class RunbooksProvider(Protocol):
    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]: ...