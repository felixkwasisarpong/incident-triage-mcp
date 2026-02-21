from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class ResiliencePolicy:
    timeout_seconds: float = 5.0
    retries: int = 1
    base_backoff_seconds: float = 0.15
    max_backoff_seconds: float = 1.0
    circuit_failure_threshold: int = 3
    circuit_open_seconds: float = 10.0


@dataclass
class ResilienceError(RuntimeError):
    provider: str
    operation: str
    kind: str
    message: str
    attempts: int
    retriable: bool
    cause: Exception | None = None

    def __str__(self) -> str:
        return self.message

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "operation": self.operation,
            "kind": self.kind,
            "message": self.message,
            "attempts": self.attempts,
            "retriable": self.retriable,
            "cause": str(self.cause) if self.cause else None,
        }


@dataclass
class _CircuitState:
    failure_count: int = 0
    open_until: float = 0.0


@dataclass
class ResilienceRunner:
    provider: str
    policy: ResiliencePolicy = field(default_factory=ResiliencePolicy)
    _circuits: dict[str, _CircuitState] = field(default_factory=dict)
    event_sink: Callable[[dict[str, Any]], None] | None = None

    def invoke(self, operation: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        state = self._circuits.setdefault(operation, _CircuitState())
        now = time.monotonic()
        if now < state.open_until:
            if self.event_sink:
                self.event_sink(
                    {
                        "provider": self.provider,
                        "operation": operation,
                        "kind": "circuit_open",
                        "attempts": 0,
                        "elapsed_ms": 0.0,
                    }
                )
            raise ResilienceError(
                provider=self.provider,
                operation=operation,
                kind="circuit_open",
                message=(
                    f"{self.provider}.{operation} circuit is open; retry after "
                    f"{round(state.open_until - now, 2)}s"
                ),
                attempts=0,
                retriable=True,
            )

        total_attempts = max(1, self.policy.retries + 1)
        started = time.monotonic()
        last_exc: Exception | None = None
        for attempt in range(1, total_attempts + 1):
            try:
                result = fn(*args, **kwargs)
                elapsed = time.monotonic() - started
                if elapsed > self.policy.timeout_seconds:
                    raise TimeoutError(
                        f"{self.provider}.{operation} exceeded timeout budget "
                        f"({elapsed:.2f}s > {self.policy.timeout_seconds:.2f}s)"
                    )
                state.failure_count = 0
                state.open_until = 0.0
                if self.event_sink:
                    self.event_sink(
                        {
                            "provider": self.provider,
                            "operation": operation,
                            "kind": "success",
                            "attempts": attempt,
                            "elapsed_ms": round(elapsed * 1000.0, 3),
                        }
                    )
                return result
            except Exception as exc:  # pragma: no cover - branches covered in tests
                last_exc = exc
                state.failure_count += 1
                if state.failure_count >= self.policy.circuit_failure_threshold:
                    state.open_until = time.monotonic() + self.policy.circuit_open_seconds

                if attempt >= total_attempts:
                    break
                backoff = min(
                    self.policy.max_backoff_seconds,
                    self.policy.base_backoff_seconds * (2 ** (attempt - 1)),
                )
                time.sleep(backoff)

        message = f"{self.provider}.{operation} failed after {total_attempts} attempt(s)"
        if self.event_sink:
            elapsed = time.monotonic() - started
            self.event_sink(
                {
                    "provider": self.provider,
                    "operation": operation,
                    "kind": "adapter_call_failed",
                    "attempts": total_attempts,
                    "elapsed_ms": round(elapsed * 1000.0, 3),
                    "cause": str(last_exc) if last_exc else None,
                }
            )
        raise ResilienceError(
            provider=self.provider,
            operation=operation,
            kind="adapter_call_failed",
            message=message,
            attempts=total_attempts,
            retriable=True,
            cause=last_exc,
        )
