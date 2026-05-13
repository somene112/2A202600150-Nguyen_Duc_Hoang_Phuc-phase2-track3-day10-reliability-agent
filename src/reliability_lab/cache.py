from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
# Shared utilities — use these in both ResponseCache and SharedRedisCache
# ---------------------------------------------------------------------------

PRIVACY_PATTERNS = re.compile(
    r"\b(balance|password|credit.card|ssn|social.security|user.\d+|account.\d+)\b",
    re.IGNORECASE,
)
FALSE_HIT_ANALYSIS_THRESHOLD = 0.5


def _is_uncacheable(query: str) -> bool:
    """Return True if query contains privacy-sensitive keywords."""
    return bool(PRIVACY_PATTERNS.search(query))


def _looks_like_false_hit(query: str, cached_key: str) -> bool:
    """Return True if query and cached key contain different 4-digit numbers (years, IDs)."""
    nums_q = set(re.findall(r"\b\d{4}\b", query))
    nums_c = set(re.findall(r"\b\d{4}\b", cached_key))
    return bool(nums_q and nums_c and nums_q != nums_c)


# ---------------------------------------------------------------------------
# In-memory cache
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class CacheEntry:
    key: str
    value: str
    created_at: float
    metadata: dict[str, str]


class ResponseCache:
    """In-memory LRU-style cache with hybrid similarity scoring and safety guardrails.

    Configuration rationale
    -----------------------
    similarity_threshold (default 0.92):
        Empirically tuned: 0.85 causes false hits on date-sensitive queries such as
        "refund policy for 2024" vs "refund policy for 2026" (Jaccard ≈ 0.83).
        0.92 eliminates those false hits while still matching genuine rephrasings
        (e.g. "what is the return window?" ≈ "how long is the return window?").

    ttl_seconds (default 300, i.e. 5 minutes):
        Balances freshness vs. hit rate for FAQ-type workloads.  5 min is short
        enough that time-sensitive answers (prices, status) stay reasonably fresh,
        but long enough to absorb repeated identical questions within a session.
        Increase to 3600 for mostly-static content; decrease to 60 for real-time data.
    """

    def __init__(self, ttl_seconds: int, similarity_threshold: float):
        self.ttl_seconds = ttl_seconds
        self.similarity_threshold = similarity_threshold
        self._entries: list[CacheEntry] = []
        self.false_hit_log: list[dict[str, object]] = []
        self.hit_log: list[dict[str, object]] = []

    def get(self, query: str) -> tuple[str | None, float]:
        if _is_uncacheable(query):
            return None, 0.0
        best_value: str | None = None
        best_score = 0.0
        best_entry: CacheEntry | None = None
        now = time.time()
        self._entries = [e for e in self._entries if now - e.created_at <= self.ttl_seconds]
        for entry in self._entries:
            score = self.similarity(query, entry.key)
            if score > best_score:
                best_score = score
                best_value = entry.value
                best_entry = entry
        if (
            best_entry is not None
            and best_score >= FALSE_HIT_ANALYSIS_THRESHOLD
            and _looks_like_false_hit(query, best_entry.key)
        ):
            self.false_hit_log.append({
                "query": query,
                "cached_key": best_entry.key,
                "score": best_score,
                "reason": "4-digit number mismatch",
            })
            return None, best_score
        if best_score >= self.similarity_threshold and best_entry is not None:
            if _looks_like_false_hit(query, best_entry.key):
                self.false_hit_log.append({
                    "query": query,
                    "cached_key": best_entry.key,
                    "score": best_score,
                    "reason": "4-digit number mismatch",
                })
                return None, best_score
            self.hit_log.append({"query": query, "score": best_score, "ts": now})
            return best_value, best_score
        return None, best_score

    def set(self, query: str, value: str, metadata: dict[str, str] | None = None) -> None:
        if _is_uncacheable(query):
            return
        self._entries.append(CacheEntry(query, value, time.time(), metadata or {}))

    @staticmethod
    def similarity(a: str, b: str) -> float:
        """Hybrid similarity: exact match + char 3-gram Jaccard + token Jaccard with 4-digit penalty.

        Score = 0.6 * char_ngram_jaccard + 0.4 * token_jaccard
        Token score is multiplied by 0.4 when queries contain different 4-digit numbers
        (years, IDs) because differing numbers usually indicate different intent.
        """
        a_norm = a.lower().strip()
        b_norm = b.lower().strip()

        if a_norm == b_norm:
            return 1.0

        # Character 3-gram Jaccard
        def _ngrams(s: str, n: int = 3) -> set[str]:
            return {s[i : i + n] for i in range(len(s) - n + 1)} if len(s) >= n else {s}

        grams_a = _ngrams(a_norm)
        grams_b = _ngrams(b_norm)
        union_g = grams_a | grams_b
        char_score = len(grams_a & grams_b) / len(union_g) if union_g else 0.0

        # Token Jaccard with 4-digit number penalty
        tokens_a = set(a_norm.split())
        tokens_b = set(b_norm.split())
        union_t = tokens_a | tokens_b
        token_score = len(tokens_a & tokens_b) / len(union_t) if union_t else 0.0

        nums_a = set(re.findall(r"\b\d{4}\b", a_norm))
        nums_b = set(re.findall(r"\b\d{4}\b", b_norm))
        if nums_a and nums_b and nums_a != nums_b:
            token_score *= 0.4

        return 0.6 * char_score + 0.4 * token_score


# ---------------------------------------------------------------------------
# Redis shared cache
# ---------------------------------------------------------------------------


