from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from incident_triage_mcp.adapters.contracts import AlertsProvider, MetricsProvider, ObservabilityAdapter
from incident_triage_mcp.adapters.datadog_mock import DatadogMock
from incident_triage_mcp.adapters.datadog_real import DatadogAPI
from incident_triage_mcp.adapters.resilience import ResiliencePolicy, ResilienceRunner
from incident_triage_mcp.secrets.loader import SecretsLoader


class _UnimplementedObservabilityAdapter:
    def __init__(self, provider: str) -> None:
        self.provider = provider

    def _raise(self, operation: str) -> None:
        raise RuntimeError(
            f"Observability provider '{self.provider}' is configured but not implemented for {operation}."
        )

    def fetch_active_alerts(
        self, services: list[str], since_minutes: int, max_alerts: int
    ) -> list[dict[str, Any]]:
        self._raise("fetch_active_alerts")

    def health_snapshot(self, service: str, start_iso: str, end_iso: str) -> dict[str, Any]:
        self._raise("health_snapshot")


_OBSERVABILITY_PROVIDERS: dict[str, Callable[[SecretsLoader], ObservabilityAdapter]] = {}


def register_observability_provider(
    name: str, factory: Callable[[SecretsLoader], ObservabilityAdapter]
) -> None:
    _OBSERVABILITY_PROVIDERS[name.strip().lower()] = factory


def _build_provider(name: str, secrets: SecretsLoader) -> ObservabilityAdapter:
    normalized = name.strip().lower()
    factory = _OBSERVABILITY_PROVIDERS.get(normalized)
    if not factory:
        return _UnimplementedObservabilityAdapter(provider=normalized)
    return factory(secrets)


def _register_builtin_providers() -> None:
    if _OBSERVABILITY_PROVIDERS:
        return
    register_observability_provider("mock", lambda _secrets: DatadogMock())
    register_observability_provider("datadog", lambda secrets: DatadogAPI(secrets))
    register_observability_provider("cloudwatch", lambda _secrets: _UnimplementedObservabilityAdapter("cloudwatch"))


@dataclass
class ObservabilityRegistry:
    alerts_provider: str
    metrics_provider: str
    logs_provider: str
    traces_provider: str
    secrets: SecretsLoader
    resilience_policy: ResiliencePolicy

    def __post_init__(self) -> None:
        _register_builtin_providers()
        provider_cache: dict[str, ObservabilityAdapter] = {}

        def _cached_provider(name: str) -> ObservabilityAdapter:
            normalized = name.strip().lower()
            existing = provider_cache.get(normalized)
            if existing is not None:
                return existing
            created = _build_provider(normalized, self.secrets)
            provider_cache[normalized] = created
            return created

        self._alerts_adapter = _cached_provider(self.alerts_provider)
        self._metrics_adapter = _cached_provider(self.metrics_provider)
        self._alerts_runner = ResilienceRunner(
            provider=self.alerts_provider,
            policy=self.resilience_policy,
        )
        self._metrics_runner = ResilienceRunner(
            provider=self.metrics_provider,
            policy=self.resilience_policy,
        )

    def provider_summary(self) -> dict[str, str]:
        return {
            "alerts_provider": self.alerts_provider,
            "metrics_provider": self.metrics_provider,
            "logs_provider": self.logs_provider,
            "traces_provider": self.traces_provider,
        }

    def fetch_active_alerts(
        self, services: list[str], since_minutes: int, max_alerts: int
    ) -> list[dict[str, Any]]:
        return self._alerts_runner.invoke(
            "fetch_active_alerts",
            self._alerts_adapter.fetch_active_alerts,
            services,
            since_minutes,
            max_alerts,
        )

    def health_snapshot(self, service: str, start_iso: str, end_iso: str) -> dict[str, Any]:
        return self._metrics_runner.invoke(
            "health_snapshot",
            self._metrics_adapter.health_snapshot,
            service,
            start_iso,
            end_iso,
        )

    @property
    def alerts_adapter(self) -> AlertsProvider:
        return self._alerts_adapter

    @property
    def metrics_adapter(self) -> MetricsProvider:
        return self._metrics_adapter


def build_observability_registry(
    *,
    alerts_provider: str,
    metrics_provider: str,
    logs_provider: str,
    traces_provider: str,
    secrets: SecretsLoader,
    resilience_policy: ResiliencePolicy | None = None,
) -> ObservabilityRegistry:
    return ObservabilityRegistry(
        alerts_provider=alerts_provider,
        metrics_provider=metrics_provider,
        logs_provider=logs_provider,
        traces_provider=traces_provider,
        secrets=secrets,
        resilience_policy=resilience_policy or ResiliencePolicy(),
    )
