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

        self.assertEqual(cfg.alerts_provider, "mock")
        self.assertEqual(cfg.metrics_provider, "mock")
        self.assertEqual(cfg.logs_provider, "mock")
        self.assertEqual(cfg.traces_provider, "mock")

    def test_config_rejects_invalid_provider_flag(self) -> None:
        with patch.dict(os.environ, {"ALERTS_PROVIDER": "nope"}, clear=True):
            with self.assertRaises(ConfigError):
                load_config()

    def test_config_rejects_invalid_resilience_values(self) -> None:
        with patch.dict(os.environ, {"ADAPTER_TIMEOUT_SECONDS": "0"}, clear=True):
            with self.assertRaises(ConfigError):
                load_config()

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
