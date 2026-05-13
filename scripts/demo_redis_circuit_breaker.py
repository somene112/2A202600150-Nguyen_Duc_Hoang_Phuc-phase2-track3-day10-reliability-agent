"""Demonstrate that RedisCircuitBreaker shares state across two independent instances.

Two instances with the same name read/write the same Redis hash.
Instance A records 3 failures (opening the circuit);
Instance B's allow_request() returns False, proving shared state.
"""
from __future__ import annotations

from pathlib import Path

from reliability_lab.circuit_breaker import CircuitState
from reliability_lab.redis_circuit_breaker import RedisCircuitBreaker

REDIS_URL = "redis://localhost:6379/0"
BREAKER_NAME = "demo-primary"


def main() -> None:
    lines: list[str] = []

    def log(msg: str) -> None:
        print(msg)
        lines.append(msg)

    log("=" * 60)
    log("RedisCircuitBreaker -- shared state across instances demo")
    log("=" * 60)

    instance_a = RedisCircuitBreaker(
        BREAKER_NAME, failure_threshold=3, reset_timeout_seconds=5.0, redis_url=REDIS_URL
    )
    instance_b = RedisCircuitBreaker(
        BREAKER_NAME, failure_threshold=3, reset_timeout_seconds=5.0, redis_url=REDIS_URL
    )

    # Clean slate
    instance_a.reset()
    log(f"\n[Setup] Reset key 'cb:{BREAKER_NAME}:state' in Redis")

    # --- Test 1: initial state ---
    log("\n--- Test 1: initial state is CLOSED on both instances ---")
    assert instance_a.state == CircuitState.CLOSED
    assert instance_b.state == CircuitState.CLOSED
    log(f"Instance A state: {instance_a.state.value}")
    log(f"Instance B state: {instance_b.state.value}")
    log("PASS")

    # --- Test 2: instance A records 3 failures, circuit opens ---
    log("\n--- Test 2: Instance A records 3 failures -> circuit opens ---")
    instance_a.record_failure()
    log(f"After failure 1 - Instance A state: {instance_a.state.value}")
    instance_a.record_failure()
    log(f"After failure 2 - Instance A state: {instance_a.state.value}")
    instance_a.record_failure()
    log(f"After failure 3 - Instance A state: {instance_a.state.value}")
    assert instance_a.state == CircuitState.OPEN
    log("PASS: Instance A circuit is OPEN")

    # --- Test 3: instance B sees OPEN without recording any failures ---
    log("\n--- Test 3: Instance B sees shared OPEN state ---")
    log(f"Instance B state (no local failures): {instance_b.state.value}")
    assert instance_b.state == CircuitState.OPEN
    log("PASS: Instance B reads OPEN from Redis")

    # --- Test 4: instance B rejects requests ---
    log("\n--- Test 4: Instance B rejects requests while circuit is OPEN ---")
    allowed = instance_b.allow_request()
    log(f"Instance B allow_request() = {allowed}")
    assert allowed is False
    log("PASS: Instance B correctly rejects request (circuit is OPEN in Redis)")

    # --- Test 5: instance A allows_request also returns False ---
    log("\n--- Test 5: Instance A also rejects (same shared state) ---")
    allowed_a = instance_a.allow_request()
    log(f"Instance A allow_request() = {allowed_a}")
    assert allowed_a is False
    log("PASS")

    # --- Show Redis key ---
    log("\n--- Redis state hash ---")
    redis_hash = instance_a._redis.hgetall(f"cb:{BREAKER_NAME}:state")
    for k, v in redis_hash.items():
        log(f"  {k}: {v}")

    instance_a.reset()
    log(f"\n[Teardown] Deleted key 'cb:{BREAKER_NAME}:state'")
    log("=" * 60)

    Path("reports").mkdir(exist_ok=True)
    out = Path("reports/redis_circuit_breaker_evidence.txt")
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
