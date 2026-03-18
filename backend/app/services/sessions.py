import json
import secrets
import time

from fastapi import HTTPException

from app.config import (
    MAX_CONCURRENT_STREAMS,
    SESSION_EXPIRY,
    MAX_SEEKS_PER_MINUTE,
    MAX_RESTARTS_PER_HOUR,
    MAX_CONTINUOUS_PLAY_HOURS,
)
from app.db.redis import get_redis


async def _get_session(session_id: str) -> dict | None:
    r = get_redis()
    data = await r.hgetall(f"session:{session_id}")
    return data if data else None


async def _evict_expired_for_user(user_id: str) -> None:
    r = get_redis()
    key = f"user_sessions:{user_id}"
    members = await r.smembers(key)
    for sid in members:
        if not await r.exists(f"session:{sid}"):
            await r.srem(key, sid)


async def create_playback_session(
    user_id: str, video_id: str, device_fingerprint: str, ip_address: str
) -> str:
    r = get_redis()
    await _evict_expired_for_user(user_id)
    user_key = f"user_sessions:{user_id}"

    members = await r.smembers(user_key)
    for sid in members:
        session = await _get_session(sid)
        if (
            session
            and session.get("video_id") == video_id
            and session.get("device_fingerprint") == device_fingerprint
        ):
            await r.expire(f"session:{sid}", SESSION_EXPIRY)
            return sid

    if len(members) >= MAX_CONCURRENT_STREAMS:
        raise HTTPException(
            status_code=403,
            detail=f"Maximum concurrent streams reached ({MAX_CONCURRENT_STREAMS}). "
            "Stop another stream first.",
        )

    session_id = secrets.token_urlsafe(16)
    now = str(time.time())

    pipe = r.pipeline()
    pipe.hset(f"session:{session_id}", mapping={
        "session_id": session_id,
        "user_id": user_id,
        "video_id": video_id,
        "device_fingerprint": device_fingerprint,
        "ip_address": ip_address,
        "created_at": now,
        "last_heartbeat": now,
        "total_play_seconds": "0",
        "ip_changes": "0",
    })
    pipe.expire(f"session:{session_id}", SESSION_EXPIRY)
    pipe.sadd(user_key, session_id)
    await pipe.execute()

    return session_id


async def heartbeat(
    session_id: str, ip_address: str = "", playback_events: dict = None
) -> dict:
    r = get_redis()
    session = await _get_session(session_id)

    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    risk_level = "normal"

    if ip_address and session.get("ip_address") != ip_address:
        ip_changes = int(session.get("ip_changes", 0)) + 1
        await r.hset(f"session:{session_id}", "ip_address", ip_address)
        await r.hset(f"session:{session_id}", "ip_changes", str(ip_changes))
        if ip_changes >= 3:
            await end_session(session_id)
            raise HTTPException(
                status_code=403,
                detail="Session terminated: too many IP changes detected.",
            )
        risk_level = "warning"

    if playback_events:
        flags = await _analyze_playback_behavior(session_id, session, playback_events)
        if flags:
            risk_level = "warning" if len(flags) < 2 else "blocked"

    pipe = r.pipeline()
    pipe.hset(f"session:{session_id}", "last_heartbeat", str(time.time()))
    pipe.expire(f"session:{session_id}", SESSION_EXPIRY)
    await pipe.execute()

    return {"status": "alive", "expires_in": SESSION_EXPIRY, "risk_level": risk_level}


async def _analyze_playback_behavior(
    session_id: str, session: dict, events: dict
) -> list:
    r = get_redis()
    now = time.time()
    flags = []

    seek_count = int(events.get("seek_count", 0))
    if seek_count > 0:
        seek_key = f"seeks:{session_id}"
        pipe = r.pipeline()
        for i in range(seek_count):
            pipe.zadd(seek_key, {f"{now}:{i}": now})
        pipe.zremrangebyscore(seek_key, 0, now - 120)
        pipe.expire(seek_key, 300)
        await pipe.execute()
        recent = await r.zcount(seek_key, now - 60, now)
        if recent > MAX_SEEKS_PER_MINUTE:
            flags.append(f"excessive_seeking:{recent}/min")

    restart_count = int(events.get("restart_count", 0))
    if restart_count > 0:
        restart_key = f"restarts:{session_id}"
        pipe = r.pipeline()
        for i in range(restart_count):
            pipe.zadd(restart_key, {f"{now}:{i}": now})
        pipe.zremrangebyscore(restart_key, 0, now - 3600)
        pipe.expire(restart_key, 3700)
        await pipe.execute()
        total = await r.zcard(restart_key)
        if total > MAX_RESTARTS_PER_HOUR:
            flags.append(f"rapid_restarts:{total}/hr")

    play_delta = int(events.get("play_seconds", 0))
    if play_delta > 0:
        total = int(session.get("total_play_seconds", 0)) + play_delta
        await r.hset(f"session:{session_id}", "total_play_seconds", str(total))
        if total / 3600 > MAX_CONTINUOUS_PLAY_HOURS:
            flags.append(f"continuous_play:{total / 3600:.1f}h")

    return flags


async def validate_session_for_rotation(
    session_id: str, video_id: str, user_id: str
) -> dict:
    """
    Validate that a session exists, belongs to the user,
    and matches the video. Used before issuing a rotated OTP.
    """
    session = await _get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    if session.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="Session does not belong to this user")

    if session.get("video_id") != video_id:
        raise HTTPException(status_code=400, detail="Video ID does not match session")

    # Track rotation count
    r = get_redis()
    count = await r.hincrby(f"session:{session_id}", "otp_rotations", 1)

    return {**session, "otp_rotations": count}


async def end_session(session_id: str) -> None:
    r = get_redis()
    session = await _get_session(session_id)
    if session:
        user_id = session.get("user_id", "")
        pipe = r.pipeline()
        pipe.delete(f"session:{session_id}")
        pipe.delete(f"seeks:{session_id}")
        pipe.delete(f"restarts:{session_id}")
        if user_id:
            pipe.srem(f"user_sessions:{user_id}", session_id)
        await pipe.execute()


async def get_user_sessions(user_id: str) -> list:
    r = get_redis()
    await _evict_expired_for_user(user_id)
    sessions = []
    members = await r.smembers(f"user_sessions:{user_id}")
    for sid in members:
        session = await _get_session(sid)
        if session:
            sessions.append({
                "session_id": session["session_id"],
                "video_id": session.get("video_id", ""),
                "device_fingerprint": session.get("device_fingerprint", "")[:8] + "...",
                "ip_address": session.get("ip_address", ""),
                "created_at": float(session.get("created_at", 0)),
                "last_heartbeat": float(session.get("last_heartbeat", 0)),
            })
    return sessions
