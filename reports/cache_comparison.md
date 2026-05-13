# Cache Comparison Report

Total requests per run: 1400 (cache off) / 1400 (cache on)

| Metric | Without cache | With cache | Delta |
|---|---:|---:|---:|
| latency_p50_ms | 280.23 | 0.52 | -99.8% |
| latency_p95_ms | 502.78 | 447.06 | -11.1% |
| latency_p99_ms | 535.41 | 518.87 | -3.1% |
| estimated_cost | 0.456022 | 0.215932 | -52.6% |
| cache_hit_rate | 0.0000 | 0.4514 | N/A |
| availability | 0.8293 | 0.8479 | +2.2% |
| error_rate | 0.1707 | 0.1521 | -10.9% |

## Configuration

| Setting | Value | Rationale |
|---|---|---|
| `similarity_threshold` | 0.92 | 0.85 caused false hits on year-sensitive queries; 0.92 eliminates them |
| `ttl_seconds` | 300 | 5-min freshness for FAQ queries; long enough for session reuse, short enough for time-sensitive answers |
| `backend` | memory | in-memory for single instance; switch to `redis` for multi-instance shared state |