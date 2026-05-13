"""Run one chaos simulation, then expose Prometheus metrics through FastAPI.

Usage:
    python scripts/serve_metrics.py            # run simulation + serve /metrics
    python scripts/serve_metrics.py --once     # run simulation + print metrics text + exit
"""
from __future__ import annotations

import argparse

import uvicorn  # type: ignore[import-untyped]
from fastapi import FastAPI, Response  # type: ignore[import-untyped]
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest  # type: ignore[import-untyped]

from reliability_lab.chaos import load_queries, run_simulation
from reliability_lab.config import load_config

app = FastAPI(title="Reliability Lab Metrics")


@app.get("/metrics")
def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


def _populate_metrics(config_path: str) -> None:
    config = load_config(config_path)
    queries = load_queries()
    print("Running chaos simulation to populate metrics...")
    run_metrics = run_simulation(config, queries)
    print(f"  {run_metrics.total_requests} requests processed")
    print(
        f"  availability={run_metrics.availability:.2%}  "
        f"cache_hit_rate={run_metrics.cache_hit_rate:.2%}"
    )
    print(f"  scenarios: {run_metrics.scenarios}")


def _print_custom_metrics() -> None:
    metrics_text = generate_latest().decode("utf-8")
    print("\n--- Prometheus metrics ---")
    for line in metrics_text.splitlines():
        if any(
            line.startswith(metric_prefix)
            for metric_prefix in (
                "agent_requests",
                "agent_latency",
                "cache_hits",
                "circuit_state",
                "cost_cap",
                "estimated_cost",
                "#",
            )
        ):
            print(line)


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve Prometheus metrics after chaos simulation")
    parser.add_argument("--config", default="configs/default.yaml")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--once",
        action="store_true",
        help="Print metrics text and exit (no HTTP server)",
    )
    args = parser.parse_args()

    _populate_metrics(args.config)
    if args.once:
        _print_custom_metrics()
        return

    print(f"\nMetrics server started: http://{args.host}:{args.port}/metrics")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
