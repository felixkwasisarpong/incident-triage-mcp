from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from incident_triage_mcp.adapters.idempotency_store import (
    FileIdempotencyStore,
    PostgresIdempotencyStore,
    RedisIdempotencyStore,
    build_idempotency_store_from_env,
)


class _FakeRedisClient:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.set_calls: list[tuple[str, str, int | None]] = []

    def get(self, key: str) -> str | None:
        return self.data.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.data[key] = value
        self.set_calls.append((key, value, ex))


class _FakeCursor:
    def __init__(self, state: dict[str, dict]) -> None:
        self._state = state
        self._row: tuple[dict] | None = None

    def execute(self, query: str, params: tuple | None = None) -> None:
        normalized = " ".join(query.split()).lower()
        if normalized.startswith("create table"):
            return
        if normalized.startswith("select value_json"):
            key = str(params[0]) if params else ""
            value = self._state.get(key)
            self._row = (value,) if value is not None else None
            return
        if normalized.startswith("insert into"):
            key = str(params[0]) if params else ""
            payload = str(params[1]) if params else "{}"
            self._state[key] = json.loads(payload)
            return
        raise AssertionError(f"Unexpected SQL in test stub: {query}")

    def fetchone(self) -> tuple[dict] | None:
        return self._row

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class _FakeConnection:
    def __init__(self, state: dict[str, dict]) -> None:
        self._state = state
        self.closed = False
        self.commits = 0

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self._state)

    def commit(self) -> None:
        self.commits += 1

    def close(self) -> None:
        self.closed = True


class TestIdempotencyStore(unittest.TestCase):
    def test_file_store_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = FileIdempotencyStore(os.path.join(tmpdir, "idempotency.json"))
            store.set("k1", {"issue_key": "SCRUM-1"})
            out = store.get("k1")

        self.assertEqual(out, {"issue_key": "SCRUM-1"})

    def test_redis_store_round_trip_with_ttl(self) -> None:
        fake = _FakeRedisClient()
        store = RedisIdempotencyStore(
            "redis://localhost:6379/0",
            key_prefix="triage:",
            ttl_seconds=120,
            client=fake,
        )
        store.set("k1", {"issue_key": "SCRUM-2"})
        out = store.get("k1")

        self.assertEqual(out, {"issue_key": "SCRUM-2"})
        self.assertEqual(fake.set_calls[0][0], "triage:k1")
        self.assertEqual(fake.set_calls[0][2], 120)

    def test_postgres_store_round_trip_with_fake_connection(self) -> None:
        state: dict[str, dict] = {}

        def _connect(_dsn: str) -> _FakeConnection:
            return _FakeConnection(state)

        store = PostgresIdempotencyStore(
            "postgresql://example",
            table_name="jira_idempotency",
            connect_fn=_connect,
        )
        store.set("k1", {"issue_key": "SCRUM-3"})
        out = store.get("k1")

        self.assertEqual(out, {"issue_key": "SCRUM-3"})

    def test_builder_defaults_to_file_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
            os.environ,
            {"IDEMPOTENCY_STORE_PATH": os.path.join(tmpdir, "store.json")},
            clear=True,
        ):
            store = build_idempotency_store_from_env()
        self.assertIsInstance(store, FileIdempotencyStore)

    def test_builder_rejects_missing_redis_url(self) -> None:
        with patch.dict(os.environ, {"IDEMPOTENCY_BACKEND": "redis"}, clear=True):
            with self.assertRaises(RuntimeError):
                build_idempotency_store_from_env()

    def test_builder_rejects_missing_postgres_dsn(self) -> None:
        with patch.dict(os.environ, {"IDEMPOTENCY_BACKEND": "postgres"}, clear=True):
            with self.assertRaises(RuntimeError):
                build_idempotency_store_from_env()


if __name__ == "__main__":
    unittest.main()
