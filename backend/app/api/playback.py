from fastapi import APIRouter, Depends, HTTPException, Request

from app.config import (
    MAX_CONCURRENT_STREAMS,
    BEHAVIORAL_RISK_POINTS,
    OTP_ROTATION_INTERVAL_BROWSER,
    OTP_ROTATION_INTERVAL_MOBILE,
)
from app.models.schemas import (
    OTPRequest,
    OTPResponse,
    OTPRotateRequest,
    HeartbeatRequest,
    HeartbeatResponse,
    ActiveSessionsResponse,
    SessionUser,
)
from app.core.auth import get_current_user
from app.core.middleware import get_client_ip, get_device_fingerprint, check_otp_rate_limit
from app.core.security import analyze_request, audit_log, add_risk_points
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
