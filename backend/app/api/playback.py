from fastapi import APIRouter, Depends, HTTPException, Request

from app.config import (
    MAX_CONCURRENT_STREAMS,
    BEHAVIORAL_RISK_POINTS,
    OTP_ROTATION_INTERVAL_BROWSER,
    OTP_ROTATION_INTERVAL_MOBILE,
    OTP_RATE_LIMIT,
    OTP_RATE_WINDOW,
    LOGIN_RATE_LIMIT,
    LOGIN_RATE_WINDOW,
    RISK_SCORE_THRESHOLD,
)
from app.models.schemas import (
    OTPRequest,
    OTPResponse,
    OTPRotateRequest,
    HeartbeatRequest,
    HeartbeatResponse,
    ActiveSessionsResponse,
    DebugInfoResponse,
    SessionUser,
)
from app.core.auth import get_current_user
from app.core.middleware import get_client_ip, get_device_fingerprint, check_otp_rate_limit
from app.core.security import audit_log, add_risk_points, get_risk_score
from app.db.redis import get_redis
from app.services.sessions import (
    create_playback_session,
    heartbeat as session_heartbeat,
    end_session,
    get_user_sessions,
    validate_session_for_rotation,
)
from app.services.videos import get_video_by_id
from app.services.vdocipher import generate_otp

router = APIRouter(prefix="/api", tags=["playback"])


