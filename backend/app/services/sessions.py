import secrets
import time

from fastapi import HTTPException

import math

from app.config import (
    MAX_CONCURRENT_STREAMS,
    SESSION_EXPIRY,
    MAX_CONTINUOUS_PLAY_HOURS,
    RAPID_SESSION_CREATION_LIMIT,
    RAPID_SESSION_CREATION_WINDOW,
    GHOST_SESSION_THRESHOLD,
    MIN_PLAY_RATIO,
    HEARTBEAT_GAP_TOLERANCE,
    BEHAVIORAL_RISK_POINTS,
    PLAY_TIME_DRIFT_THRESHOLD,
    PLAY_TIME_DRIFT_MIN_SAMPLES,
    PLAY_TIME_VARIANCE_WINDOW,
    PLAY_TIME_VARIANCE_THRESHOLD,
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

    # Reuse existing session for same video + device
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

    # Track session creation rate (server-side signal #1)
    creation_key = f"session_creations:{user_id}"
    now = time.time()
    await r.zadd(creation_key, {f"{now}": now})
    await r.zremrangebyscore(creation_key, 0, now - RAPID_SESSION_CREATION_WINDOW)
    await r.expire(creation_key, RAPID_SESSION_CREATION_WINDOW + 60)

    session_id = secrets.token_urlsafe(16)
    now_str = str(now)

    pipe = r.pipeline()
    pipe.hset(f"session:{session_id}", mapping={
        "session_id": session_id,
        "user_id": user_id,
        "video_id": video_id,
        "device_fingerprint": device_fingerprint,
        "ip_address": ip_address,
        "created_at": now_str,
        "last_heartbeat": now_str,
        "total_play_seconds": "0",
        "ip_changes": "0",
        "heartbeat_count": "0",
        "missed_heartbeats": "0",
    })
    pipe.expire(f"session:{session_id}", SESSION_EXPIRY)
    pipe.sadd(user_key, session_id)
    await pipe.execute()

    # Track ghost sessions (sessions that never get a heartbeat)
    # We record session creation; heartbeat clears it
    await r.zadd(f"ghost_check:{user_id}", {session_id: now})
    await r.expire(f"ghost_check:{user_id}", SESSION_EXPIRY * 2)

    return session_id


async def heartbeat(
    session_id: str, ip_address: str = "", playback_events: dict = None
) -> dict:
    r = get_redis()
    session = await _get_session(session_id)

    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    user_id = session.get("user_id", "")
    now = time.time()
    flags = []

    # ── Server-side signal #1: IP change detection ──
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
        flags.append(f"ip_change:{ip_changes}/3")

    # ── Server-side signal #2: Heartbeat gap detection ──
    last_hb = float(session.get("last_heartbeat", now))
    gap = now - last_hb
    expected_interval = 30  # heartbeat every 30s
    if gap > expected_interval * 2.5:  # missed at least 1 heartbeat
        missed = int(session.get("missed_heartbeats", 0)) + 1
        await r.hset(f"session:{session_id}", "missed_heartbeats", str(missed))
        if missed >= HEARTBEAT_GAP_TOLERANCE:
            flags.append(f"heartbeat_gaps:{missed}")

    # ── Server-side signal #3: Play ratio detection ──
    # If play_seconds is way less than elapsed time, something is off
    # (e.g., pausing constantly while a script downloads segments)
    play_delta = int(playback_events.get("play_seconds", 0)) if playback_events else 0
    total_play = int(session.get("total_play_seconds", 0)) + play_delta
    session_age = now - float(session.get("created_at", now))

    if session_age > 120 and total_play > 0:  # after 2 minutes of session
        play_ratio = total_play / session_age
        if play_ratio < MIN_PLAY_RATIO:
            flags.append(f"low_play_ratio:{play_ratio:.2f}")

    # ── Server-side signal #4: Continuous play ──
    if total_play > 0:
        await r.hset(f"session:{session_id}", "total_play_seconds", str(total_play))
        if total_play / 3600 > MAX_CONTINUOUS_PLAY_HOURS:
            flags.append(f"continuous_play:{total_play / 3600:.1f}h")

    # ── Server-side signal #5: Rapid session creation ──
    creation_key = f"session_creations:{user_id}"
    recent_creations = await r.zcount(creation_key, now - RAPID_SESSION_CREATION_WINDOW, now)
    if recent_creations > RAPID_SESSION_CREATION_LIMIT:
        flags.append(f"rapid_sessions:{recent_creations}/{RAPID_SESSION_CREATION_LIMIT}")

    # ── Server-side signal #6: Ghost sessions ──
    # Sessions created but never heartbeated
    ghost_key = f"ghost_check:{user_id}"
    ghost_members = await r.zrangebyscore(ghost_key, 0, now - SESSION_EXPIRY)
    ghost_count = len(ghost_members)
    if ghost_count >= GHOST_SESSION_THRESHOLD:
        flags.append(f"ghost_sessions:{ghost_count}")
    # Clear this session from ghost check (it heartbeated)
    await r.zrem(ghost_key, session_id)

    # ── Server-side signal #7: OTP rotation abuse ──
    otp_rotations = int(session.get("otp_rotations", 0))
    if session_age > 0 and otp_rotations > 0:
        # Expected rotations: session_age / rotation_interval
        # If actual rotations are 3x expected, that's suspicious
        expected_rotations = session_age / 90  # 90s default rotation interval
        if otp_rotations > max(10, expected_rotations * 3):
            flags.append(f"rotation_abuse:{otp_rotations}")

    # ── Server-side signal #8: Seek proxy detection (play-time drift & variance) ──
    # Compare client-reported play_seconds vs server-measured heartbeat gap.
    # Also track variance of play_seconds across heartbeats — erratic values
    # indicate seeking/scrubbing even when individual deltas look plausible.
    drift_key = f"play_deltas:{session_id}"
    drift_count = int(session.get("drift_count", 0))

    if play_delta > 0:
        # Drift detection: client says X seconds but server measured Y seconds gap
        drift_ratio = abs(play_delta - gap) / max(gap, play_delta, 1)
        if drift_ratio > PLAY_TIME_DRIFT_THRESHOLD:
            drift_count += 1
            await r.hset(f"session:{session_id}", "drift_count", str(drift_count))
        if drift_count >= PLAY_TIME_DRIFT_MIN_SAMPLES:
            flags.append(f"play_time_drift:{drift_count}")

        # Variance detection: store recent play_seconds, check for erratic pattern
        await r.rpush(drift_key, str(play_delta))
        await r.ltrim(drift_key, -PLAY_TIME_VARIANCE_WINDOW, -1)
        await r.expire(drift_key, SESSION_EXPIRY)

        raw_deltas = await r.lrange(drift_key, 0, -1)
        deltas = [float(d) for d in raw_deltas]
        if len(deltas) >= PLAY_TIME_DRIFT_MIN_SAMPLES:
            mean = sum(deltas) / len(deltas)
            variance = sum((d - mean) ** 2 for d in deltas) / len(deltas)
            std_dev = math.sqrt(variance)
            if std_dev > PLAY_TIME_VARIANCE_THRESHOLD:
                flags.append(f"erratic_playback:{std_dev:.1f}")

    # ── Determine risk level ──
    risk_level = "normal"
    if flags:
        risk_level = "warning" if len(flags) < 3 else "blocked"

    # Update heartbeat tracking + persist flags for watermark decisions
    hb_count = int(session.get("heartbeat_count", 0)) + 1
    pipe = r.pipeline()
    pipe.hset(f"session:{session_id}", "last_heartbeat", str(now))
    pipe.hset(f"session:{session_id}", "heartbeat_count", str(hb_count))
    pipe.hset(f"session:{session_id}", "flags", ",".join(flags) if flags else "")
    pipe.expire(f"session:{session_id}", SESSION_EXPIRY)
    await pipe.execute()

    # Collect debug info
    ttl = await r.ttl(f"session:{session_id}")
    debug = {
        "session_ttl": ttl,
        "total_play_seconds": total_play,
        "ip_changes": int(session.get("ip_changes", 0)),
        "current_ip": ip_address or session.get("ip_address", ""),
        "otp_rotations": otp_rotations,
        "heartbeat_count": hb_count,
        "missed_heartbeats": int(session.get("missed_heartbeats", 0)),
        "session_age_seconds": int(session_age),
        "play_ratio": round(total_play / session_age, 2) if session_age > 0 else 1.0,
        "recent_session_creations": recent_creations,
        "ghost_sessions": ghost_count,
        "drift_count": drift_count,
        "flags": flags,
        "watermark_active": bool(flags),
    }

    return {"status": "alive", "expires_in": SESSION_EXPIRY, "risk_level": risk_level, "debug": debug}


async def session_has_anomaly(session_id: str) -> bool:
    """Check if a session currently has any anomaly flags."""
    session = await _get_session(session_id)
    if not session:
        return False
    flags = session.get("flags", "")
    return bool(flags and flags.strip())


async def validate_session_for_rotation(
    session_id: str, video_id: str, user_id: str
) -> dict:
    session = await _get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    if session.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="Session does not belong to this user")

    if session.get("video_id") != video_id:
        raise HTTPException(status_code=400, detail="Video ID does not match session")

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
        if user_id:
            pipe.srem(f"user_sessions:{user_id}", session_id)
            pipe.zrem(f"ghost_check:{user_id}", session_id)
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
