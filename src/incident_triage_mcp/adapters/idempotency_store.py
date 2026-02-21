from __future__ import annotations

import json
import os
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Protocol


class IdempotencyStore(Protocol):
    def get(self, key: str) -> dict[str, Any] | None: ...

    def set(self, key: str, value: dict[str, Any]) -> None: ...


class NullIdempotencyStore:
    def get(self, key: str) -> dict[str, Any] | None:
        return None

    def set(self, key: str, value: dict[str, Any]) -> None:
        return None


class FileIdempotencyStore:
    """
    Minimal file-backed key/value store for idempotent ticket creation.
    Stored shape:
    {
      "<idempotency_key>": {
        "created": true,
        "provider": "cloud",
        "issue_key": "SCRUM-123",
        "browse_url": "https://.../browse/SCRUM-123"
      }
    }
    """

    def __init__(self, path: str) -> None:
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def _read_all(self) -> dict[str, dict[str, Any]]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except json.JSONDecodeError:
            return {}

        if isinstance(raw, dict):
            return raw
        return {}

    def _write_all(self, data: dict[str, dict[str, Any]]) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def get(self, key: str) -> dict[str, Any] | None:
        if not key:
            return None
        with self._lock:
            return self._read_all().get(key)

    def set(self, key: str, value: dict[str, Any]) -> None:
        if not key:
            return
        with self._lock:
            data = self._read_all()
            data[key] = value
            self._write_all(data)


class RedisIdempotencyStore:
    def __init__(
        self,
        redis_url: str,
        *,
        key_prefix: str = "incident-triage:idempotency:",
        ttl_seconds: int | None = None,
        client: Any | None = None,
    ) -> None:
        self.redis_url = redis_url.strip()
        if not self.redis_url:
            raise RuntimeError("IDEMPOTENCY_REDIS_URL is required for IDEMPOTENCY_BACKEND=redis")
        self.key_prefix = key_prefix
        self.ttl_seconds = ttl_seconds if ttl_seconds and ttl_seconds > 0 else None
        self._client = client

    def _redis(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            import redis  # type: ignore
        except ImportError as exc:  # pragma: no cover - dependency availability
            raise RuntimeError(
                "Redis backend requires the 'redis' package. Install it or switch IDEMPOTENCY_BACKEND to file."
            ) from exc

        self._client = redis.Redis.from_url(self.redis_url, decode_responses=True)
        return self._client

    def _full_key(self, key: str) -> str:
        return f"{self.key_prefix}{key}"

    def get(self, key: str) -> dict[str, Any] | None:
        if not key:
            return None
        raw = self._redis().get(self._full_key(key))
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if isinstance(parsed, dict):
            return parsed
        return None

    def set(self, key: str, value: dict[str, Any]) -> None:
        if not key:
            return
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True)
        if self.ttl_seconds:
            self._redis().set(self._full_key(key), payload, ex=self.ttl_seconds)
            return
        self._redis().set(self._full_key(key), payload)


class PostgresIdempotencyStore:
    def __init__(
        self,
        dsn: str,
        *,
        table_name: str = "jira_idempotency",
        connect_fn: Callable[[str], Any] | None = None,
    ) -> None:
        self.dsn = dsn.strip()
        if not self.dsn:
            raise RuntimeError("IDEMPOTENCY_POSTGRES_DSN is required for IDEMPOTENCY_BACKEND=postgres")
        self.table_name = table_name.strip() or "jira_idempotency"
        if not self.table_name.replace("_", "").isalnum():
            raise RuntimeError("IDEMPOTENCY_POSTGRES_TABLE must be alphanumeric/underscore.")
        self._connect_fn = connect_fn
        self._table_ready = False
        self._lock = Lock()

    def _connect(self) -> Any:
        if self._connect_fn is not None:
            return self._connect_fn(self.dsn)
        try:
            import psycopg  # type: ignore
        except ImportError as exc:  # pragma: no cover - dependency availability
            raise RuntimeError(
                "Postgres backend requires the 'psycopg' package. Install it or switch IDEMPOTENCY_BACKEND to file."
            ) from exc
        return psycopg.connect(self.dsn)

    def _ensure_table(self, conn: Any) -> None:
        if self._table_ready:
            return
        with conn.cursor() as cur:
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.table_name} (
                    idempotency_key TEXT PRIMARY KEY,
                    value_json JSONB NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )
        conn.commit()
        self._table_ready = True

    def get(self, key: str) -> dict[str, Any] | None:
        if not key:
            return None
        with self._lock:
            conn = self._connect()
            try:
                self._ensure_table(conn)
                with conn.cursor() as cur:
                    cur.execute(
                        f"SELECT value_json FROM {self.table_name} WHERE idempotency_key = %s",
                        (key,),
                    )
                    row = cur.fetchone()
                if not row:
                    return None
                value = row[0]
                if isinstance(value, dict):
                    return value
                if isinstance(value, str):
                    try:
                        parsed = json.loads(value)
                    except json.JSONDecodeError:
                        return None
                    return parsed if isinstance(parsed, dict) else None
                return None
            finally:
                conn.close()

    def set(self, key: str, value: dict[str, Any]) -> None:
        if not key:
            return
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True)
        with self._lock:
            conn = self._connect()
            try:
                self._ensure_table(conn)
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        INSERT INTO {self.table_name} (idempotency_key, value_json, updated_at)
                        VALUES (%s, %s::jsonb, NOW())
                        ON CONFLICT (idempotency_key)
                        DO UPDATE SET value_json = EXCLUDED.value_json, updated_at = NOW()
                        """,
                        (key, payload),
                    )
                conn.commit()
            finally:
                conn.close()


def build_idempotency_store_from_env() -> IdempotencyStore:
    backend = (os.getenv("IDEMPOTENCY_BACKEND", "file") or "file").strip().lower()

    if backend in {"", "file", "fs", "local"}:
        path = os.getenv("IDEMPOTENCY_STORE_PATH", "./data/jira_idempotency.json")
        return FileIdempotencyStore(path)

    if backend == "none":
        return NullIdempotencyStore()

    if backend == "redis":
        redis_url = os.getenv("IDEMPOTENCY_REDIS_URL", "")
        key_prefix = os.getenv("IDEMPOTENCY_REDIS_KEY_PREFIX", "incident-triage:idempotency:")
        ttl_raw = os.getenv("IDEMPOTENCY_REDIS_TTL_SECONDS")
        ttl_seconds: int | None = None
        if ttl_raw:
            try:
                parsed = int(ttl_raw)
            except ValueError as exc:
                raise RuntimeError("IDEMPOTENCY_REDIS_TTL_SECONDS must be an integer.") from exc
            ttl_seconds = parsed if parsed > 0 else None
        return RedisIdempotencyStore(redis_url, key_prefix=key_prefix, ttl_seconds=ttl_seconds)

    if backend in {"postgres", "postgresql"}:
        dsn = os.getenv("IDEMPOTENCY_POSTGRES_DSN", "")
        table_name = os.getenv("IDEMPOTENCY_POSTGRES_TABLE", "jira_idempotency")
        return PostgresIdempotencyStore(dsn, table_name=table_name)

    raise RuntimeError("IDEMPOTENCY_BACKEND must be one of: file, redis, postgres, none")
