from __future__ import annotations

from typing import Any, Protocol


class AlertsProvider(Protocol):
    def fetch_active_alerts(
        self, services: list[str], since_minutes: int, max_alerts: int
    ) -> list[dict[str, Any]]: ...


class MetricsProvider(Protocol):
    def health_snapshot(self, service: str, start_iso: str, end_iso: str) -> dict[str, Any]: ...


class LogsProvider(Protocol):
    def fetch_logs(
        self, service: str, start_iso: str, end_iso: str, limit: int = 100
    ) -> list[dict[str, Any]]: ...


class TracesProvider(Protocol):
    def fetch_traces(
        self, service: str, start_iso: str, end_iso: str, limit: int = 100
    ) -> list[dict[str, Any]]: ...


class ObservabilityAdapter(AlertsProvider, MetricsProvider, Protocol):
    """
    Canonical observability contract.
    fetch_logs/fetch_traces are optional extensions implemented per provider.
    """


class TicketingProvider(Protocol):
    def create_ticket(self, title: str, body: str, severity: str) -> dict[str, Any]: ...


class RunbooksProvider(Protocol):
    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]: ...
