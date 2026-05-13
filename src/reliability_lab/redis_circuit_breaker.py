"""Redis-backed circuit breaker for shared state across multiple gateway instances.

State is stored in a Redis Hash so every process with the same `name` and
`redis_url` sees the same circuit state, eliminating the thundering-herd
problem that arises when each instance runs an independent in-process breaker.

Redis key layout (one hash per breaker):
    cb:{name}:state
        state          -> "closed" | "open" | "half_open"
        failure_count  -> integer string
        success_count  -> integer string
        opened_at      -> float string (Unix timestamp)

Atomicity:
    - failure_count is incremented with HINCRBY (atomic)
    - OPEN transition uses HSETNX("probing","1") as a distributed mutex so
      only one instance sends the HALF_OPEN probe at a time
"""
from __future__ import annotations

import time
import threading
from typing import Any

from reliability_lab.circuit_breaker import CircuitBreaker, CircuitOpenError, CircuitState


class RedisCircuitBreaker(CircuitBreaker):
    """Circuit breaker whose state lives in Redis, shared across processes."""

    def __init__(
        self,
        name: str,
        failure_threshold: int,
        reset_timeout_seconds: float,
        success_threshold: int = 1,
        redis_url: str = "redis://localhost:6379/0",
        prefix: str = "cb:",
        ttl_seconds: int | None = None,
    ) -> None:
        import redis as redis_lib

        self.name = name
        self.failure_threshold = failure_threshold
        self.reset_timeout_seconds = reset_timeout_seconds
        self.success_threshold = success_threshold
        self._key = f"{prefix}{name}:state"
        self._ttl = ttl_seconds if ttl_seconds is not None else max(1, int(reset_timeout_seconds * 2))
        self._redis: Any = redis_lib.Redis.from_url(redis_url, decode_responses=True)
        self._lock = threading.Lock()  # local lock for allow_request check+set
        self.transition_log: list[dict[str, str | float]] = []

    # ------------------------------------------------------------------
    # State helpers
    # ------------------------------------------------------------------

    def _state(self) -> CircuitState:
        val = self._redis.hget(self._key, "state")
        if val is None:
            return CircuitState.CLOSED
        return CircuitState(val)

    def _set(self, mapping: dict[str, str]) -> None:
        self._redis.hset(self._key, mapping=mapping)
        self._redis.expire(self._key, self._ttl)

    def _log(self, from_state: CircuitState, to_state: CircuitState, reason: str) -> None:
        self.transition_log.append(
            {"from": from_state.value, "to": to_state.value, "reason": reason, "ts": time.time()}
        )

    # ------------------------------------------------------------------
    # Public API: mirrors CircuitBreaker interface
    # ------------------------------------------------------------------

    @property
    def state(self) -> CircuitState:
        return self._state()

    @state.setter
    def state(self, value: CircuitState) -> None:
        self._set({"state": value.value})

    def allow_request(self) -> bool:
        """Return True if a request may proceed.

        Uses HSETNX as a distributed mutex so only one instance transitions
        OPEN to HALF_OPEN and sends the probe; all others stay blocked.
        """
        with self._lock:
            state = self._state()
            if state != CircuitState.OPEN:
                return True

            opened_at_str = self._redis.hget(self._key, "opened_at")
            if opened_at_str is None:
                return False
            elapsed = time.time() - float(opened_at_str)
            if elapsed < self.reset_timeout_seconds:
                return False

            # Distributed mutex: only one instance wins the probe slot
            if self._redis.hsetnx(self._key, "probing", "1"):
                self._set({"state": CircuitState.HALF_OPEN.value, "failure_count": "0", "success_count": "0"})
                self._redis.hdel(self._key, "probing")
                self._log(CircuitState.OPEN, CircuitState.HALF_OPEN, "reset_timeout_elapsed")
                return True
            return False

    def record_success(self) -> None:
        with self._lock:
            state = self._state()
            if state == CircuitState.HALF_OPEN:
                count = int(self._redis.hincrby(self._key, "success_count", 1) or 0)
                self._redis.hset(self._key, "failure_count", "0")
                if count >= self.success_threshold:
                    self._set({"state": CircuitState.CLOSED.value, "failure_count": "0", "success_count": "0"})
                    self._log(CircuitState.HALF_OPEN, CircuitState.CLOSED, "probe_success")
            else:
                self._redis.hset(self._key, "failure_count", "0")

    def record_failure(self) -> None:
        with self._lock:
            state = self._state()
            if state == CircuitState.HALF_OPEN:
                self._set(
                    {
                        "state": CircuitState.OPEN.value,
                        "opened_at": str(time.time()),
                        "failure_count": "0",
                        "success_count": "0",
                    }
                )
                self._log(CircuitState.HALF_OPEN, CircuitState.OPEN, "probe_failure")
                return

            count = int(self._redis.hincrby(self._key, "failure_count", 1) or 0)
            self._redis.hset(self._key, "success_count", "0")
            if state == CircuitState.CLOSED and count >= self.failure_threshold:
                self._set(
                    {
                        "state": CircuitState.OPEN.value,
                        "opened_at": str(time.time()),
                        "failure_count": "0",
                    }
                )
                self._log(CircuitState.CLOSED, CircuitState.OPEN, "failure_threshold")

    def call(self, fn: Any, *args: object, **kwargs: object) -> Any:
        if not self.allow_request():
            raise CircuitOpenError(f"circuit {self.name} is open")
        try:
            result = fn(*args, **kwargs)
        except Exception:
            self.record_failure()
            raise
        self.record_success()
        return result

    def reset(self) -> None:
        """Reset all state (useful for tests)."""
        self._redis.delete(self._key)
