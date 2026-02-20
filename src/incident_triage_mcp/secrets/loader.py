from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol


class SecretsError(RuntimeError):
    pass


class SecretsLoader(Protocol):
    def get(self, name: str, *, default: str | None = None, required: bool = False) -> str | None: ...


@dataclass(frozen=True)
class EnvSecretsLoader:
    """
    Default secrets loader for local/staging usage.
    """

    def get(self, name: str, *, default: str | None = None, required: bool = False) -> str | None:
        value = os.getenv(name, default)
        if required and not value:
            raise SecretsError(f"Missing required secret: {name}")
        return value


@dataclass(frozen=True)
class SecretManagerLoader:
    """
    Interface scaffold for cloud secret managers (AWS/GCP/Azure/Vault).
    This adapter is intentionally minimal for now and should be replaced by a
    concrete provider implementation in production environments.
    """

    provider: str

    def get(self, name: str, *, default: str | None = None, required: bool = False) -> str | None:
        raise SecretsError(
            f"Secrets provider '{self.provider}' is not implemented yet. "
            "Use SECRET_PROVIDER=env for now."
        )


def get_secrets_loader() -> SecretsLoader:
    provider = (os.getenv("SECRET_PROVIDER", "env") or "env").strip().lower()
    if provider in {"", "env"}:
        return EnvSecretsLoader()
    if provider in {"secret-manager", "manager"}:
        return SecretManagerLoader(provider=provider)
    raise SecretsError("SECRET_PROVIDER must be one of: env, secret-manager")
