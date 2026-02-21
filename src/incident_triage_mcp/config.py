from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


class ConfigError(RuntimeError):
    pass


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    return os.getenv(name, default)


def _require(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise ConfigError(f"Missing required environment variable: {name}")
    return v


@dataclass(frozen=True)
class AppConfig:
    # MCP
    mcp_transport: str
    mcp_host: str
    mcp_port: int

    # Audit
    audit_mode: str
    audit_path: str

    # Artifact store
    evidence_backend: str
    evidence_dir: str
    artifact_store: str
    s3_endpoint_url: Optional[str]
    s3_bucket: Optional[str]
    s3_region: str
    aws_access_key_id: Optional[str]
    aws_secret_access_key: Optional[str]

    # Airflow (optional)
    airflow_base_url: Optional[str]
    airflow_username: Optional[str]
    airflow_password: Optional[str]

    # Adapter providers
    alerts_provider: str
    metrics_provider: str
    logs_provider: str
    traces_provider: str

    # HTTP auth boundary
    http_auth_mode: str
    http_api_key: Optional[str]
    http_jwt_secret: Optional[str]
    http_jwt_issuer: Optional[str]
    http_jwt_audience: Optional[str]
    http_jwt_leeway_seconds: int

    # Adapter resilience
    adapter_timeout_seconds: float
    adapter_retries: int
    adapter_backoff_seconds: float
    adapter_max_backoff_seconds: float
    adapter_circuit_failure_threshold: int
    adapter_circuit_open_seconds: float

    # Runbooks
    runbooks_dir: str


def load_config() -> AppConfig:
    artifact_store = (_env("ARTIFACT_STORE", "fs") or "fs").lower()
    evidence_backend = (_env("EVIDENCE_BACKEND") or artifact_store or "fs").lower()

    cfg = AppConfig(
        mcp_transport=_env("MCP_TRANSPORT", "stdio") or "stdio",
        mcp_host=_env("MCP_HOST", "0.0.0.0") or "0.0.0.0",
        mcp_port=int(_env("MCP_PORT", "3333") or "3333"),

        audit_mode=(_env("AUDIT_MODE", "stdout") or "stdout").lower(),
        audit_path=_env("AUDIT_PATH", "audit.jsonl") or "audit.jsonl",

        evidence_backend=evidence_backend,
        evidence_dir=_env("EVIDENCE_DIR", "./evidence") or "./evidence",
        artifact_store=artifact_store,
        s3_endpoint_url=_env("S3_ENDPOINT_URL"),
        s3_bucket=_env("S3_BUCKET"),
        s3_region=_env("S3_REGION", "us-east-1") or "us-east-1",
        aws_access_key_id=_env("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=_env("AWS_SECRET_ACCESS_KEY"),

        airflow_base_url=_env("AIRFLOW_BASE_URL"),
        airflow_username=_env("AIRFLOW_USERNAME"),
        airflow_password=_env("AIRFLOW_PASSWORD"),

        alerts_provider=(_env("ALERTS_PROVIDER", "mock") or "mock").lower(),
        metrics_provider=(_env("METRICS_PROVIDER", "mock") or "mock").lower(),
        logs_provider=(_env("LOGS_PROVIDER", "mock") or "mock").lower(),
        traces_provider=(_env("TRACES_PROVIDER", "mock") or "mock").lower(),

        http_auth_mode=(_env("MCP_HTTP_AUTH_MODE", "none") or "none").lower(),
        http_api_key=_env("MCP_HTTP_API_KEY"),
        http_jwt_secret=_env("MCP_HTTP_JWT_SECRET"),
        http_jwt_issuer=_env("MCP_HTTP_JWT_ISSUER"),
        http_jwt_audience=_env("MCP_HTTP_JWT_AUDIENCE"),
        http_jwt_leeway_seconds=int(_env("MCP_HTTP_JWT_LEEWAY_SECONDS", "30") or "30"),

        adapter_timeout_seconds=float(_env("ADAPTER_TIMEOUT_SECONDS", "5.0") or "5.0"),
        adapter_retries=int(_env("ADAPTER_RETRIES", "1") or "1"),
        adapter_backoff_seconds=float(_env("ADAPTER_BACKOFF_SECONDS", "0.15") or "0.15"),
        adapter_max_backoff_seconds=float(_env("ADAPTER_MAX_BACKOFF_SECONDS", "1.0") or "1.0"),
        adapter_circuit_failure_threshold=int(
            _env("ADAPTER_CIRCUIT_FAILURE_THRESHOLD", "3") or "3"
        ),
        adapter_circuit_open_seconds=float(
            _env("ADAPTER_CIRCUIT_OPEN_SECONDS", "10.0") or "10.0"
        ),

        runbooks_dir=_env("RUNBOOKS_DIR", "./runbooks") or "./runbooks",
    )

    # Validate audit
    if cfg.audit_mode not in {"stdout", "file"}:
        raise ConfigError("AUDIT_MODE must be 'stdout' or 'file'")

    # Validate evidence backend mode
    if cfg.evidence_backend not in {"none", "fs", "s3", "airflow"}:
        raise ConfigError("EVIDENCE_BACKEND must be one of: none, fs, s3, airflow")

    # Validate provider flags
    provider_sets = {
        "ALERTS_PROVIDER": (
            cfg.alerts_provider,
            {"mock", "datadog", "cloudwatch", "prometheus", "pagerduty"},
        ),
        "METRICS_PROVIDER": (cfg.metrics_provider, {"mock", "datadog", "cloudwatch", "prometheus"}),
        "LOGS_PROVIDER": (cfg.logs_provider, {"mock", "datadog", "cloudwatch", "elk", "none"}),
        "TRACES_PROVIDER": (
            cfg.traces_provider,
            {"mock", "datadog", "cloudwatch", "xray", "otel", "none"},
        ),
    }
    for env_name, (value, allowed) in provider_sets.items():
        if value not in allowed:
            allowed_str = ", ".join(sorted(allowed))
            raise ConfigError(f"{env_name} must be one of: {allowed_str}")

    # Validate HTTP auth settings
    if cfg.http_auth_mode not in {"none", "api_key", "jwt_hs256"}:
        raise ConfigError("MCP_HTTP_AUTH_MODE must be one of: none, api_key, jwt_hs256")
    if cfg.http_auth_mode == "api_key" and not cfg.http_api_key:
        raise ConfigError("MCP_HTTP_API_KEY is required when MCP_HTTP_AUTH_MODE=api_key")
    if cfg.http_auth_mode == "jwt_hs256" and not cfg.http_jwt_secret:
        raise ConfigError("MCP_HTTP_JWT_SECRET is required when MCP_HTTP_AUTH_MODE=jwt_hs256")
    if cfg.http_jwt_leeway_seconds < 0:
        raise ConfigError("MCP_HTTP_JWT_LEEWAY_SECONDS must be >= 0")

    # Validate resilience settings
    if cfg.adapter_timeout_seconds <= 0:
        raise ConfigError("ADAPTER_TIMEOUT_SECONDS must be > 0")
    if cfg.adapter_retries < 0:
        raise ConfigError("ADAPTER_RETRIES must be >= 0")
    if cfg.adapter_backoff_seconds < 0:
        raise ConfigError("ADAPTER_BACKOFF_SECONDS must be >= 0")
    if cfg.adapter_max_backoff_seconds <= 0:
        raise ConfigError("ADAPTER_MAX_BACKOFF_SECONDS must be > 0")
    if cfg.adapter_circuit_failure_threshold <= 0:
        raise ConfigError("ADAPTER_CIRCUIT_FAILURE_THRESHOLD must be > 0")
    if cfg.adapter_circuit_open_seconds < 0:
        raise ConfigError("ADAPTER_CIRCUIT_OPEN_SECONDS must be >= 0")

    # Validate artifacts for S3 backend only
    if cfg.evidence_backend == "s3":
        missing = []
        if not cfg.s3_endpoint_url:
            missing.append("S3_ENDPOINT_URL")
        if not cfg.s3_bucket:
            missing.append("S3_BUCKET")
        if not cfg.aws_access_key_id:
            missing.append("AWS_ACCESS_KEY_ID")
        if not cfg.aws_secret_access_key:
            missing.append("AWS_SECRET_ACCESS_KEY")
        if missing:
            raise ConfigError(
                "Missing required env vars for EVIDENCE_BACKEND=s3: " + ", ".join(missing)
            )

    return cfg
