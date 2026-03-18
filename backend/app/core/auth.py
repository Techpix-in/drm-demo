import hashlib
import hmac
import json
import time
from typing import Optional

from fastapi import HTTPException, Request
from passlib.hash import bcrypt
from sqlalchemy import select

from app.config import SESSION_SECRET, SESSION_TOKEN_TTL, REFRESH_TOKEN_TTL
from app.db.postgres import async_session, UserDB
from app.db.redis import get_redis
from app.models.schemas import SessionUser
from app.core.middleware import get_device_fingerprint

_REVOKE_TTL = REFRESH_TOKEN_TTL + 60


def _sign(payload: str) -> str:
    return hmac.new(
        SESSION_SECRET.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()


def create_session_token(user: SessionUser, device_fingerprint: str = "") -> str:
    payload = json.dumps({
        "user_id": user.user_id,
        "email": user.email,
        "name": user.name,
        "device_fingerprint": device_fingerprint,
        "type": "session",
        "exp": int(time.time()) + SESSION_TOKEN_TTL,
    })
    return f"{payload}|{_sign(payload)}"


def create_refresh_token(user: SessionUser, device_fingerprint: str = "") -> str:
    payload = json.dumps({
        "user_id": user.user_id,
        "email": user.email,
        "name": user.name,
        "device_fingerprint": device_fingerprint,
        "type": "refresh",
        "exp": int(time.time()) + REFRESH_TOKEN_TTL,
    })
    return f"{payload}|{_sign(payload)}"


async def _is_token_revoked(signature: str) -> bool:
    r = get_redis()
    return await r.exists(f"revoked:{signature}") > 0


async def verify_session_token(token: str, device_fingerprint: str = "") -> SessionUser:
    try:
        payload, signature = token.rsplit("|", 1)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid token format")

    if await _is_token_revoked(signature):
        raise HTTPException(status_code=401, detail="Token has been revoked")

    if not hmac.compare_digest(_sign(payload), signature):
        raise HTTPException(status_code=401, detail="Invalid token signature")

    data = json.loads(payload)

    if data["exp"] < int(time.time()):
        raise HTTPException(status_code=401, detail="Token expired")

    token_fp = data.get("device_fingerprint", "")
    if device_fingerprint and token_fp and device_fingerprint != token_fp:
        raise HTTPException(status_code=401, detail="Device mismatch")

    return SessionUser(user_id=data["user_id"], email=data["email"], name=data["name"])


async def verify_refresh_token(token: str, device_fingerprint: str = "") -> SessionUser:
    try:
        payload, signature = token.rsplit("|", 1)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid token format")

    if await _is_token_revoked(signature):
        raise HTTPException(status_code=401, detail="Token has been revoked")

    if not hmac.compare_digest(_sign(payload), signature):
        raise HTTPException(status_code=401, detail="Invalid token signature")

    data = json.loads(payload)

    if data.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Not a refresh token")

    if data["exp"] < int(time.time()):
        raise HTTPException(status_code=401, detail="Refresh token expired")

    token_fp = data.get("device_fingerprint", "")
    if device_fingerprint and token_fp and device_fingerprint != token_fp:
        raise HTTPException(status_code=401, detail="Device mismatch")

    return SessionUser(user_id=data["user_id"], email=data["email"], name=data["name"])


async def revoke_token(token: str) -> None:
    try:
        _, signature = token.rsplit("|", 1)
        r = get_redis()
        await r.setex(f"revoked:{signature}", _REVOKE_TTL, "1")
    except ValueError:
        pass


async def get_current_user(request: Request) -> SessionUser:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing authorization token")

    token = auth_header[7:]
    fingerprint = get_device_fingerprint(request)
    return await verify_session_token(token, fingerprint)


async def authenticate_user(email: str, password: str) -> Optional[SessionUser]:
    async with async_session() as session:
        result = await session.execute(
            select(UserDB).where(UserDB.email == email, UserDB.is_active == True)
        )
        user = result.scalar_one_or_none()

    if not user or not bcrypt.verify(password, user.password_hash):
        return None

    return SessionUser(user_id=user.id, email=user.email, name=user.name)
