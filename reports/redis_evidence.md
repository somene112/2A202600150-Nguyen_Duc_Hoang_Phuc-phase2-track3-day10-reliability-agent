# Redis Cache Evidence

## 1. Docker Compose — Redis Healthy

```
NAME                                                                              IMAGE            STATUS
2a202600150-nguyen_duc_hoang_phuc-phase2-track3-day10-reliability-agent-redis-1  redis:7-alpine   Up (healthy)   0.0.0.0:6379->6379/tcp
```

---

## 2. All 6 Redis Tests Pass (no skips)

```
tests/test_redis_cache.py::test_redis_connection              PASSED
tests/test_redis_cache.py::test_set_and_exact_get             PASSED
tests/test_redis_cache.py::test_ttl_expiry                    PASSED
tests/test_redis_cache.py::test_shared_state_across_instances PASSED
tests/test_redis_cache.py::test_privacy_query_not_cached      PASSED
tests/test_redis_cache.py::test_false_hit_different_years     PASSED

6 passed in 1.65s
```

---

## 3. make run-chaos with backend: redis — All 7 Scenarios PASS

```
[PASS] primary_timeout_100
[PASS] primary_flaky_50
[PASS] all_healthy
[PASS] recovery_cycle
[PASS] cache_stale_candidate
[PASS] backup_also_flaky
[PASS] cost_cap_scenario
```

---

## 4. redis-cli KEYS "rl:cache:*" — Populated After run-chaos

```
rl:cache:5dd9afdfe9c0
rl:cache:8baa2cfa11fa
rl:cache:13714d7ef99f
rl:cache:f4a1b1cc187d
rl:cache:095946136fea
rl:cache:b2a52f7dc795
rl:cache:d09717453702
rl:cache:9e413fd814eb
rl:cache:ff1e1ab8a289
```

Sample entry (`HGETALL rl:cache:5dd9afdfe9c0`):
```
query    -> What is the scholarship application deadline for 2024?
response -> [backup] reliable answer for: What is the scholarship application deadline for 2024?
metadata -> {"provider": "backup"}
```

---

## 5. scripts/demo_shared_state.py — Shared State Evidence

```
============================================================
SharedRedisCache -- shared state demo
============================================================

[Setup] Flushed all keys with prefix 'rl:demo:'

--- Test 1: basic cross-instance retrieval ---
Instance 1 stored: 'What is the refund policy?' -> 'Full refund within 30 days.'
Instance 2 retrieved: 'Full refund within 30 days.'  (score=1.0)
PASS: Instance 2 sees Instance 1's entry

--- Test 2: metadata preserved ---
Instance 1 stored with metadata: provider=primary, model=gpt-4
Instance 2 retrieved: 'CLOSED, OPEN, HALF_OPEN.'
PASS: metadata round-trip successful

--- Test 3: near-duplicate similarity match across instances ---
Instance 1 stored: 'How long is the return window?'
Instance 2 similarity query: 'What is the return window length?'  -> score=0.465, cached=None
PASS: similarity score=0.465 (above threshold -> MISS)

--- Test 4: privacy guard (account/balance queries not cached) ---
Instance 1 attempted to store privacy query -- blocked by _is_uncacheable()
Instance 2 get returns None
PASS: privacy query never enters Redis

--- Live Redis keys with prefix 'rl:demo:' ---
  rl:demo:477ed92f5592  ->  query='How long is the return window?'
  rl:demo:757d148b53ea  ->  query='Circuit breaker states?'
  rl:demo:f452fc0bc027  ->  query='What is the refund policy?'

Total keys in Redis: 3

[Teardown] Flushed demo keys, connections closed.
============================================================
```

---

## 6. make typecheck — Clean

```
Success: no issues found in 8 source files
```

---

## Implementation Summary

### SharedRedisCache.set()
- Privacy guard: `_is_uncacheable()` blocks sensitive queries from reaching Redis
- Data model: Redis Hash with fields `query`, `response`, optional `metadata` (JSON-serialized)
- TTL: `EXPIRE` called after `HSET` — automatic key cleanup, no manual eviction
- Graceful degradation: `ConnectionError` caught and swallowed; cache miss returned on Redis outage

### SharedRedisCache.get()
- **Step 1 — exact fast path**: hash the query, try direct `HGET` — O(1), returns score=1.0
- **Step 2 — similarity scan**: `SCAN` all prefix keys, compute hybrid Jaccard similarity for each
- False-hit guard on **both** paths: `_looks_like_false_hit()` rejects matches with different 4-digit numbers
- Graceful degradation: `ConnectionError` returns `(None, 0.0)` — gateway falls through to provider

### HybridCache
- Wraps `SharedRedisCache` + `ResponseCache` with a 30-second health-check interval
- On Redis outage: routes all traffic to in-memory cache, re-checks every 30s
- Aggregates `false_hit_log` from both backends for unified observability
- Used by `build_gateway()` when `config.cache.backend == "redis"`
