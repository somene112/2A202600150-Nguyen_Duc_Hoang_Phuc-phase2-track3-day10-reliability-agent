"""SLO definitions and checker.

Defines named SLOTarget objects and a check_slos() function that
evaluates a RunMetrics snapshot against each target, returning a
list of result dicts suitable for logging or report generation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from reliability_lab.metrics import RunMetrics


@dataclass(frozen=True)
class SLOTarget:
    name: str
    description: str
    metric: str          # attribute name on RunMetrics (or "latency_p95_ms" etc.)
    operator: str        # ">=" | "<=" | "==" | "!="
    threshold: float
    unit: str = ""

    def evaluate(self, metrics: RunMetrics) -> tuple[float | None, bool]:
        """Return (actual_value, met) for this SLO against the given metrics."""
        # latency percentiles aren't stored as plain fields
        if self.metric == "latency_p50_ms":
            actual: float | None = metrics.percentile(50)
        elif self.metric == "latency_p95_ms":
            actual = metrics.percentile(95)
        elif self.metric == "latency_p99_ms":
            actual = metrics.percentile(99)
        else:
            raw: Any = getattr(metrics, self.metric, None)
            actual = float(raw) if raw is not None else None

        if actual is None:
            return None, False

        if self.operator == ">=":
            met = actual >= self.threshold
        elif self.operator == "<=":
            met = actual <= self.threshold
        elif self.operator == "==":
            met = actual == self.threshold
        elif self.operator == "!=":
            met = actual != self.threshold
        else:
            met = False
        return actual, met


# ---------------------------------------------------------------------------
# Default SLO targets
# ---------------------------------------------------------------------------

DEFAULT_SLOS: list[SLOTarget] = [
    SLOTarget(
        name="Availability",
        description="Fraction of requests that received a non-static-fallback response",
        metric="availability",
        operator=">=",
        threshold=0.90,
    ),
    SLOTarget(
        name="Latency P95",
        description="95th-percentile end-to-end latency",
        metric="latency_p95_ms",
        operator="<=",
        threshold=2500.0,
        unit=" ms",
    ),
    SLOTarget(
        name="Latency P99",
        description="99th-percentile end-to-end latency",
        metric="latency_p99_ms",
        operator="<=",
        threshold=3000.0,
        unit=" ms",
    ),
    SLOTarget(
        name="Cache hit rate",
        description="Fraction of requests served from cache",
        metric="cache_hit_rate",
        operator=">=",
        threshold=0.10,
    ),
    SLOTarget(
        name="Recovery time",
        description="Average time from circuit opening to successful close",
        metric="recovery_time_ms",
        operator="<=",
        threshold=5000.0,
        unit=" ms",
    ),
    SLOTarget(
        name="False hit count",
        description="Number of incorrect cache hits due to year/ID mismatch",
        metric="false_hit_count",
        operator="==",
        threshold=0.0,
    ),
]


# ---------------------------------------------------------------------------
# Checker
# ---------------------------------------------------------------------------


def check_slos(
    metrics: RunMetrics,
    targets: list[SLOTarget] | None = None,
) -> list[dict[str, object]]:
    """Evaluate each SLO target against metrics and return a result list.

    Each result dict has keys: name, description, threshold, unit,
    operator, actual, met.
    """
    if targets is None:
        targets = DEFAULT_SLOS
    results: list[dict[str, object]] = []
    for slo in targets:
        actual, met = slo.evaluate(metrics)
        results.append(
            {
                "name": slo.name,
                "description": slo.description,
                "operator": slo.operator,
                "threshold": slo.threshold,
                "unit": slo.unit,
                "actual": actual,
                "met": met,
            }
        )
    return results


def format_slo_table(results: list[dict[str, object]]) -> str:
    """Return a Markdown table string from check_slos() output."""
    lines = [
        "| SLI | Target | Actual | Met? |",
        "|---|---|---:|---|",
    ]
    for r in results:
        op = r["operator"]
        threshold = r["threshold"]
        unit = r["unit"]
        actual = r["actual"]
        met = r["met"]
        target_str = f"{op} {threshold}{unit}"
        actual_str = f"{actual:.4f}{unit}" if isinstance(actual, float) else "N/A"
        icon = "YES" if met else "NO"
        lines.append(f"| {r['name']} | {target_str} | {actual_str} | {icon} |")
    return "\n".join(lines)
