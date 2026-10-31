from collections import Counter

import pytest

from app.hashring import ConsistentHashRing, stable_hash

KEYS = [f"user:{i}" for i in range(20_000)]


def test_stable_hash_is_deterministic():
    assert stable_hash("abc") == stable_hash("abc")
    assert stable_hash("abc") != stable_hash("abd")


def test_same_key_always_maps_to_same_node():
    ring = ConsistentHashRing(range(4))
    assert all(ring.get_node(k) == ring.get_node(k) for k in KEYS[:1000])


def test_adding_a_node_moves_about_one_fifth_of_keys():
    ring = ConsistentHashRing(range(4), vnodes=150)
    before = {k: ring.get_node(k) for k in KEYS}
    ring.add_node(4)
    moved = sum(1 for k in KEYS if ring.get_node(k) != before[k])
    # Ideal is 1/5 = 20%; allow slack for hash variance.
    assert 0.15 < moved / len(KEYS) < 0.25
    # Every moved key must have moved to the new node, never between old nodes.
    assert all(ring.get_node(k) == 4 for k in KEYS if ring.get_node(k) != before[k])


def test_mod_n_baseline_moves_most_keys():
    before = {k: stable_hash(k) % 4 for k in KEYS}
    moved = sum(1 for k in KEYS if stable_hash(k) % 5 != before[k])
    assert moved / len(KEYS) > 0.75


def test_vnodes_keep_load_balanced():
    ring = ConsistentHashRing(range(4), vnodes=150)
    counts = Counter(ring.get_node(k) for k in KEYS)
    ideal = len(KEYS) / 4
    assert max(abs(c - ideal) / ideal for c in counts.values()) < 0.15


def test_remove_node_only_moves_its_keys():
    ring = ConsistentHashRing(range(4))
    before = {k: ring.get_node(k) for k in KEYS}
    ring.remove_node(2)
    for k in KEYS:
        if before[k] != 2:
            assert ring.get_node(k) == before[k]
        else:
            assert ring.get_node(k) != 2


def test_errors():
    with pytest.raises(LookupError):
        ConsistentHashRing().get_node("x")
    ring = ConsistentHashRing([0])
    with pytest.raises(ValueError):
        ring.add_node(0)
    with pytest.raises(KeyError):
        ring.remove_node(9)
