"""Benchmark: consistent hashing vs mod-N, load balance, and in-process throughput.

Run:  python -m bench.bench_sharding
"""
import platform
import random
import statistics
import time
from collections import Counter

from app.cache import ShardCache
from app.hashring import ConsistentHashRing, stable_hash

N_KEYS = 100_000
KEYS = [f"user:{i}" for i in range(N_KEYS)]


def remap_pct_ring(n, vnodes=150):
    ring = ConsistentHashRing(range(n), vnodes=vnodes)
    before = [ring.get_node(k) for k in KEYS]
    ring.add_node(n)
    return 100 * sum(b != ring.get_node(k) for k, b in zip(KEYS, before, strict=True)) / N_KEYS


def remap_pct_modn(n):
    return 100 * sum(stable_hash(k) % n != stable_hash(k) % (n + 1) for k in KEYS) / N_KEYS


def imbalance_pct(vnodes, n=4):
    ring = ConsistentHashRing(range(n), vnodes=vnodes)
    counts = Counter(ring.get_node(k) for k in KEYS)
    ideal = N_KEYS / n
    return 100 * max(abs(c - ideal) for c in counts.values()) / ideal


def throughput():
    cache = ShardCache(num_shards=4, max_size_per_shard=50_000)
    ops = [(random.random() < 0.2, random.choice(KEYS)) for _ in range(200_000)]  # 80% reads
    lat = []
    start = time.perf_counter()
    for is_write, k in ops:
        t = time.perf_counter()
        if is_write:
            cache.set(k, "v", ttl=300)
        else:
            cache.get(k)
        lat.append(time.perf_counter() - t)
    elapsed = time.perf_counter() - start
    lat.sort()
    return len(ops) / elapsed, lat[len(lat) // 2] * 1e6, lat[int(len(lat) * 0.99)] * 1e6


if __name__ == "__main__":
    print(f"Python {platform.python_version()} on {platform.machine()}, {N_KEYS:,} keys\n")
    print("Keys remapped when adding one shard:")
    for n in (4, 8):
        ring_pct, modn_pct = remap_pct_ring(n), remap_pct_modn(n)
        print(f"  {n}->{n+1} shards: consistent hashing {ring_pct:5.1f}%  |  mod-N {modn_pct:5.1f}%"
              f"  (ideal {100/(n+1):.1f}%)")
    print("\nWorst shard deviation from even load (4 shards):")
    for v in (1, 10, 50, 150):
        print(f"  {v:>3} vnodes/shard: {imbalance_pct(v):5.1f}%")
    runs = [throughput() for _ in range(3)]
    ops = statistics.median(r[0] for r in runs)
    p50 = statistics.median(r[1] for r in runs)
    p99 = statistics.median(r[2] for r in runs)
    print("\nIn-process cache ops (80% get / 20% set, single thread, median of 3 runs):")
    print(f"  {ops:,.0f} ops/sec   p50 {p50:.1f} us   p99 {p99:.1f} us")
