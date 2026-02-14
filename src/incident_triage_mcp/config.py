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

    # Runbooks
    runbooks_dir: str


def load_config() -> AppConfig:
    artifact_store = (_env("ARTIFACT_STORE", "s3") or "s3").lower()

    cfg = AppConfig(
        mcp_transport=_env("MCP_TRANSPORT", "stdio") or "stdio",
        mcp_host=_env("MCP_HOST", "0.0.0.0") or "0.0.0.0",
        mcp_port=int(_env("MCP_PORT", "3333") or "3333"),

        audit_mode=(_env("AUDIT_MODE", "stdout") or "stdout").lower(),
        audit_path=_env("AUDIT_PATH", "audit.jsonl") or "audit.jsonl",

        artifact_store=artifact_store,
        s3_endpoint_url=_env("S3_ENDPOINT_URL"),
        s3_bucket=_env("S3_BUCKET"),
        s3_region=_env("S3_REGION", "us-east-1") or "us-east-1",
        aws_access_key_id=_env("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=_env("AWS_SECRET_ACCESS_KEY"),

        airflow_base_url=_env("AIRFLOW_BASE_URL"),
        airflow_username=_env("AIRFLOW_USERNAME"),
        airflow_password=_env("AIRFLOW_PASSWORD"),

        runbooks_dir=_env("RUNBOOKS_DIR", "./runbooks") or "./runbooks",
    )

    # Validate audit
    if cfg.audit_mode not in {"stdout", "file"}:
        raise ConfigError("AUDIT_MODE must be 'stdout' or 'file'")

    # Validate artifacts
    if cfg.artifact_store == "s3":
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
            raise ConfigError("Missing required env vars for ARTIFACT_STORE=s3: " + ", ".join(missing))
    elif cfg.artifact_store != "fs":
        raise ConfigError("ARTIFACT_STORE must be 's3' or 'fs'")

    # Airflow is optional: only validate if user intends to use it
    if cfg.airflow_base_url:
        # if base url set, require creds (since your setup uses basic auth)
        if not cfg.airflow_username or not cfg.airflow_password:
            raise ConfigError("AIRFLOW_BASE_URL is set, but AIRFLOW_USERNAME/AIRFLOW_PASSWORD are missing")

    return cfg