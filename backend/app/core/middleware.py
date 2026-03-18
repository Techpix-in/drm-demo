import hashlib
import time

from fastapi import HTTPException, Request

from app.config import (
    LOGIN_RATE_LIMIT,
    LOGIN_RATE_WINDOW,
    OTP_RATE_LIMIT,
    OTP_RATE_WINDOW,
    LICENSE_RATE_LIMIT,
    LICENSE_RATE_WINDOW,
)
from app.models.schemas import SessionUser
from app.db.redis import get_redis


async def _check_rate_limit(key: str, limit: int, window: int) -> tuple[bool, int]:
    """Redis sliding window rate limiter."""
    r = get_redis()
    now = time.time()
    cutoff = now - window

    pipe = r.pipeline()
    pipe.zremrangebyscore(key, 0, cutoff)
    pipe.zcard(key)
    pipe.zadd(key, {str(now): now})
    pipe.expire(key, window + 10)
    results = await pipe.execute()

    current_count = results[1]
    if current_count >= limit:
        await r.zrem(key, str(now))
        oldest = await r.zrange(key, 0, 0, withscores=True)
        retry = max(1, int(window - (now - oldest[0][1]))) if oldest else window
        return False, retry

    return True, 0


def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def get_device_fingerprint(request: Request) -> str:
    fingerprint = request.headers.get("X-Device-Fingerprint")
    if fingerprint:
        return fingerprint

    ua = request.headers.get("User-Agent", "")
    ip = get_client_ip(request)
    raw = f"{ua}:{ip}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


async def check_login_rate_limit(request: Request) -> None:
    ip = get_client_ip(request)
    key = f"ratelimit:login:{ip}"
    allowed, retry = await _check_rate_limit(key, LOGIN_RATE_LIMIT, LOGIN_RATE_WINDOW)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Too many login attempts. Try again in {retry} seconds.",
            headers={"Retry-After": str(retry)},
        )


async def check_otp_rate_limit(request: Request, user: SessionUser) -> None:
    key = f"ratelimit:otp:{user.user_id}"
    allowed, retry = await _check_rate_limit(key, OTP_RATE_LIMIT, OTP_RATE_WINDOW)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Too many playback requests. Try again in {retry} seconds.",
            headers={"Retry-After": str(retry)},
        )


async def check_license_rate_limit(request: Request, user: SessionUser) -> None:
    key = f"ratelimit:license:{user.user_id}"
    allowed, retry = await _check_rate_limit(key, LICENSE_RATE_LIMIT, LICENSE_RATE_WINDOW)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Too many license requests. Try again in {retry} seconds.",
            headers={"Retry-After": str(retry)},
        )
