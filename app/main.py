import asyncio
import logging
import os
from contextlib import asynccontextmanager

import redis
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import Response

from .cache import ShardCache
from .metrics import cache_hits, cache_misses, get_metrics, http_requests_total, rate_limit_rejections
from .ratelimiter import TokenBucketLimiter

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

redis_client = None
cache = None
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
NUM_SHARDS = int(os.getenv("NUM_SHARDS", "4"))
VNODES = int(os.getenv("VNODES", "150"))
RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "true").lower() == "true"
rate_limiter = TokenBucketLimiter(
    capacity=int(os.getenv("RATE_LIMIT_CAPACITY", "20")),
    refill_rate=float(os.getenv("RATE_LIMIT_REFILL_PER_SEC", "10")),
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis_client, cache
    # Startup
    try:
        redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0, decode_responses=False)
        redis_client.ping()
        logger.info("✅ Connected to Redis successfully")
    except Exception as e:
        logger.warning(f"⚠️ Could not connect to Redis: {e}. Running in memory-only mode.")
        redis_client = None

    cache = ShardCache(num_shards=NUM_SHARDS, max_size_per_shard=500,
                       redis_client=redis_client, vnodes=VNODES)
    if redis_client:
        cache.load_from_redis()

    # Periodic background sync (optional)
    async def periodic_sync():
        while True:
            await asyncio.sleep(60)
            logger.info("Periodic sync check completed")

    asyncio.create_task(periodic_sync())

    yield

    # Shutdown
    logger.info("Shutting down... Final sync")
    if redis_client:
        try:
            redis_client.bgsave()
        except redis.RedisError:
            pass
        redis_client.close()

app = FastAPI(title="ShardCache", version="1.1.0", lifespan=lifespan)

def rate_limit(request: Request):
    if not RATE_LIMIT_ENABLED:
        return "disabled"
    client_ip = request.client.host if request.client else "unknown"
    if not rate_limiter.allow_request(client_ip):
        rate_limit_rejections.labels(identifier=client_ip).inc()
        raise HTTPException(status_code=429, detail="Too Many Requests")
    return client_ip

@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    response = await call_next(request)
    http_requests_total.labels(
        method=request.method,
        endpoint=request.url.path,
        status=response.status_code
    ).inc()
    return response

@app.post("/set")
async def set_key(key: str, value: str, ttl: int = 0, _: str = Depends(rate_limit)):
    cache.set(key, value, ttl)
    return {"status": "ok", "key": key, "persisted_to_redis": bool(redis_client)}

@app.get("/get/{key}")
async def get_key(key: str, _: str = Depends(rate_limit)):
    value = cache.get(key)
    if value is None:
        cache_misses.inc()
        raise HTTPException(status_code=404, detail="Key not found or expired")
    cache_hits.inc()
    return {"key": key, "value": value}

@app.delete("/delete/{key}")
async def delete_key(key: str, _: str = Depends(rate_limit)):
    deleted = cache.delete(key)
    return {"status": "ok", "deleted": deleted}

@app.post("/shards")
async def add_shard():
    """Scale out by one shard; only keys whose ring segment changed are moved."""
    return cache.add_shard()

@app.get("/health")
async def health():
    return {"status": "ok", "redis": bool(redis_client)}

@app.get("/stats")
async def get_stats():
    return cache.get_stats()

@app.get("/metrics")
async def metrics():
    return Response(content=get_metrics(), media_type="text/plain")

@app.post("/snapshot")
async def trigger_snapshot():
    if redis_client:
        try:
            redis_client.bgsave()
            return {"status": "Background save to Redis triggered"}
        except Exception as e:
            return {"error": str(e)}
    return {"status": "Redis not connected"}
