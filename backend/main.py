import asyncio

from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from config import FRONTEND_URL, MAX_CONCURRENT_STREAMS
from models import (
    LoginRequest,
    LoginResponse,
    OTPRequest,
    OTPResponse,
    RefreshRequest,
    RefreshResponse,
    HeartbeatRequest,
    HeartbeatResponse,
    ActiveSessionsResponse,
    SessionUser,
)
from auth import (
    authenticate_user,
    create_session_token,
    create_refresh_token,
    verify_refresh_token,
    revoke_token,
    get_current_user,
)
from middleware import (
    get_client_ip,
    get_device_fingerprint,
    check_login_rate_limit,
    check_otp_rate_limit,
)
from security import analyze_request, audit_log
from sessions import (
    create_playback_session,
    heartbeat as session_heartbeat,
    end_session,
    get_user_sessions,
    cleanup_expired_sessions,
)
from videos import VIDEOS, get_video_by_id
from vdocipher import generate_otp

app = FastAPI(title="SecureStream API", version="2.0.0")

# CORS - allow the Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
    expose_headers=["Retry-After"],
)


# ─── Background Tasks ────────────────────────────────────────────────────


@app.on_event("startup")
async def start_session_cleanup():
    """Periodically clean up expired playback sessions."""
    async def _cleanup_loop():
        while True:
            cleanup_expired_sessions()
            await asyncio.sleep(30)
    asyncio.create_task(_cleanup_loop())


# ─── Auth ────────────────────────────────────────────────────────────────


@app.post("/api/auth/login", response_model=LoginResponse)
async def login(
    body: LoginRequest,
    request: Request,
    _: None = Depends(check_login_rate_limit),
):
    """Authenticate user and return session + refresh tokens."""
    ip = get_client_ip(request)
    fingerprint = get_device_fingerprint(request)

    user = authenticate_user(body.email, body.password)
    if not user:
        audit_log("LOGIN_FAILED", ip=ip, details={"email": body.email})
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = create_session_token(user, fingerprint)
    refresh = create_refresh_token(user, fingerprint)

    audit_log("LOGIN_SUCCESS", user_id=user.user_id, ip=ip)

    return LoginResponse(token=token, refresh_token=refresh, user=user)


@app.post("/api/auth/refresh", response_model=RefreshResponse)
async def refresh_token(body: RefreshRequest, request: Request):
    """Exchange a refresh token for a new session token."""
    fingerprint = get_device_fingerprint(request)
    user = verify_refresh_token(body.refresh_token, fingerprint)
    new_token = create_session_token(user, fingerprint)
    return RefreshResponse(token=new_token)


@app.post("/api/auth/logout")
async def logout(request: Request, user: SessionUser = Depends(get_current_user)):
    """Revoke token and end all playback sessions."""
    ip = get_client_ip(request)
    auth_header = request.headers.get("Authorization", "")
    token = auth_header[7:]  # strip "Bearer "
    revoke_token(token)

    # End all playback sessions for this user
    for session in get_user_sessions(user.user_id):
        end_session(session["session_id"])

    audit_log("LOGOUT", user_id=user.user_id, ip=ip)
    return {"status": "logged_out"}


@app.get("/api/auth/me", response_model=SessionUser)
async def get_me(user: SessionUser = Depends(get_current_user)):
    """Return the current authenticated user."""
    return user


# ─── Videos ──────────────────────────────────────────────────────────────


@app.get("/api/videos")
async def list_videos(user: SessionUser = Depends(get_current_user)):
    """Return the video catalog. Requires authentication."""
    return {"videos": [v.model_dump() for v in VIDEOS]}


@app.get("/api/videos/{video_id}")
async def get_video(
    video_id: str, user: SessionUser = Depends(get_current_user)
):
    """Return a single video's metadata."""
    video = get_video_by_id(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    return video.model_dump()


# ─── DRM / OTP ───────────────────────────────────────────────────────────


@app.post("/api/video/otp", response_model=OTPResponse)
async def get_otp(
    body: OTPRequest,
    request: Request,
    user: SessionUser = Depends(get_current_user),
):
    """
    Generate a session-bound VdoCipher OTP for DRM playback.

    Security layers:
    - Rate limiting (10 req/min per user)
    - Anomaly detection (impossible travel, fingerprint abuse)
    - Concurrent stream limiting (max 2)
    - IP-bound OTP via VdoCipher ipGeo
    - Forensic watermark with user + device identity
    - canPersist: false to block offline ripping
    """
    ip = get_client_ip(request)
    fingerprint = get_device_fingerprint(request)

    # Rate limit check
    check_otp_rate_limit(request, user)

    # Anomaly detection — may raise 403
    analyze_request(user.user_id, ip, fingerprint)

    # Validate video exists
    video = get_video_by_id(body.video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    # Create playback session — may raise 403 if at concurrent limit
    session_id = create_playback_session(
        user.user_id, video.id, fingerprint, ip
    )

    try:
        otp_data = await generate_otp(video.id, user, ip, fingerprint)
        audit_log(
            "OTP_GENERATED",
            user_id=user.user_id,
            ip=ip,
            details={
                "video_id": video.id,
                "session_id": session_id,
                "fingerprint": fingerprint[:8],
            },
        )
        return OTPResponse(
            otp=otp_data["otp"],
            playback_info=otp_data["playback_info"],
            session_id=session_id,
        )
    except Exception as e:
        # Clean up session if OTP generation fails
        end_session(session_id)
        raise HTTPException(status_code=500, detail=str(e))


# ─── Playback Sessions ───────────────────────────────────────────────────


@app.post("/api/playback/heartbeat", response_model=HeartbeatResponse)
async def playback_heartbeat(
    body: HeartbeatRequest,
    user: SessionUser = Depends(get_current_user),
):
    """Keep a playback session alive. Call every 30 seconds."""
    result = session_heartbeat(body.session_id)
    return HeartbeatResponse(**result)


@app.delete("/api/playback/session/{session_id}")
async def stop_session(
    session_id: str,
    user: SessionUser = Depends(get_current_user),
):
    """End a specific playback session."""
    end_session(session_id)
    return {"status": "ended"}


@app.get("/api/playback/sessions", response_model=ActiveSessionsResponse)
async def list_sessions(user: SessionUser = Depends(get_current_user)):
    """List all active playback sessions for the current user."""
    sessions = get_user_sessions(user.user_id)
    return ActiveSessionsResponse(
        sessions=sessions,
        max_allowed=MAX_CONCURRENT_STREAMS,
    )


# ─── Health ──────────────────────────────────────────────────────────────


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "2.0.0"}
