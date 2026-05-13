"""Compare sequential (concurrency=1) vs concurrent (concurrency=10) load runs."""
from __future__ import annotations

from pathlib import Path

from reliability_lab.chaos import load_queries, run_scenario
from reliability_lab.config import ScenarioConfig, load_config


def _delta(before: float, after: float) -> str:
    if before == 0:
        return "N/A"
    pct = (after - before) / before * 100
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.1f}%"


def main() -> None:
    config = load_config("configs/default.yaml")
    queries = load_queries()
    scenario = ScenarioConfig(name="all_healthy", description="concurrency comparison baseline")

    print("Running concurrency=1 …")
    c1_config = config.model_copy(update={"load_test": config.load_test.model_copy(update={"concurrency": 1})})
    m1 = run_scenario(c1_config, queries, scenario)

    print("Running concurrency=10 …")
    c10_config = config.model_copy(update={"load_test": config.load_test.model_copy(update={"concurrency": 10})})
    m10 = run_scenario(c10_config, queries, scenario)

    rows = [
        ("latency_p50_ms", m1.percentile(50),  m10.percentile(50),  2),
        ("latency_p95_ms", m1.percentile(95),  m10.percentile(95),  2),
        ("latency_p99_ms", m1.percentile(99),  m10.percentile(99),  2),
        ("availability",   m1.availability,    m10.availability,    4),
        ("error_rate",     m1.error_rate,       m10.error_rate,      4),
        ("cache_hit_rate", m1.cache_hit_rate,  m10.cache_hit_rate,  4),
        ("estimated_cost", m1.estimated_cost,  m10.estimated_cost,  6),
    ]

    lines = [
        "# Concurrency Comparison Report\n",
        f"Requests per run: {m1.total_requests} | Scenario: {scenario.name}\n",
        "| Metric | concurrency=1 | concurrency=10 | Delta |",
        "|---|---:|---:|---:|",
    ]
    for name, v1, v10, dec in rows:
        lines.append(f"| {name} | {v1:.{dec}f} | {v10:.{dec}f} | {_delta(v1, v10)} |")

    report = "\n".join(lines)
    Path("reports").mkdir(exist_ok=True)
    out = Path("reports/concurrency_comparison.md")
    out.write_text(report, encoding="utf-8")
    print("\n" + report)
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
