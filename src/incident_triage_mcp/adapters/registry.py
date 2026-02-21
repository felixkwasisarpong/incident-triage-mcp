from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from incident_triage_mcp.adapters.cloudwatch_real import CloudWatchAPI
from incident_triage_mcp.adapters.contracts import (
    AlertsProvider,
    LogsProvider,
    MetricsProvider,
    ObservabilityAdapter,
    TracesProvider,
)
from incident_triage_mcp.adapters.datadog_mock import DatadogMock
from incident_triage_mcp.adapters.datadog_real import DatadogAPI
from incident_triage_mcp.adapters.elk_logs_real import ElkLogsAPI
from incident_triage_mcp.adapters.pagerduty_real import PagerDutyAPI
from incident_triage_mcp.adapters.prometheus_real import PrometheusAPI
from incident_triage_mcp.adapters.resilience import ResiliencePolicy, ResilienceRunner
from incident_triage_mcp.adapters.xray_real import XRayAPI
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

    def fetch_logs(
        self, service: str, start_iso: str, end_iso: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        self._raise("fetch_logs")

    def fetch_traces(
        self, service: str, start_iso: str, end_iso: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        self._raise("fetch_traces")


class _DisabledObservabilityAdapter:
    def __init__(self, provider: str = "none") -> None:
        self.provider = provider

    def fetch_active_alerts(
        self, services: list[str], since_minutes: int, max_alerts: int
    ) -> list[dict[str, Any]]:
        raise RuntimeError(f"Observability provider '{self.provider}' disables fetch_active_alerts.")

    def health_snapshot(self, service: str, start_iso: str, end_iso: str) -> dict[str, Any]:
        raise RuntimeError(f"Observability provider '{self.provider}' disables health_snapshot.")

    def fetch_logs(
        self, service: str, start_iso: str, end_iso: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        return []

    def fetch_traces(
        self, service: str, start_iso: str, end_iso: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        return []


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
    register_observability_provider("cloudwatch", lambda secrets: CloudWatchAPI(secrets))
    register_observability_provider("prometheus", lambda secrets: PrometheusAPI(secrets))
    register_observability_provider("pagerduty", lambda secrets: PagerDutyAPI(secrets))
    register_observability_provider("elk", lambda secrets: ElkLogsAPI(secrets))
    register_observability_provider("xray", lambda secrets: XRayAPI(secrets))
    register_observability_provider("none", lambda _secrets: _DisabledObservabilityAdapter("none"))


@dataclass
class ObservabilityRegistry:
    alerts_provider: str
    metrics_provider: str
    logs_provider: str
    traces_provider: str
    secrets: SecretsLoader
    resilience_policy: ResiliencePolicy
    resilience_event_sink: Callable[[dict[str, Any]], None] | None = None

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
        self._logs_adapter = _cached_provider(self.logs_provider)
        self._traces_adapter = _cached_provider(self.traces_provider)
        self._alerts_runner = ResilienceRunner(
            provider=self.alerts_provider,
            policy=self.resilience_policy,
            event_sink=self.resilience_event_sink,
        )
        self._metrics_runner = ResilienceRunner(
            provider=self.metrics_provider,
            policy=self.resilience_policy,
            event_sink=self.resilience_event_sink,
        )
        self._logs_runner = ResilienceRunner(
            provider=self.logs_provider,
            policy=self.resilience_policy,
            event_sink=self.resilience_event_sink,
        )
        self._traces_runner = ResilienceRunner(
            provider=self.traces_provider,
            policy=self.resilience_policy,
            event_sink=self.resilience_event_sink,
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

    def fetch_logs(
        self, service: str, start_iso: str, end_iso: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        logs_fn = getattr(self._logs_adapter, "fetch_logs", None)
        if not callable(logs_fn):
            raise RuntimeError(
                f"Observability provider '{self.logs_provider}' is configured but does not implement fetch_logs."
            )
        return self._logs_runner.invoke(
            "fetch_logs",
            logs_fn,
            service,
            start_iso,
            end_iso,
            limit,
        )

    def fetch_traces(
        self, service: str, start_iso: str, end_iso: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        traces_fn = getattr(self._traces_adapter, "fetch_traces", None)
        if not callable(traces_fn):
            raise RuntimeError(
                f"Observability provider '{self.traces_provider}' is configured but does not implement fetch_traces."
            )
        return self._traces_runner.invoke(
            "fetch_traces",
            traces_fn,
            service,
            start_iso,
            end_iso,
            limit,
        )

    @property
    def alerts_adapter(self) -> AlertsProvider:
        return self._alerts_adapter

    @property
    def metrics_adapter(self) -> MetricsProvider:
        return self._metrics_adapter

    @property
    def logs_adapter(self) -> LogsProvider:
        return self._logs_adapter

    @property
    def traces_adapter(self) -> TracesProvider:
        return self._traces_adapter


def build_observability_registry(
    *,
    alerts_provider: str,
    metrics_provider: str,
    logs_provider: str,
    traces_provider: str,
    secrets: SecretsLoader,
    resilience_policy: ResiliencePolicy | None = None,
    resilience_event_sink: Callable[[dict[str, Any]], None] | None = None,
) -> ObservabilityRegistry:
    return ObservabilityRegistry(
        alerts_provider=alerts_provider,
        metrics_provider=metrics_provider,
        logs_provider=logs_provider,
        traces_provider=traces_provider,
        secrets=secrets,
        resilience_policy=resilience_policy or ResiliencePolicy(),
        resilience_event_sink=resilience_event_sink,
    )
