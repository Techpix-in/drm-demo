from fastapi import APIRouter, Depends, HTTPException, Request

from app.models.schemas import (
    LoginRequest,
    LoginResponse,
    RefreshRequest,
    RefreshResponse,
    SessionUser,
)
from app.core.auth import (
    authenticate_user,
    create_session_token,
    create_refresh_token,
    verify_refresh_token,
    revoke_token,
    get_current_user,
)
from app.core.middleware import get_client_ip, get_device_fingerprint, check_login_rate_limit
from app.core.security import audit_log
from app.services.sessions import end_session, get_user_sessions

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, request: Request):
    await check_login_rate_limit(request)
    ip = get_client_ip(request)
    fingerprint = get_device_fingerprint(request)

    user = await authenticate_user(body.email, body.password)
    if not user:
        await audit_log("LOGIN_FAILED", ip=ip, details={"email": body.email})
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = create_session_token(user, fingerprint)
    refresh = create_refresh_token(user, fingerprint)
    await audit_log("LOGIN_SUCCESS", user_id=user.user_id, ip=ip)

    return LoginResponse(token=token, refresh_token=refresh, user=user)


@router.post("/refresh", response_model=RefreshResponse)
async def refresh_token(body: RefreshRequest, request: Request):
    fingerprint = get_device_fingerprint(request)
    user = await verify_refresh_token(body.refresh_token, fingerprint)
    new_token = create_session_token(user, fingerprint)
    return RefreshResponse(token=new_token)


@router.post("/logout")
async def logout(request: Request, user: SessionUser = Depends(get_current_user)):
    ip = get_client_ip(request)
    auth_header = request.headers.get("Authorization", "")
    token = auth_header[7:]
    await revoke_token(token)

    for session in await get_user_sessions(user.user_id):
        await end_session(session["session_id"])

    await audit_log("LOGOUT", user_id=user.user_id, ip=ip)
    return {"status": "logged_out"}


@router.get("/me", response_model=SessionUser)
async def get_me(user: SessionUser = Depends(get_current_user)):
    return user
