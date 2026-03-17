import hashlib
import time
from typing import Dict, List

from fastapi import HTTPException, Request

from config import (
    LOGIN_RATE_LIMIT,
    LOGIN_RATE_WINDOW,
    OTP_RATE_LIMIT,
    OTP_RATE_WINDOW,
)
from models import SessionUser


class InMemoryRateLimiter:
    """Simple in-memory rate limiter using sliding window."""

    def __init__(self):
        self._store: Dict[str, List[float]] = {}

    def check(self, key: str, limit: int, window: int) -> bool:
        """Return True if request is allowed, False if rate-limited."""
        now = time.time()
        cutoff = now - window

        # Prune old entries
        timestamps = self._store.get(key, [])
        timestamps = [t for t in timestamps if t > cutoff]
        self._store[key] = timestamps

        if len(timestamps) >= limit:
            return False

        timestamps.append(now)
        return True

    def remaining(self, key: str, limit: int, window: int) -> int:
        """Return how many requests are left in the current window."""
        now = time.time()
        cutoff = now - window
        timestamps = self._store.get(key, [])
        active = [t for t in timestamps if t > cutoff]
        return max(0, limit - len(active))

    def retry_after(self, key: str, window: int) -> int:
        """Return seconds until the oldest entry in the window expires."""
        timestamps = self._store.get(key, [])
        if not timestamps:
            return 0
        oldest = min(timestamps)
        return max(1, int(window - (time.time() - oldest)))


# Module-level singleton
rate_limiter = InMemoryRateLimiter()


def get_client_ip(request: Request) -> str:
    """Extract client IP, respecting X-Forwarded-For proxy header."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def get_device_fingerprint(request: Request) -> str:
    """
    Extract device fingerprint from header.
    Falls back to hashing User-Agent + IP if header not present.
    """
    fingerprint = request.headers.get("X-Device-Fingerprint")
    if fingerprint:
        return fingerprint

    # Fallback: derive fingerprint from available request data
    ua = request.headers.get("User-Agent", "")
    ip = get_client_ip(request)
    raw = f"{ua}:{ip}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def check_login_rate_limit(request: Request) -> None:
    """FastAPI dependency: rate-limit login attempts by IP."""
    ip = get_client_ip(request)
    key = f"login:{ip}"

    if not rate_limiter.check(key, LOGIN_RATE_LIMIT, LOGIN_RATE_WINDOW):
        retry = rate_limiter.retry_after(key, LOGIN_RATE_WINDOW)
        raise HTTPException(
            status_code=429,
            detail=f"Too many login attempts. Try again in {retry} seconds.",
            headers={"Retry-After": str(retry)},
        )


def check_otp_rate_limit(request: Request, user: SessionUser) -> None:
    """Rate-limit OTP generation per user."""
    key = f"otp:{user.user_id}"

    if not rate_limiter.check(key, OTP_RATE_LIMIT, OTP_RATE_WINDOW):
        retry = rate_limiter.retry_after(key, OTP_RATE_WINDOW)
        raise HTTPException(
            status_code=429,
            detail=f"Too many playback requests. Try again in {retry} seconds.",
            headers={"Retry-After": str(retry)},
        )
