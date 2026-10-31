# ShardCache

**A sharded in-memory key-value store with Redis persistence, rate limiting, and observability**, built with FastAPI and Python.

ShardCache is a small hybrid cache: fast LRU shards in memory, backed by Redis for durability. It shows how sharding, eviction, persistence, and production features fit together.

## Features

- **Consistent hashing with virtual nodes** (150 per shard by default) using a stable MD5-based hash. Adding a shard moves about 1/(N+1) of the keys, while `hash(key) % N` moves almost all of them (see [Benchmarks](#benchmarks)).
- **Online scale-out:** `POST /shards` adds a shard and migrates only the keys whose ring position changed.
- **LRU eviction** with per-key TTL, using `OrderedDict` for O(1) operations.
- **Token-bucket rate limiting** per client IP, with burst and sustained rates set through env vars.
- **Write-through persistence to Redis.** The cache reloads from Redis on startup, so it recovers after a crash.
- **Prometheus metrics** for requests, cache hits and misses, and rate-limit rejections, plus a provisioned **Grafana** dashboard.
- **Graceful fallback:** keeps serving from memory if Redis is unavailable.
- **CI/CD:** a `Jenkinsfile` runs lint (Ruff), unit tests (pytest), the benchmark, the image build, and the deploy.

## Tech Stack

Python 3.12 · FastAPI + Uvicorn · Redis · Prometheus + Grafana · Docker Compose · Jenkins · pytest · k6

## Quick Start

```bash
git clone https://github.com/Ash28501/ShardCache.git
cd ShardCache
docker compose up --build
```

| URL | What it is |
|---|---|
| http://localhost:8000/docs | API (Swagger) |
| http://localhost:8000/metrics | Prometheus metrics |
| http://localhost:9090 | Prometheus |
| http://localhost:3000 | Grafana → ShardCache dashboard |

```bash
curl -X POST "http://localhost:8000/set?key=user:1&value=alice&ttl=300"
curl http://localhost:8000/get/user:1
curl -X POST http://localhost:8000/shards      # scale out: {"keys_moved": ..., "keys_total": ...}
curl http://localhost:8000/stats
```

### Configuration

| Env var | Default | Meaning |
|---|---|---|
| `REDIS_HOST` / `REDIS_PORT` | `localhost` / `6379` | Redis location (`redis` in Compose) |
| `NUM_SHARDS` | `4` | Initial shard count |
| `VNODES` | `150` | Virtual nodes per shard |
| `RATE_LIMIT_ENABLED` | `true` | Set `false` for load tests |
| `RATE_LIMIT_CAPACITY` / `RATE_LIMIT_REFILL_PER_SEC` | `20` / `10` | Token bucket burst / sustained rate |

## Benchmarks

`python -m bench.bench_sharding` uses 100,000 keys. These are the measured results on Python 3.13, a 2-vCPU Intel Xeon at 2.1 GHz:

| Scenario | Consistent hashing | mod-N | Ideal |
|---|---:|---:|---:|
| Keys remapped, 4 → 5 shards | **20.6%** | 79.9% | 20.0% |
| Keys remapped, 8 → 9 shards | **9.9%** | 88.9% | 11.1% |

| Virtual nodes per shard | Worst shard's deviation from even load |
|---:|---:|
| 1 | 93.4% |
| 10 | 20.2% |
| 150 | **9.9%** |

In-process cache throughput (80% get / 20% set, single thread): **~589K ops/sec, p50 1.2 µs, p99 4.8 µs**.

### HTTP load test (k6)

```bash
RATE_LIMIT_ENABLED=false docker compose up -d --build
k6 run loadtest/k6-shardcache.js            # VUS=50 DURATION=60s by default
```

k6 reports requests/sec, p50/p95/p99 latency, and error rate. Record your results here with your hardware.

## Tests

```bash
pip install pytest && pytest -q    # 15 tests: hash ring, LRU/TTL, Redis recovery, rebalancing, rate limiter
```

## Project Structure

```text
app/
  hashring.py     consistent hash ring with virtual nodes
  cache.py        LRU shards, write-through Redis, online rebalancing
  ratelimiter.py  token bucket per client
  metrics.py      Prometheus counters
  main.py         FastAPI app
bench/            sharding benchmark
loadtest/         k6 script
monitoring/       Prometheus config + Grafana provisioning and dashboard
tests/            pytest suite
Jenkinsfile       lint → test → benchmark → build → deploy
```
