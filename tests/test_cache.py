import time

from app.cache import LRUShard, ShardCache


class FakeRedis:
    def __init__(self):
        self.store = {}

    def set(self, key, value, ex=None):
        self.store[key] = value.encode() if isinstance(value, str) else value

    def get(self, key):
        return self.store.get(key)

    def delete(self, key):
        self.store.pop(key, None)

    def keys(self, pattern="*"):
        return [k.encode() for k in self.store]


def test_lru_evicts_least_recently_used():
    shard = LRUShard(max_size=2)
    shard.set("a", 1)
    shard.set("b", 2)
    shard.get("a")          # a is now most recent
    shard.set("c", 3)       # evicts b
    assert shard.get("b") is None
    assert shard.get("a") == 1 and shard.get("c") == 3


def test_ttl_expires_keys():
    shard = LRUShard()
    shard.set("k", "v", ttl=1)
    assert shard.get("k") == "v"
    shard.cache["k"] = ("v", time.time() - 1)  # force expiry
    assert shard.get("k") is None


def test_set_get_delete_roundtrip():
    cache = ShardCache(num_shards=4)
    cache.set("x", "1")
    assert cache.get("x") == "1"
    assert cache.delete("x") is True
    assert cache.get("x") is None


def test_write_through_and_recovery_from_redis():
    redis = FakeRedis()
    cache = ShardCache(num_shards=4, redis_client=redis)
    cache.set("persisted", "yes")
    assert "persisted" in redis.store
    # Simulate a crash: new process, empty memory, same Redis.
    restarted = ShardCache(num_shards=4, redis_client=redis)
    restarted.load_from_redis()
    assert restarted.get("persisted") == "yes"


def test_add_shard_moves_only_remapped_keys_and_keeps_data():
    cache = ShardCache(num_shards=4, max_size_per_shard=10_000)
    keys = [f"k{i}" for i in range(10_000)]
    for k in keys:
        cache.set(k, k)
    result = cache.add_shard()
    assert result["keys_total"] == 10_000
    assert 0.15 < result["keys_moved"] / result["keys_total"] < 0.25
    assert all(cache.get(k) == k for k in keys)
    assert cache.get_stats()["total_shards"] == 5
