from __future__ import annotations

from reliability_lab.cache import ResponseCache


def test_exact_match_returns_1() -> None:
    cache = ResponseCache(ttl_seconds=60, similarity_threshold=0.5)
    cache.set("What is the refund policy?", "Full refund within 30 days.")
    cached, score = cache.get("What is the refund policy?")
    assert cached == "Full refund within 30 days."
    assert score == 1.0


def test_different_years_not_match() -> None:
    cache = ResponseCache(ttl_seconds=60, similarity_threshold=0.3)
    cache.set("policy 2024", "old rules")
    cached, _ = cache.get("policy 2026")
    assert cached is None
    assert len(cache.false_hit_log) == 1
    assert cache.false_hit_log[0]["reason"] == "4-digit number mismatch"


def test_privacy_query_not_cached() -> None:
    cache = ResponseCache(ttl_seconds=60, similarity_threshold=0.5)
    cache.set("account balance for user 42", "Balance: $100")
    assert len(cache._entries) == 0
    cached, score = cache.get("account balance for user 42")
    assert cached is None
    assert score == 0.0


def test_similarity_threshold_tunable() -> None:
    # ResponseCache.similarity("What is Python", "What is python?") ≈ 0.754
    # A loose threshold (0.7) allows this near-match through.
    loose = ResponseCache(ttl_seconds=60, similarity_threshold=0.7)
    loose.set("What is Python", "Python is a language")
    cached, score = loose.get("What is python?")
    assert cached == "Python is a language"
    assert score >= 0.7

    # A tight threshold (0.99) blocks the same pair.
    tight = ResponseCache(ttl_seconds=60, similarity_threshold=0.99)
    tight.set("What is Python", "Python is a language")
    cached, _ = tight.get("What is python?")
    assert cached is None
