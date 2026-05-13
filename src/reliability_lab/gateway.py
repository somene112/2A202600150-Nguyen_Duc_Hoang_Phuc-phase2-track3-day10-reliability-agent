from __future__ import annotations

import time
from dataclasses import dataclass

from reliability_lab.cache import HybridCache, ResponseCache, SharedRedisCache
from reliability_lab.circuit_breaker import CircuitBreaker, CircuitOpenError, CircuitState
from reliability_lab.prometheus_metrics import (
    agent_latency_seconds,
    agent_requests_total,
    cache_hits_total,
    circuit_state,
    cost_cap_skips_total,
    estimated_cost_saved_usd,
    estimated_cost_usd,
)
from reliability_lab.providers import FakeLLMProvider, ProviderError, ProviderResponse

_CIRCUIT_STATE_VALUE: dict[CircuitState, float] = {
    CircuitState.CLOSED: 0.0,
    CircuitState.HALF_OPEN: 1.0,
    CircuitState.OPEN: 2.0,
}


@dataclass(slots=True)
class GatewayResponse:
    text: str
    route: str
    provider: str | None
    cache_hit: bool
    latency_ms: float
    estimated_cost: float
    error: str | None = None


class ReliabilityGateway:
    """Routes requests through cache, circuit breakers, and fallback providers."""

    EXPENSIVE_COST_THRESHOLD: float = 0.008

    def __init__(
        self,
        providers: list[FakeLLMProvider],
        breakers: dict[str, CircuitBreaker],
        cache: HybridCache | ResponseCache | SharedRedisCache | None = None,
        cost_budget_usd: float = 1.0,
    ):
        self.providers = providers
        self.breakers = breakers
        self.cache = cache
        self.cumulative_cost: float = 0.0
        self.cost_budget_usd = cost_budget_usd
        self.cost_cap_skips: int = 0

    def complete(self, prompt: str) -> GatewayResponse:
        """Return a reliable response or a static fallback, recording Prometheus metrics.

        Route reasons: primary:<name>, fallback:<name>, cache_hit:<score>,
        static_fallback:<error_brief>.
        Expensive providers are skipped when cumulative_cost > cost_budget_usd.
        """
        t_start = time.perf_counter()
        resp = self._route(prompt, t_start)
        self._record_metrics(resp)
        return resp

    # ------------------------------------------------------------------
    # Internal routing logic
    # ------------------------------------------------------------------

    def _route(self, prompt: str, t_start: float) -> GatewayResponse:
        if self.cache is not None:
            cached, score = self.cache.get(prompt)
            if cached is not None:
                latency_ms = (time.perf_counter() - t_start) * 1000
                return GatewayResponse(cached, f"cache_hit:{score:.2f}", None, True, latency_ms, 0.0)

        last_error: str | None = None
        for i, provider in enumerate(self.providers):
            if (
                self.cumulative_cost > self.cost_budget_usd
                and provider.cost_per_1k_tokens > self.EXPENSIVE_COST_THRESHOLD
            ):
                last_error = "cost_cap_exceeded"
                self.cost_cap_skips += 1
                cost_cap_skips_total.labels(provider=provider.name).inc()
                continue

            breaker = self.breakers[provider.name]
            try:
                response: ProviderResponse = breaker.call(provider.complete, prompt)
                if self.cache is not None:
                    self.cache.set(prompt, response.text, {"provider": provider.name})
                self.cumulative_cost += response.estimated_cost
                estimated_cost_usd.labels(provider=provider.name).set(self.cumulative_cost)
                route = f"primary:{provider.name}" if i == 0 else f"fallback:{provider.name}"
                latency_ms = (time.perf_counter() - t_start) * 1000
                return GatewayResponse(
                    text=response.text,
                    route=route,
                    provider=provider.name,
                    cache_hit=False,
                    latency_ms=latency_ms,
                    estimated_cost=response.estimated_cost,
                )
            except (ProviderError, CircuitOpenError) as exc:
                last_error = str(exc)
                continue

        latency_ms = (time.perf_counter() - t_start) * 1000
        brief = (last_error or "all_providers_failed")[:40]
        return GatewayResponse(
            text="The service is temporarily degraded. Please try again soon.",
            route=f"static_fallback:{brief}",
            provider=None,
            cache_hit=False,
            latency_ms=latency_ms,
            estimated_cost=0.0,
            error=last_error,
        )

    def _record_metrics(self, resp: GatewayResponse) -> None:
        route_type = resp.route.split(":")[0] if ":" in resp.route else resp.route
        provider_label = resp.provider or "none"

        agent_requests_total.labels(route=route_type, provider=provider_label).inc()
        agent_latency_seconds.labels(route=route_type).observe(resp.latency_ms / 1000.0)

        if resp.cache_hit:
            cache_hits_total.labels(backend="memory").inc()
            estimated_cost_saved_usd.inc(0.001)

        # Reflect current circuit state in gauges after every call
        for name, breaker in self.breakers.items():
            circuit_state.labels(provider=name).set(_CIRCUIT_STATE_VALUE[breaker.state])
