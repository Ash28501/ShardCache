import json
import logging
import time
from collections import OrderedDict
from typing import Any, Dict, Optional

from .hashring import ConsistentHashRing

logger = logging.getLogger(__name__)

class LRUShard:
    def __init__(self, max_size: int = 500):
        self.max_size = max_size
        self.cache: OrderedDict = OrderedDict()

    def _is_expired(self, expiry: Optional[float]) -> bool:
        return expiry is not None and expiry < time.time()

    def set(self, key: str, value: Any, ttl: int = 0):
        expiry = time.time() + ttl if ttl > 0 else None
        if key in self.cache:
            self.cache.move_to_end(key)
        self.cache[key] = (value, expiry)
        if len(self.cache) > self.max_size:
            self.cache.popitem(last=False)

    def get(self, key: str) -> Optional[Any]:
        if key not in self.cache:
            return None
        value, expiry = self.cache[key]
        if self._is_expired(expiry):
            del self.cache[key]
            return None
        self.cache.move_to_end(key)
        return value

    def delete(self, key: str) -> bool:
        return self.cache.pop(key, None) is not None

    def size(self) -> int:
        return len(self.cache)


class ShardCache:
    def __init__(self, num_shards: int = 4, max_size_per_shard: int = 500,
                 redis_client=None, vnodes: int = 150):
        self.max_size_per_shard = max_size_per_shard
        self.shards = [LRUShard(max_size_per_shard) for _ in range(num_shards)]
        self.ring = ConsistentHashRing(range(num_shards), vnodes=vnodes)
        self.redis_client = redis_client

    @property
    def num_shards(self) -> int:
        return len(self.shards)

    def _get_shard_index(self, key: str) -> int:
        return self.ring.get_node(key)

    def add_shard(self) -> Dict:
        """Add a shard and move only the keys whose ring position changed.

        Returns how many keys moved, which with consistent hashing is roughly
        1/(N+1) of the keys rather than nearly all of them.
        """
        new_idx = len(self.shards)
        self.shards.append(LRUShard(self.max_size_per_shard))
        self.ring.add_node(new_idx)
        moved = 0
        total = 0
        for idx, shard in enumerate(self.shards[:-1]):
            for key in list(shard.cache.keys()):
                total += 1
                if self.ring.get_node(key) != idx:
                    value, expiry = shard.cache.pop(key)
                    self.shards[new_idx].cache[key] = (value, expiry)
                    moved += 1
        return {"new_shard": new_idx, "keys_moved": moved, "keys_total": total}

    def set(self, key: str, value: Any, ttl: int = 0):
        shard_idx = self._get_shard_index(key)
        self.shards[shard_idx].set(key, value, ttl)

        if self.redis_client:
            try:
                self.redis_client.set(key, json.dumps(value), ex=ttl if ttl > 0 else None)
            except Exception as e:
                logger.warning(f"Redis write failed for {key}: {e}")

    def get(self, key: str) -> Optional[Any]:
        shard_idx = self._get_shard_index(key)
        value = self.shards[shard_idx].get(key)
        if value is not None:
            return value

        if self.redis_client:
            try:
                data = self.redis_client.get(key)
                if data:
                    value = json.loads(data)
                    self.set(key, value, ttl=300)  # Rehydrate
                    return value
            except Exception as e:
                logger.warning(f"Redis read failed for {key}: {e}")
        return None

    def delete(self, key: str) -> bool:
        shard_idx = self._get_shard_index(key)
        deleted = self.shards[shard_idx].delete(key)
        if self.redis_client:
            try:
                self.redis_client.delete(key)
            except Exception:
                pass
        return deleted

    def get_stats(self) -> Dict:
        return {
            "total_shards": self.num_shards,
            "vnodes_per_shard": self.ring.vnodes,
            "shards": [{"shard_id": i, "size": shard.size()} for i, shard in enumerate(self.shards)]
        }

    def load_from_redis(self):
        if not self.redis_client:
            return
        try:
            keys = self.redis_client.keys("*")
            count = 0
            for k in keys:
                key = k.decode('utf-8') if isinstance(k, bytes) else k
                data = self.redis_client.get(k)
                if data:
                    try:
                        value = json.loads(data)
                        self.set(key, value, ttl=300)
                        count += 1
                    except (ValueError, TypeError):
                        pass
            logger.info(f"Loaded {count} keys from Redis")
        except Exception as e:
            logger.error(f"Failed to load from Redis: {e}")
