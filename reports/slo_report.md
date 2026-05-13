# SLO Report

> Generated from reports\metrics.json - 1400 total requests across 7 scenarios

> Note: aggregate metrics span all chaos scenarios including intentional-failure ones.

| SLI | Target | Actual | Met? |
|---|---|---:|---|
| Availability | >= 0.9 | 0.8450 | NO |
| Latency P95 | <= 2500.0 ms | 327.1997 ms | YES |
| Latency P99 | <= 3000.0 ms | 530.6870 ms | YES |
| Cache hit rate | >= 0.1 | 0.4550 | YES |
| Recovery time | <= 5000.0 ms | 3863.6637 ms | YES |
| False hit count | == 0.0 | 0.0000 | YES |

## Per-scenario pass/fail

| Scenario | Result |
|---|---|
| primary_timeout_100 | PASS |
| primary_flaky_50 | PASS |
| all_healthy | PASS |
| recovery_cycle | PASS |
| cache_stale_candidate | PASS |
| backup_also_flaky | PASS |
| cost_cap_scenario | PASS |