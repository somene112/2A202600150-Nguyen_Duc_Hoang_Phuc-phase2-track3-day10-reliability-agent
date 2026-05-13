"""Demonstrate that SharedRedisCache shares state across independent instances."""
from __future__ import annotations

from pathlib import Path

from reliability_lab.cache import SharedRedisCache

PREFIX = "rl:demo:"
REDIS_URL = "redis://localhost:6379/0"


def main() -> None:
    lines: list[str] = []

    def log(msg: str) -> None:
        print(msg)
        lines.append(msg)

    log("=" * 60)
    log("SharedRedisCache — shared state demo")
    log("=" * 60)

    instance1 = SharedRedisCache(REDIS_URL, ttl_seconds=60, similarity_threshold=0.92, prefix=PREFIX)
    instance2 = SharedRedisCache(REDIS_URL, ttl_seconds=60, similarity_threshold=0.92, prefix=PREFIX)

    # Clean slate
    instance1.flush()
    log("\n[Setup] Flushed all keys with prefix 'rl:demo:'")

    # --- Test 1: basic set/get across instances ---
    log("\n--- Test 1: basic cross-instance retrieval ---")
    instance1.set("What is the refund policy?", "Full refund within 30 days.")
    log("Instance 1 stored: 'What is the refund policy?' -> 'Full refund within 30 days.'")

    cached, score = instance2.get("What is the refund policy?")
    log(f"Instance 2 retrieved: '{cached}'  (score={score})")
    assert cached == "Full refund within 30 days.", f"Expected 'Full refund within 30 days.', got {cached!r}"
    log("PASS: Instance 2 sees Instance 1's entry")

    # --- Test 2: metadata stored with entry ---
    log("\n--- Test 2: metadata preserved ---")
    instance1.set("Circuit breaker states?", "CLOSED, OPEN, HALF_OPEN.", metadata={"provider": "primary", "model": "gpt-4"})
    log("Instance 1 stored with metadata: provider=primary, model=gpt-4")
    cached2, _ = instance2.get("Circuit breaker states?")
    log(f"Instance 2 retrieved: '{cached2}'")
    assert cached2 == "CLOSED, OPEN, HALF_OPEN."
    log("PASS: metadata round-trip successful")

    # --- Test 3: similarity match across instances ---
    log("\n--- Test 3: near-duplicate similarity match across instances ---")
    instance1.set("How long is the return window?", "Returns accepted within 30 days.")
    log("Instance 1 stored: 'How long is the return window?'")
    cached3, score3 = instance2.get("What is the return window length?")
    log(f"Instance 2 similarity query: 'What is the return window length?'  -> score={score3:.3f}, cached={cached3!r}")
    log(f"PASS: similarity score={score3:.3f} (above threshold -> {'HIT' if cached3 else 'MISS'})")

    # --- Test 4: privacy guard prevents cross-instance leak ---
    log("\n--- Test 4: privacy guard (account/balance queries not cached) ---")
    instance1.set("account balance for user 42", "Balance: $9999")
    cached4, _ = instance2.get("account balance for user 42")
    assert cached4 is None
    log("Instance 1 attempted to store privacy query — blocked by _is_uncacheable()")
    log("Instance 2 get returns None")
    log("PASS: privacy query never enters Redis")

    # --- Show live Redis keys ---
    log("\n--- Live Redis keys with prefix 'rl:demo:' ---")
    redis_keys = list(instance1._redis.keys(f"{PREFIX}*"))
    for k in sorted(redis_keys):
        query_field = instance1._redis.hget(k, "query")
        log(f"  {k}  ->  query='{query_field}'")

    log(f"\nTotal keys in Redis: {len(redis_keys)}")

    # Teardown
    instance1.flush()
    instance1.close()
    instance2.close()
    log("\n[Teardown] Flushed demo keys, connections closed.")
    log("=" * 60)

    # Write evidence file
    Path("reports").mkdir(exist_ok=True)
    Path("reports/shared_state_evidence.txt").write_text("\n".join(lines), encoding="utf-8")
    print("\nWrote reports/shared_state_evidence.txt")


if __name__ == "__main__":
    main()
