from __future__ import annotations

import os
import time
import unittest
from unittest.mock import patch

from incident_triage_mcp.adapters.registry import build_observability_registry
from incident_triage_mcp.adapters.resilience import ResilienceError, ResiliencePolicy, ResilienceRunner
from incident_triage_mcp.config import ConfigError, load_config
from incident_triage_mcp.secrets.loader import EnvSecretsLoader, SecretsError, get_secrets_loader


class TestAdapterScaffold(unittest.TestCase):
    def test_config_provider_defaults(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            cfg = load_config()

        self.assertEqual(cfg.deployment_profile, "local")
        self.assertEqual(cfg.alerts_provider, "mock")
        self.assertEqual(cfg.metrics_provider, "mock")
        self.assertEqual(cfg.logs_provider, "mock")
        self.assertEqual(cfg.traces_provider, "mock")

    def test_config_rejects_invalid_deployment_profile(self) -> None:
        with patch.dict(os.environ, {"DEPLOYMENT_PROFILE": "qa"}, clear=True):
            with self.assertRaises(ConfigError):
                load_config()

    def test_config_rejects_invalid_provider_flag(self) -> None:
        with patch.dict(os.environ, {"ALERTS_PROVIDER": "nope"}, clear=True):
            with self.assertRaises(ConfigError):
                load_config()

    def test_config_rejects_invalid_ticket_provider_flag(self) -> None:
        with patch.dict(os.environ, {"JIRA_PROVIDER": "bad-provider"}, clear=True):
            with self.assertRaises(ConfigError):
                load_config()

    def test_config_rejects_invalid_resilience_values(self) -> None:
        with patch.dict(os.environ, {"ADAPTER_TIMEOUT_SECONDS": "0"}, clear=True):
            with self.assertRaises(ConfigError):
                load_config()

    def test_config_rejects_http_api_key_mode_without_key(self) -> None:
        with patch.dict(os.environ, {"MCP_HTTP_AUTH_MODE": "api_key"}, clear=True):
            with self.assertRaises(ConfigError):
                load_config()

    def test_config_rejects_http_jwt_mode_without_secret(self) -> None:
        with patch.dict(os.environ, {"MCP_HTTP_AUTH_MODE": "jwt_hs256"}, clear=True):
            with self.assertRaises(ConfigError):
                load_config()

    def test_staging_streamable_http_requires_auth(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DEPLOYMENT_PROFILE": "staging",
                "MCP_TRANSPORT": "streamable-http",
                "MCP_HTTP_AUTH_MODE": "none",
            },
            clear=True,
        ):
            with self.assertRaises(ConfigError):
                load_config()

    def test_staging_requires_datadog_secrets_when_selected(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DEPLOYMENT_PROFILE": "staging",
                "MCP_TRANSPORT": "stdio",
                "ALERTS_PROVIDER": "datadog",
            },
            clear=True,
        ):
            with self.assertRaises(ConfigError):
                load_config()

    def test_staging_requires_opsgenie_secret_when_selected(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DEPLOYMENT_PROFILE": "staging",
                "MCP_TRANSPORT": "stdio",
                "ALERTS_PROVIDER": "opsgenie",
            },
            clear=True,
        ):
            with self.assertRaises(ConfigError):
                load_config()

    def test_staging_requires_servicenow_secrets_when_selected(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DEPLOYMENT_PROFILE": "staging",
                "MCP_TRANSPORT": "stdio",
                "JIRA_PROVIDER": "servicenow",
            },
            clear=True,
        ):
            with self.assertRaises(ConfigError):
                load_config()

    def test_prod_requires_durable_idempotency_backend(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DEPLOYMENT_PROFILE": "prod",
                "MCP_TRANSPORT": "stdio",
                "AUDIT_MODE": "stdout",
                "ALERTS_PROVIDER": "cloudwatch",
                "METRICS_PROVIDER": "cloudwatch",
            },
            clear=True,
        ):
            with self.assertRaises(ConfigError):
                load_config()

    def test_prod_rejects_mock_alerts_metrics(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DEPLOYMENT_PROFILE": "prod",
                "MCP_TRANSPORT": "stdio",
                "AUDIT_MODE": "stdout",
                "ALERTS_PROVIDER": "mock",
                "METRICS_PROVIDER": "mock",
                "IDEMPOTENCY_BACKEND": "redis",
                "IDEMPOTENCY_REDIS_URL": "redis://localhost:6379/0",
            },
            clear=True,
        ):
            with self.assertRaises(ConfigError):
                load_config()

    def test_prod_minimal_valid_profile(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DEPLOYMENT_PROFILE": "prod",
                "MCP_TRANSPORT": "stdio",
                "AUDIT_MODE": "stdout",
                "ALERTS_PROVIDER": "cloudwatch",
                "METRICS_PROVIDER": "cloudwatch",
                "IDEMPOTENCY_BACKEND": "redis",
                "IDEMPOTENCY_REDIS_URL": "redis://localhost:6379/0",
            },
            clear=True,
        ):
            cfg = load_config()

        self.assertEqual(cfg.deployment_profile, "prod")

    def test_registry_mock_provider_works(self) -> None:
        registry = build_observability_registry(
            alerts_provider="mock",
            metrics_provider="mock",
            logs_provider="mock",
            traces_provider="mock",
            secrets=EnvSecretsLoader(),
        )

        alerts = registry.fetch_active_alerts(["payments-api"], since_minutes=30, max_alerts=10)
        snapshot = registry.health_snapshot("payments-api", "2026-01-01T00:00:00Z", "2026-01-01T00:30:00Z")
        self.assertGreaterEqual(len(alerts), 1)
        self.assertEqual(snapshot["service"], "payments-api")

    def test_registry_logs_provider_none_returns_empty_list(self) -> None:
        registry = build_observability_registry(
            alerts_provider="mock",
            metrics_provider="mock",
            logs_provider="none",
            traces_provider="none",
            secrets=EnvSecretsLoader(),
        )

        logs = registry.fetch_logs("payments-api", "2026-01-01T00:00:00Z", "2026-01-01T00:30:00Z", limit=50)
        self.assertEqual(logs, [])
        traces = registry.fetch_traces(
            "payments-api",
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:30:00Z",
            limit=50,
        )
        self.assertEqual(traces, [])

    def test_registry_unimplemented_provider_returns_normalized_error(self) -> None:
        registry = build_observability_registry(
            alerts_provider="newrelic",
            metrics_provider="mock",
            logs_provider="mock",
            traces_provider="mock",
            secrets=EnvSecretsLoader(),
            resilience_policy=ResiliencePolicy(retries=0),
        )

        with self.assertRaises(ResilienceError) as ctx:
            registry.fetch_active_alerts(["payments-api"], since_minutes=30, max_alerts=10)

        self.assertEqual(ctx.exception.kind, "adapter_call_failed")
        self.assertEqual(ctx.exception.provider, "newrelic")
        self.assertIn("not implemented", str(ctx.exception.cause))

    def test_registry_opsgenie_provider_requires_api_key(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            registry = build_observability_registry(
                alerts_provider="opsgenie",
                metrics_provider="mock",
                logs_provider="none",
                traces_provider="none",
                secrets=EnvSecretsLoader(),
                resilience_policy=ResiliencePolicy(retries=0),
            )
            with self.assertRaises(ResilienceError) as ctx:
                registry.fetch_active_alerts(["payments-api"], since_minutes=30, max_alerts=5)

        self.assertEqual(ctx.exception.kind, "adapter_call_failed")
        self.assertIsNotNone(ctx.exception.cause)
        self.assertIn("OPSGENIE_API_KEY", str(ctx.exception.cause))

    def test_resilience_runner_opens_circuit_after_threshold(self) -> None:
        runner = ResilienceRunner(
            provider="mock",
            policy=ResiliencePolicy(
                retries=0,
                circuit_failure_threshold=1,
                circuit_open_seconds=60.0,
            ),
        )

        def always_fail() -> None:
            raise RuntimeError("boom")

        with self.assertRaises(ResilienceError) as first:
            runner.invoke("fetch_active_alerts", always_fail)
        self.assertEqual(first.exception.kind, "adapter_call_failed")

        with self.assertRaises(ResilienceError) as second:
            runner.invoke("fetch_active_alerts", always_fail)
        self.assertEqual(second.exception.kind, "circuit_open")

    def test_resilience_runner_normalizes_timeout(self) -> None:
        runner = ResilienceRunner(
            provider="mock",
            policy=ResiliencePolicy(
                timeout_seconds=0.01,
                retries=0,
                circuit_failure_threshold=5,
                circuit_open_seconds=0.0,
            ),
        )

        def too_slow() -> str:
            time.sleep(0.02)
            return "ok"

        with self.assertRaises(ResilienceError) as ctx:
            runner.invoke("health_snapshot", too_slow)

        self.assertEqual(ctx.exception.kind, "adapter_call_failed")
        self.assertIn("timeout budget", str(ctx.exception.cause))

    def test_resilience_runner_emits_event_sink_records(self) -> None:
        events: list[dict] = []
        runner = ResilienceRunner(
            provider="mock",
            policy=ResiliencePolicy(retries=0),
            event_sink=events.append,
        )

        result = runner.invoke("health_snapshot", lambda: {"ok": True})

        self.assertEqual(result, {"ok": True})
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["provider"], "mock")
        self.assertEqual(events[0]["operation"], "health_snapshot")
        self.assertEqual(events[0]["kind"], "success")

    def test_secrets_loader_provider_selection(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            loader = get_secrets_loader()
            self.assertIsInstance(loader, EnvSecretsLoader)

        with patch.dict(os.environ, {"SECRET_PROVIDER": "secret-manager"}, clear=True):
            loader = get_secrets_loader()
            with self.assertRaises(SecretsError):
                loader.get("ANY_SECRET", required=True)


if __name__ == "__main__":
    unittest.main()
