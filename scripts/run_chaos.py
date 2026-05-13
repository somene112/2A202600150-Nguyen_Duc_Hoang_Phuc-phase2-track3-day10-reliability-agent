from __future__ import annotations

import argparse
import json
from pathlib import Path

from prometheus_client import generate_latest  # type: ignore[import-untyped]

from reliability_lab.chaos import load_queries, run_cache_comparison, run_simulation
from reliability_lab.config import load_config
from reliability_lab.slo import check_slos, format_slo_table


def _prometheus_summary() -> dict[str, int]:
    """Return sample counts for the custom Prometheus metric families."""
    prefixes = (
        "agent_requests",
        "agent_latency",
        "cache_hits",
        "circuit_state",
        "cost_cap",
        "estimated_cost",
    )
    summary = dict.fromkeys(prefixes, 0)
    metrics_text = generate_latest().decode("utf-8")
    for line in metrics_text.splitlines():
        if not line or line.startswith("#"):
            continue
        for prefix in prefixes:
            if line.startswith(prefix):
                summary[prefix] += 1
                break
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/default.yaml")
    parser.add_argument("--out", default="reports/metrics.json")
    parser.add_argument("--transitions", default="reports/circuit_transitions.txt")
    parser.add_argument(
        "--compare-cache",
        action="store_true",
        help="Run cache-off vs cache-on comparison and write reports/cache_comparison.md",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    queries = load_queries()

    if args.compare_cache:
        print("Running cache comparison (off vs on) ...")
        m_off, m_on = run_cache_comparison(config, queries)

        def _delta(before: float, after: float) -> str:
            if before == 0:
                return "N/A"
            pct = (after - before) / before * 100
            sign = "+" if pct >= 0 else ""
            return f"{sign}{pct:.1f}%"

        rows = [
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
            lines.append(f"| {name} | {off:.{dec}f} | {on:.{dec}f} | {_delta(off, on)} |")
        report = "\n".join(lines)
        Path("reports").mkdir(exist_ok=True)
        out_md = Path("reports/cache_comparison.md")
        out_md.write_text(report, encoding="utf-8")
        print("\n" + report)
        print(f"\nWrote {out_md}")
        return

    metrics = run_simulation(config, queries)
    metrics.prometheus_metrics = _prometheus_summary()
    metrics.write_json(args.out)
    print(f"wrote {args.out}")

    if metrics.transition_logs:
        Path(args.transitions).write_text(
            json.dumps(metrics.transition_logs, indent=2, ensure_ascii=False)
        )
        print(f"wrote {args.transitions} ({len(metrics.transition_logs)} transitions)")
    else:
        print("no circuit transitions recorded")

    false_hits_path = Path("reports/false_hits.jsonl")
    Path("reports").mkdir(exist_ok=True)
    false_hit_lines = [json.dumps(entry, ensure_ascii=False) for entry in metrics.false_hit_log]
    false_hits_path.write_text("\n".join(false_hit_lines), encoding="utf-8")
    print(f"wrote {false_hits_path} ({len(false_hit_lines)} blocked candidates)")

    slo_results = check_slos(metrics)
    slo_table = format_slo_table(slo_results)

    slo_lines = [
        "# SLO Report\n",
        f"> Generated from {args.out} - {metrics.total_requests} total requests "
        f"across {len(metrics.scenarios)} scenarios\n",
        "> Note: aggregate metrics span all chaos scenarios including intentional-failure ones.\n",
        slo_table,
        "",
        "## Per-scenario pass/fail",
        "",
        "| Scenario | Result |",
        "|---|---|",
    ]
    for name, verdict in metrics.scenarios.items():
        icon = "PASS" if verdict == "pass" else "FAIL"
        slo_lines.append(f"| {name} | {icon} |")

    slo_report = "\n".join(slo_lines)
    slo_path = Path("reports/slo_report.md")
    slo_path.write_text(slo_report, encoding="utf-8")
    print(f"wrote {slo_path}")

    print("\n" + slo_table)
    print("\nScenario results:")
    for name, verdict in metrics.scenarios.items():
        icon = "PASS" if verdict == "pass" else "FAIL"
        print(f"  [{icon}] {name}")


if __name__ == "__main__":
    main()
