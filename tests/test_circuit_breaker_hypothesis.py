"""Property-based tests for CircuitBreaker state machine using Hypothesis.

Strategy: drive the circuit breaker through arbitrary sequences of
record_success() / record_failure() and verify structural invariants hold
at every step, regardless of which sequence was generated.
"""
from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, rule

from reliability_lab.circuit_breaker import CircuitBreaker, CircuitState


# ---------------------------------------------------------------------------
# Rule-based state machine
# ---------------------------------------------------------------------------


class CircuitBreakerMachine(RuleBasedStateMachine):
    """Drives CircuitBreaker with random success/failure events and checks
    that invariants hold after every transition."""

    @initialize()  # type: ignore[misc]
    def setup(self) -> None:
        # reset_timeout=0.0 so OPEN to HALF_OPEN fires immediately on allow_request().
        # This avoids Windows timer-resolution flakiness in property tests.
        self.cb = CircuitBreaker(
            name="test",
            failure_threshold=3,
            reset_timeout_seconds=0.0,
            success_threshold=1,
        )

    @rule()  # type: ignore[misc]
    def success(self) -> None:
        self.cb.record_success()

    @rule()  # type: ignore[misc]
    def failure(self) -> None:
        self.cb.record_failure()

    @rule()  # type: ignore[misc]
    def probe(self) -> None:
        """Trigger the OPEN to HALF_OPEN timeout check."""
        self.cb.allow_request()

    @invariant()  # type: ignore[misc]
    def state_is_valid(self) -> None:
        assert self.cb.state in (CircuitState.CLOSED, CircuitState.OPEN, CircuitState.HALF_OPEN)

    @invariant()  # type: ignore[misc]
    def open_state_has_opened_at(self) -> None:
        if self.cb.state in (CircuitState.OPEN, CircuitState.HALF_OPEN):
            assert self.cb.opened_at is not None

    @invariant()  # type: ignore[misc]
    def counts_are_non_negative(self) -> None:
        assert self.cb.failure_count >= 0
        assert self.cb.success_count >= 0

    @invariant()  # type: ignore[misc]
    def transition_log_timestamps_monotone(self) -> None:
        ts_list = [float(e["ts"]) for e in self.cb.transition_log]
        assert ts_list == sorted(ts_list), "Transition timestamps must be non-decreasing"


# Hypothesis will generate up to 100 step sequences
CircuitBreakerTest = CircuitBreakerMachine.TestCase
CircuitBreakerTest.settings = settings(max_examples=200, stateful_step_count=50)


# ---------------------------------------------------------------------------
# Simple property tests (no state machine)
# ---------------------------------------------------------------------------


@given(failures=st.integers(min_value=0, max_value=30))  # type: ignore[misc]
@settings(max_examples=100)  # type: ignore[misc]
def test_failure_count_triggers_open_after_threshold(failures: int) -> None:
    cb = CircuitBreaker(name="prop", failure_threshold=3, reset_timeout_seconds=100.0)
    for _ in range(failures):
        cb.record_failure()
    if failures >= 3:
        assert cb.state == CircuitState.OPEN
    else:
        assert cb.state == CircuitState.CLOSED


@given(failures=st.integers(min_value=3, max_value=10))  # type: ignore[misc]
@settings(max_examples=100)  # type: ignore[misc]
def test_recovery_cycle_always_closes(failures: int) -> None:
    """After opening via failures, HALF_OPEN + record_success() must close.

    Uses reset_timeout_seconds=0.0 so the timeout is always elapsed immediately,
    removing reliance on wall-clock timing (Windows timer resolution is ~15 ms).
    """
    cb = CircuitBreaker(
        name="recovery",
        failure_threshold=failures,
        reset_timeout_seconds=0.0,
        success_threshold=1,
    )
    for _ in range(failures):
        cb.record_failure()
    assert cb.state == CircuitState.OPEN

    allowed = cb.allow_request()
    assert allowed is True
    assert cb.state == CircuitState.HALF_OPEN

    cb.record_success()
    assert cb.state == CircuitState.CLOSED
    assert cb.failure_count == 0


@given(n=st.integers(min_value=1, max_value=20))  # type: ignore[misc]
@settings(max_examples=50)  # type: ignore[misc]
def test_open_circuit_rejects_all_requests(n: int) -> None:
    """Once open, allow_request must return False for all attempts."""
    cb = CircuitBreaker(
        name="reject",
        failure_threshold=3,
        reset_timeout_seconds=9999.0,  # Never times out in this test
    )
    for _ in range(3):
        cb.record_failure()
    assert cb.state == CircuitState.OPEN

    for _ in range(n):
        assert cb.allow_request() is False
