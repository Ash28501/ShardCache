"""Consistent hash ring with virtual nodes.

Each physical shard is placed on the ring many times ("virtual nodes"), so keys
spread evenly and adding or removing a shard only remaps the keys that fall in
the affected ring segments (about 1/N of them), instead of nearly all keys as
with ``hash(key) % N``.

A stable hash (MD5) is used rather than Python's built-in ``hash()``, which is
randomized per process and would send the same key to different shards after a
restart.
"""
from __future__ import annotations

import bisect
import hashlib
from typing import Dict, Hashable, Iterable, List


def stable_hash(value: str) -> int:
    """64-bit stable hash of a string."""
    return int.from_bytes(hashlib.md5(value.encode("utf-8")).digest()[:8], "big")


class ConsistentHashRing:
    def __init__(self, nodes: Iterable[Hashable] = (), vnodes: int = 150):
        if vnodes < 1:
            raise ValueError("vnodes must be >= 1")
        self.vnodes = vnodes
        self._ring: List[int] = []          # sorted vnode hashes
        self._owners: Dict[int, Hashable] = {}  # vnode hash -> node
        self._nodes: List[Hashable] = []
        for node in nodes:
            self.add_node(node)

    @property
    def nodes(self) -> List[Hashable]:
        return list(self._nodes)

    def add_node(self, node: Hashable) -> None:
        if node in self._nodes:
            raise ValueError(f"node {node!r} already on the ring")
        self._nodes.append(node)
        for i in range(self.vnodes):
            h = stable_hash(f"{node}#vnode{i}")
            # Collisions are astronomically unlikely with 64-bit hashes; skip if one occurs.
            if h in self._owners:
                continue
            self._owners[h] = node
            bisect.insort(self._ring, h)

    def remove_node(self, node: Hashable) -> None:
        if node not in self._nodes:
            raise KeyError(node)
        self._nodes.remove(node)
        dead = [h for h, owner in self._owners.items() if owner == node]
        for h in dead:
            del self._owners[h]
        dead_set = set(dead)
        self._ring = [h for h in self._ring if h not in dead_set]

    def get_node(self, key: str) -> Hashable:
        if not self._ring:
            raise LookupError("hash ring is empty")
        h = stable_hash(key)
        idx = bisect.bisect_right(self._ring, h)
        if idx == len(self._ring):
            idx = 0  # wrap around the ring
        return self._owners[self._ring[idx]]