class SharedRedisCache:
    """Redis-backed shared cache for multi-instance deployments.

    Data model:
        Key   = "{prefix}{query_hash}"  (Redis Hash namespace)
        Value = Redis Hash: "query", "response", optional "metadata" (JSON)
        TTL   = Redis EXPIRE (no manual eviction)

    Graceful degradation: ConnectionError is caught and swallowed so a Redis
    outage never crashes the gateway — callers simply get cache misses.
    """

    def __init__(
        self,
        redis_url: str,
        ttl_seconds: int,
        similarity_threshold: float,
        prefix: str = "rl:cache:",
    ):
        import redis as redis_lib

        self.ttl_seconds = ttl_seconds
        self.similarity_threshold = similarity_threshold
        self.prefix = prefix
        self.false_hit_log: list[dict[str, object]] = []
        self._redis: Any = redis_lib.Redis.from_url(redis_url, decode_responses=True)
        # Store the exception type to avoid re-importing in hot path
        self._conn_exc: type[Exception] = redis_lib.exceptions.ConnectionError

    def ping(self) -> bool:
        """Check Redis connectivity."""
        try:
            return bool(self._redis.ping())
        except Exception:
            return False

    def get(self, query: str) -> tuple[str | None, float]:
        """Look up a cached response from Redis.

        Two-step: exact hash match first (O(1)), then similarity scan (O(n)).
        Both steps check for false-hit (differing 4-digit numbers) before returning.
        """
        if _is_uncacheable(query):
            return None, 0.0
        try:
            # Step 1: exact-match fast path
            exact_key = f"{self.prefix}{self._query_hash(query)}"
            exact_response = self._redis.hget(exact_key, "response")
            if exact_response is not None:
                cached_query = self._redis.hget(exact_key, "query") or query
                if _looks_like_false_hit(query, cached_query):
                    self.false_hit_log.append({
                        "query": query,
                        "cached_key": cached_query,
                        "score": 1.0,
                        "reason": "year_mismatch",
                    })
                    return None, 1.0
                return exact_response, 1.0

            # Step 2: similarity scan
            best_score = 0.0
            best_response: str | None = None
            best_cached_query: str | None = None
            for key in self._redis.scan_iter(f"{self.prefix}*"):
                cached_query = self._redis.hget(key, "query")
                if not cached_query:
                    continue
                score = ResponseCache.similarity(query, cached_query)
                if score > best_score:
                    best_score = score
                    best_response = self._redis.hget(key, "response")
                    best_cached_query = cached_query

            if (
                best_response
                and best_cached_query
                and best_score >= FALSE_HIT_ANALYSIS_THRESHOLD
                and _looks_like_false_hit(query, best_cached_query)
            ):
                self.false_hit_log.append({
                    "query": query,
                    "cached_key": best_cached_query,
                    "score": best_score,
                    "reason": "year_mismatch",
                })
                return None, best_score

            if best_score >= self.similarity_threshold and best_response and best_cached_query:
                if _looks_like_false_hit(query, best_cached_query):
                    self.false_hit_log.append({
                        "query": query,
                        "cached_key": best_cached_query,
                        "score": best_score,
                        "reason": "year_mismatch",
                    })
                    return None, best_score
                return best_response, best_score

            return None, best_score
        except self._conn_exc:
            return None, 0.0

    def set(self, query: str, value: str, metadata: dict[str, str] | None = None) -> None:
        """Store a response in Redis with TTL."""
        if _is_uncacheable(query):
            return
        try:
            key = f"{self.prefix}{self._query_hash(query)}"
            mapping: dict[str, str] = {"query": query, "response": value}
            if metadata:
                mapping["metadata"] = json.dumps(metadata)
            self._redis.hset(key, mapping=mapping)
            self._redis.expire(key, self.ttl_seconds)
        except self._conn_exc:
            pass

    def flush(self) -> None:
        """Remove all entries with this cache prefix (for testing)."""
        try:
            for key in self._redis.scan_iter(f"{self.prefix}*"):
                self._redis.delete(key)
        except Exception:
            pass

    def close(self) -> None:
        """Close Redis connection."""
        if self._redis is not None:
            self._redis.close()

    @staticmethod
    def _query_hash(query: str) -> str:
        """Deterministic short hash for a query string."""
        return hashlib.md5(query.lower().strip().encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Hybrid cache — Redis with automatic in-memory fallback
# ---------------------------------------------------------------------------


class HybridCache:
    """Wraps SharedRedisCache with automatic fallback to in-memory ResponseCache.

    If Redis is unavailable, all traffic is routed through the local in-memory
    cache.  Health is re-checked every HEALTH_CHECK_INTERVAL seconds so the
    gateway automatically recovers shared state when Redis comes back online.
    """

    HEALTH_CHECK_INTERVAL: float = 30.0

    def __init__(self, redis_cache: SharedRedisCache, memory_cache: ResponseCache):
        self.redis_cache = redis_cache
        self.memory_cache = memory_cache
        self._last_ping: float = 0.0
        self._redis_healthy: bool = redis_cache.ping()

    @property
    def false_hit_log(self) -> list[dict[str, object]]:
        return self.redis_cache.false_hit_log + self.memory_cache.false_hit_log

    def _check_health(self) -> bool:
        now = time.time()
        if now - self._last_ping >= self.HEALTH_CHECK_INTERVAL:
            self._redis_healthy = self.redis_cache.ping()
            self._last_ping = now
        return self._redis_healthy

    def get(self, query: str) -> tuple[str | None, float]:
        if self._check_health():
            return self.redis_cache.get(query)
        return self.memory_cache.get(query)

    def set(self, query: str, value: str, metadata: dict[str, str] | None = None) -> None:
        if self._check_health():
            self.redis_cache.set(query, value, metadata)
        else:
            self.memory_cache.set(query, value, metadata)
