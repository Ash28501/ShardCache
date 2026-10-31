from app.ratelimiter import TokenBucketLimiter


def test_allows_burst_up_to_capacity_then_rejects():
    limiter = TokenBucketLimiter(capacity=5, refill_rate=0.0001)
    results = [limiter.allow_request("ip") for _ in range(7)]
    assert results == [True] * 5 + [False, False]


def test_buckets_are_per_client():
    limiter = TokenBucketLimiter(capacity=1, refill_rate=0.0001)
    assert limiter.allow_request("a") is True
    assert limiter.allow_request("b") is True
    assert limiter.allow_request("a") is False


def test_refills_over_time():
    limiter = TokenBucketLimiter(capacity=1, refill_rate=1000)
    assert limiter.allow_request("ip")
    limiter.buckets["ip"].last_refill -= 0.01  # 10ms later -> 10 tokens, capped at 1
    assert limiter.allow_request("ip")
