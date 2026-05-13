from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, TypeVar

T = TypeVar("T")


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(RuntimeError):
    """Raised when a circuit is open and calls should fail fast."""


@dataclass(slots=True)
class CircuitBreaker:
    """Three-state circuit breaker: CLOSED → OPEN → HALF_OPEN → CLOSED.

    Thread-safe: a reentrant lock guards every state transition so concurrent
    workers can call allow_request / record_success / record_failure safely.
    """

    name: str
    failure_threshold: int
    reset_timeout_seconds: float
    success_threshold: int = 1
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    success_count: int = 0
    opened_at: float | None = None
    transition_log: list[dict[str, str | float]] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def allow_request(self) -> bool:
        """Return True if a request may proceed; False when the circuit is OPEN."""
        with self._lock:
            if self.state == CircuitState.OPEN:
                if self.opened_at is not None and time.monotonic() - self.opened_at >= self.reset_timeout_seconds:
                    self._transition(CircuitState.HALF_OPEN, "reset_timeout_elapsed")
                    return True
                return False
            return True

    def call(self, fn: Callable[..., T], *args: object, **kwargs: object) -> T:
        """Call a function through the circuit breaker."""
        if not self.allow_request():
            raise CircuitOpenError(f"circuit {self.name} is open")
        try:
            result = fn(*args, **kwargs)
        except Exception:
            self.record_failure()
            raise
        self.record_success()
        return result

    def record_success(self) -> None:
        """Record a successful call; close from HALF_OPEN when enough probes pass."""
        with self._lock:
            if self.state == CircuitState.HALF_OPEN:
                self.failure_count = 0
                self.success_count += 1
                if self.success_count >= self.success_threshold:
                    self._transition(CircuitState.CLOSED, "probe_success")
                    self.success_count = 0
            else:
                self.failure_count = 0

    def record_failure(self) -> None:
        """Record a failed call; open the circuit when the threshold is reached."""
        with self._lock:
            self.failure_count += 1
            self.success_count = 0
            if self.state == CircuitState.HALF_OPEN:
                self._transition(CircuitState.OPEN, "probe_failure")
                self.opened_at = time.monotonic()
                self.failure_count = 0
            elif self.failure_count >= self.failure_threshold:
                self._transition(CircuitState.OPEN, "failure_threshold")
                self.opened_at = time.monotonic()

    def _transition(self, new_state: CircuitState, reason: str) -> None:
        if self.state == new_state:
            return
        self.transition_log.append(
            {"from": self.state.value, "to": new_state.value, "reason": reason, "ts": time.time()}
        )
        self.state = new_state
