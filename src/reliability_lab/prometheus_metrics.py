from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

# ---------------------------------------------------------------------------
# Request counters
# ---------------------------------------------------------------------------

agent_requests_total: Counter = Counter(
    "agent_requests_total",
    "Total requests processed by the gateway",
    ["route", "provider"],
)

cache_hits_total: Counter = Counter(
    "cache_hits_total",
    "Number of cache hits served without calling a provider",
    ["backend"],
)

cost_cap_skips_total: Counter = Counter(
    "cost_cap_skips_total",
    "Requests skipped because cumulative cost exceeded the budget",
    ["provider"],
)

# ---------------------------------------------------------------------------
# Latency histogram
# ---------------------------------------------------------------------------

agent_latency_seconds: Histogram = Histogram(
    "agent_latency_seconds",
    "End-to-end gateway request latency in seconds",
    ["route"],
    buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

# ---------------------------------------------------------------------------
# Circuit breaker state gauge
# ---------------------------------------------------------------------------

circuit_state: Gauge = Gauge(
    "circuit_state",
    "Current circuit breaker state: 0=closed  1=half_open  2=open",
    ["provider"],
)

# ---------------------------------------------------------------------------
# Cost tracking
# ---------------------------------------------------------------------------

estimated_cost_usd: Gauge = Gauge(
    "estimated_cost_usd",
    "Cumulative estimated cost in USD since gateway init",
    ["provider"],
)

estimated_cost_saved_usd: Counter = Counter(
    "estimated_cost_saved_usd",
    "Estimated USD saved by cache hits (avoided provider calls)",
    [],
)