@router.post("/video/otp", response_model=OTPResponse)
async def get_otp(
    body: OTPRequest,
    request: Request,
    user: SessionUser = Depends(get_current_user),
):
    ip = get_client_ip(request)
    fingerprint = get_device_fingerprint(request)
    client_tier = body.client_tier or "browser"

    await check_otp_rate_limit(request, user)
    # Skip analyze_request here — it causes false positives behind
    # proxies (Cloudflare/Vercel) where X-Forwarded-For IPs vary.
    # IP monitoring is done per-session in heartbeat instead.

    video = await get_video_by_id(body.video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    session_id = await create_playback_session(user.user_id, video.id, fingerprint, ip)

    try:
        otp_data = await generate_otp(video.id, user, ip, fingerprint, client_tier)
        await audit_log(
            "OTP_GENERATED",
            user_id=user.user_id,
            ip=ip,
            details={
                "video_id": video.id,
                "session_id": session_id,
                "fingerprint": fingerprint[:8],
                "tier": client_tier,
                "max_resolution": otp_data["max_resolution"],
            },
        )
        rotation_interval = (
            OTP_ROTATION_INTERVAL_BROWSER
            if client_tier == "browser"
            else OTP_ROTATION_INTERVAL_MOBILE
        )
        return OTPResponse(
            otp=otp_data["otp"],
            playback_info=otp_data["playback_info"],
            session_id=session_id,
            tier=otp_data["tier"],
            max_resolution=otp_data["max_resolution"],
            rotation_interval=rotation_interval,
        )
    except Exception as e:
        await end_session(session_id)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/video/otp/rotate", response_model=OTPResponse)
async def rotate_otp(
    body: OTPRotateRequest,
    request: Request,
    user: SessionUser = Depends(get_current_user),
):
    """
    Issue a fresh OTP for an active session.
    Validates: session exists, belongs to user, matches video.
    Rate-limited same as regular OTP requests.
    """
    ip = get_client_ip(request)
    fingerprint = get_device_fingerprint(request)

    await check_otp_rate_limit(request, user)

    # Validate session ownership and video match
    session = await validate_session_for_rotation(
        body.session_id, body.video_id, user.user_id
    )

    client_tier = session.get("client_tier", "browser")

    try:
        otp_data = await generate_otp(body.video_id, user, ip, fingerprint, client_tier)
        await audit_log(
            "OTP_ROTATED",
            user_id=user.user_id,
            ip=ip,
            details={
                "video_id": body.video_id,
                "session_id": body.session_id,
                "rotation_count": session.get("otp_rotations", 0),
            },
        )
        rotation_interval = (
            OTP_ROTATION_INTERVAL_BROWSER
            if client_tier == "browser"
            else OTP_ROTATION_INTERVAL_MOBILE
        )
        return OTPResponse(
            otp=otp_data["otp"],
            playback_info=otp_data["playback_info"],
            session_id=body.session_id,
            tier=otp_data["tier"],
            max_resolution=otp_data["max_resolution"],
            rotation_interval=rotation_interval,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/playback/heartbeat", response_model=HeartbeatResponse)
async def playback_heartbeat(
    body: HeartbeatRequest,
    request: Request,
    user: SessionUser = Depends(get_current_user),
):
    ip = get_client_ip(request)
    result = await session_heartbeat(
        body.session_id,
        ip_address=ip,
        playback_events=body.playback_events or {},
    )

    if result.get("risk_level") == "blocked":
        await add_risk_points(user.user_id, BEHAVIORAL_RISK_POINTS, "behavioral_blocked", ip=ip)

    return HeartbeatResponse(**result)


@router.delete("/playback/session/{session_id}")
async def stop_session(session_id: str, user: SessionUser = Depends(get_current_user)):
    await end_session(session_id)
    return {"status": "ended"}


@router.get("/playback/sessions", response_model=ActiveSessionsResponse)
async def list_sessions(user: SessionUser = Depends(get_current_user)):
    sessions = await get_user_sessions(user.user_id)
    return ActiveSessionsResponse(sessions=sessions, max_allowed=MAX_CONCURRENT_STREAMS)


@router.get("/playback/debug/{session_id}", response_model=DebugInfoResponse)
async def get_debug_info(
    session_id: str,
    request: Request,
    user: SessionUser = Depends(get_current_user),
):
    """Return debug info: session state, rate limits, risk score."""
    import time

    r = get_redis()
    now = time.time()

    # Session info
    session_data = await r.hgetall(f"session:{session_id}")
    session_ttl = await r.ttl(f"session:{session_id}")
    session_info = {}
    if session_data:
        session_info = {
            "session_id": session_data.get("session_id", ""),
            "video_id": session_data.get("video_id", ""),
            "device_fingerprint": session_data.get("device_fingerprint", "")[:8] + "...",
            "ip_address": session_data.get("ip_address", ""),
            "created_at": float(session_data.get("created_at", 0)),
            "last_heartbeat": float(session_data.get("last_heartbeat", 0)),
            "total_play_seconds": int(session_data.get("total_play_seconds", 0)),
            "ip_changes": int(session_data.get("ip_changes", 0)),
            "otp_rotations": int(session_data.get("otp_rotations", 0)),
            "ttl": session_ttl,
        }

    # Rate limits
    otp_key = f"ratelimit:otp:{user.user_id}"
    await r.zremrangebyscore(otp_key, 0, now - OTP_RATE_WINDOW)
    otp_used = await r.zcard(otp_key)

    ip = get_client_ip(request)
    login_key = f"ratelimit:login:{ip}"
    await r.zremrangebyscore(login_key, 0, now - LOGIN_RATE_WINDOW)
    login_used = await r.zcard(login_key)

    rate_limits = {
        "otp": {"used": otp_used, "limit": OTP_RATE_LIMIT, "window": OTP_RATE_WINDOW},
        "login": {"used": login_used, "limit": LOGIN_RATE_LIMIT, "window": LOGIN_RATE_WINDOW},
    }

    # Risk score
    risk_score = await get_risk_score(user.user_id)
    risk_info = {
        "score": risk_score,
        "threshold": RISK_SCORE_THRESHOLD,
        "status": "blocked" if risk_score >= RISK_SCORE_THRESHOLD else (
            "warning" if risk_score >= RISK_SCORE_THRESHOLD * 0.5 else "normal"
        ),
    }

    return DebugInfoResponse(session=session_info, rate_limits=rate_limits, risk=risk_info)
