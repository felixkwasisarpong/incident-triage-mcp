from __future__ import annotations

import os
import sys
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from incident_triage_mcp.adapters.artifacts_s3 import read_evidence_bundle
from incident_triage_mcp.adapters.cloudwatch_real import CloudWatchAPI
from incident_triage_mcp.adapters.registry import build_observability_registry
from incident_triage_mcp.adapters.resilience import ResilienceError, ResiliencePolicy
from incident_triage_mcp.adapters.xray_real import XRayAPI
from incident_triage_mcp.secrets.loader import EnvSecretsLoader


@contextmanager
def _without_boto3():
    blocked_prefixes = ("boto3", "botocore")
    removed: dict[str, object] = {}
    for name in list(sys.modules):
        if (
            name == blocked_prefixes[0]
            or name.startswith("boto3.")
            or name == blocked_prefixes[1]
            or name.startswith("botocore.")
        ):
            removed[name] = sys.modules.pop(name)

    real_import = __import__

    def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name in blocked_prefixes or name.startswith("boto3.") or name.startswith("botocore."):
            raise ModuleNotFoundError("No module named 'boto3'")
        return real_import(name, globals, locals, fromlist, level)

    try:
        with patch("builtins.__import__", side_effect=_guarded_import):
            yield
    finally:
        sys.modules.update(removed)


class TestOptionalDependencies(unittest.TestCase):
    def test_cloudwatch_adapter_reports_missing_boto3(self) -> None:
        with patch.dict(os.environ, {}, clear=True), _without_boto3():
            adapter = CloudWatchAPI(EnvSecretsLoader())
            with self.assertRaises(RuntimeError) as ctx:
                adapter.fetch_active_alerts(["payments-api"], since_minutes=30, max_alerts=1)

        self.assertIn("optional dependency 'boto3'", str(ctx.exception))
        self.assertIn("incident-triage-mcp[aws]", str(ctx.exception))

    def test_xray_adapter_reports_missing_boto3(self) -> None:
        with patch.dict(os.environ, {}, clear=True), _without_boto3():
            adapter = XRayAPI(EnvSecretsLoader())
            with self.assertRaises(RuntimeError) as ctx:
                adapter.fetch_traces(
                    "payments-api",
                    "2026-01-01T00:00:00Z",
                    "2026-01-01T00:30:00Z",
                    limit=1,
                )

        self.assertIn("optional dependency 'boto3'", str(ctx.exception))
        self.assertIn("incident-triage-mcp[aws]", str(ctx.exception))

    def test_registry_normalizes_missing_boto3_for_cloudwatch_calls(self) -> None:
        with patch.dict(os.environ, {}, clear=True), _without_boto3():
            registry = build_observability_registry(
                alerts_provider="cloudwatch",
                metrics_provider="mock",
                logs_provider="none",
                traces_provider="none",
                secrets=EnvSecretsLoader(),
                resilience_policy=ResiliencePolicy(retries=0),
            )
            with self.assertRaises(ResilienceError) as ctx:
                registry.fetch_active_alerts(["payments-api"], since_minutes=30, max_alerts=1)

        self.assertEqual(ctx.exception.kind, "adapter_call_failed")
        self.assertIsNotNone(ctx.exception.cause)
        self.assertIn("optional dependency 'boto3'", str(ctx.exception.cause))

    def test_s3_artifacts_reader_reports_missing_boto3(self) -> None:
        with patch.dict(os.environ, {}, clear=True), _without_boto3():
            with self.assertRaises(RuntimeError) as ctx:
                read_evidence_bundle("INC-123")

        self.assertIn("optional dependency 'boto3'", str(ctx.exception))
        self.assertIn("incident-triage-mcp[aws]", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
