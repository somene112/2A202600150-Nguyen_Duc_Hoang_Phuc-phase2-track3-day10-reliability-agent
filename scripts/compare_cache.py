"""Run two chaos simulations (cache on vs off) and emit comparison artifacts."""
from __future__ import annotations

from pathlib import Path

from reliability_lab.chaos import load_queries, run_simulation
from reliability_lab.config import LabConfig, load_config


def _with_cache(config: LabConfig, enabled: bool) -> LabConfig:
    updated_cache = config.cache.model_copy(update={"enabled": enabled})
    return config.model_copy(update={"cache": updated_cache})


def _delta(before: float, after: float) -> str:
    if before == 0:
        return "N/A"
    pct = (after - before) / before * 100
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.1f}%"


def _fmt(v: float, decimals: int = 2) -> str:
    return f"{v:.{decimals}f}"


def main() -> None:
    config = load_config("configs/default.yaml")
    queries = load_queries()
    Path("reports").mkdir(exist_ok=True)

    print("Running WITHOUT cache ...")
    m_off = run_simulation(_with_cache(config, enabled=False), queries)
    m_off.write_json("reports/metrics_no_cache.json")

    print("Running WITH cache ...")
    m_on = run_simulation(_with_cache(config, enabled=True), queries)
    m_on.write_json("reports/metrics_with_cache.json")

    rows: list[tuple[str, float, float, int]] = [
        ("latency_p50_ms", m_off.percentile(50), m_on.percentile(50), 2),
        ("latency_p95_ms", m_off.percentile(95), m_on.percentile(95), 2),
        ("latency_p99_ms", m_off.percentile(99), m_on.percentile(99), 2),
        ("estimated_cost", m_off.estimated_cost, m_on.estimated_cost, 6),
        ("cache_hit_rate", m_off.cache_hit_rate, m_on.cache_hit_rate, 4),
        ("availability", m_off.availability, m_on.availability, 4),
        ("error_rate", m_off.error_rate, m_on.error_rate, 4),
    ]

    lines = [
        "# Cache Comparison Report\n",
        f"Total requests per run: {m_off.total_requests} (cache off) / "
        f"{m_on.total_requests} (cache on)\n",
        "| Metric | Without cache | With cache | Delta |",
        "|---|---:|---:|---:|",
    ]
    for name, off, on, dec in rows:
        lines.append(f"| {name} | {_fmt(off, dec)} | {_fmt(on, dec)} | {_delta(off, on)} |")

    lines += [
        "",
        "## Configuration",
        "",
        "| Setting | Value | Rationale |",
        "|---|---|---|",
        f"| `similarity_threshold` | {config.cache.similarity_threshold} | "
        "0.85 caused false hits on year-sensitive queries; 0.92 eliminates them |",
        f"| `ttl_seconds` | {config.cache.ttl_seconds} | "
        "5-min freshness for FAQ queries; long enough for session reuse, "
        "short enough for time-sensitive answers |",
        f"| `backend` | {config.cache.backend} | "
        "in-memory for single instance; switch to `redis` for multi-instance shared state |",
    ]

    report = "\n".join(lines)
    out = Path("reports/cache_comparison.md")
    out.write_text(report, encoding="utf-8")

    print("\n" + report)
    print(f"\nWrote {out}")
    print("Wrote reports/metrics_no_cache.json")
    print("Wrote reports/metrics_with_cache.json")


if __name__ == "__main__":
    main()
