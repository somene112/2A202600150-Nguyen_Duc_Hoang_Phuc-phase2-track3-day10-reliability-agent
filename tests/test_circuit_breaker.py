from __future__ import annotations

import time

import pytest

from reliability_lab.circuit_breaker import CircuitBreaker, CircuitOpenError, CircuitState


def make_breaker(
    failure_threshold: int = 3,
    reset_timeout_seconds: float = 5.0,
    success_threshold: int = 1,
) -> CircuitBreaker:
    return CircuitBreaker(
        name="test",
        failure_threshold=failure_threshold,
        reset_timeout_seconds=reset_timeout_seconds,
        success_threshold=success_threshold,
    )


def test_closed_to_open_after_threshold_failures() -> None:
    cb = make_breaker(failure_threshold=3)
    for _ in range(3):
        cb.record_failure()
    assert cb.state == CircuitState.OPEN
    assert any(t["from"] == "closed" and t["to"] == "open" for t in cb.transition_log)


def test_open_rejects_requests_via_allow_request() -> None:
    cb = make_breaker(failure_threshold=1, reset_timeout_seconds=60.0)
    cb.record_failure()
    assert cb.state == CircuitState.OPEN
    assert cb.allow_request() is False


def test_open_to_half_open_after_timeout() -> None:
    cb = make_breaker(failure_threshold=1, reset_timeout_seconds=0.1)
    cb.record_failure()
    assert cb.state == CircuitState.OPEN
    time.sleep(0.2)
    assert cb.allow_request() is True
    assert cb.state == CircuitState.HALF_OPEN


def test_half_open_success_closes() -> None:
    cb = make_breaker(failure_threshold=1, reset_timeout_seconds=0.1, success_threshold=1)
    cb.record_failure()
    time.sleep(0.2)
    cb.allow_request()
    assert cb.state == CircuitState.HALF_OPEN
    cb.record_success()
    assert cb.state == CircuitState.CLOSED


def test_half_open_failure_reopens_immediately() -> None:
    cb = make_breaker(failure_threshold=3, reset_timeout_seconds=0.1)
    for _ in range(3):
        cb.record_failure()
    assert cb.state == CircuitState.OPEN
    time.sleep(0.2)
    cb.allow_request()
    assert cb.state == CircuitState.HALF_OPEN
    cb.record_failure()
    assert cb.state == CircuitState.OPEN
    assert any(t["reason"] == "probe_failure" for t in cb.transition_log)


def test_no_retry_storm_when_open() -> None:
    call_count = 0

    def failing_fn() -> str:
        nonlocal call_count
        call_count += 1
        raise RuntimeError("fail")

    cb = make_breaker(failure_threshold=1, reset_timeout_seconds=60.0)
    with pytest.raises(RuntimeError):
        cb.call(failing_fn)
    assert cb.state == CircuitState.OPEN
    assert call_count == 1

    for _ in range(5):
        with pytest.raises(CircuitOpenError):
            cb.call(failing_fn)
    assert call_count == 1
