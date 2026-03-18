import redis.asyncio as redis

from app.config import REDIS_URL

pool: redis.Redis | None = None


async def init_redis():
    global pool
    pool = redis.from_url(REDIS_URL, decode_responses=True)
    await pool.ping()


async def close_redis():
    global pool
    if pool:
        await pool.aclose()
        pool = None


def get_redis() -> redis.Redis:
    if pool is None:
        raise RuntimeError("Redis not initialized. Call init_redis() first.")
    return pool
