import hashlib
import hmac
import json
import time
from typing import Optional, Set

from fastapi import HTTPException, Request

from config import SESSION_SECRET, SESSION_TOKEN_TTL, REFRESH_TOKEN_TTL
from models import SessionUser
from middleware import get_device_fingerprint

# Demo users - replace with a real database in production
DEMO_USERS = {
    "viewer@example.com": {
        "password": "demo123",
        "user_id": "user-001",
        "name": "Demo Viewer",
    },
    "admin@example.com": {
        "password": "admin123",
        "user_id": "user-002",
        "name": "Admin User",
    },
}

# Token revocation store (in production, use Redis)
_revoked_tokens: Set[str] = set()


def _sign(payload: str) -> str:
    return hmac.new(
        SESSION_SECRET.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()


def create_session_token(user: SessionUser, device_fingerprint: str = "") -> str:
    """Create a signed session token (valid for SESSION_TOKEN_TTL)."""
    payload = json.dumps(
        {
            "user_id": user.user_id,
            "email": user.email,
            "name": user.name,
            "device_fingerprint": device_fingerprint,
            "type": "session",
            "exp": int(time.time()) + SESSION_TOKEN_TTL,
        }
    )
    signature = _sign(payload)
    return f"{payload}|{signature}"


def create_refresh_token(user: SessionUser, device_fingerprint: str = "") -> str:
    """Create a signed refresh token (valid for REFRESH_TOKEN_TTL)."""
    payload = json.dumps(
        {
            "user_id": user.user_id,
            "email": user.email,
            "name": user.name,
            "device_fingerprint": device_fingerprint,
            "type": "refresh",
            "exp": int(time.time()) + REFRESH_TOKEN_TTL,
        }
    )
    signature = _sign(payload)
    return f"{payload}|{signature}"


def verify_session_token(
    token: str, device_fingerprint: str = ""
) -> SessionUser:
    """Verify and decode a session token."""
    try:
        payload, signature = token.rsplit("|", 1)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid token format")

    # Check revocation
    if signature in _revoked_tokens:
        raise HTTPException(status_code=401, detail="Token has been revoked")

    if not hmac.compare_digest(_sign(payload), signature):
        raise HTTPException(status_code=401, detail="Invalid token signature")

    data = json.loads(payload)

    if data["exp"] < int(time.time()):
        raise HTTPException(status_code=401, detail="Token expired")

    # Device binding: verify fingerprint matches if both are present
    token_fp = data.get("device_fingerprint", "")
    if device_fingerprint and token_fp and device_fingerprint != token_fp:
        raise HTTPException(status_code=401, detail="Device mismatch")

    return SessionUser(
        user_id=data["user_id"],
        email=data["email"],
        name=data["name"],
    )


def verify_refresh_token(
    token: str, device_fingerprint: str = ""
) -> SessionUser:
    """Verify and decode a refresh token."""
    try:
        payload, signature = token.rsplit("|", 1)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid token format")

    if signature in _revoked_tokens:
        raise HTTPException(status_code=401, detail="Token has been revoked")

    if not hmac.compare_digest(_sign(payload), signature):
        raise HTTPException(status_code=401, detail="Invalid token signature")

    data = json.loads(payload)

    if data.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Not a refresh token")

    if data["exp"] < int(time.time()):
        raise HTTPException(status_code=401, detail="Refresh token expired")

    # Device binding
    token_fp = data.get("device_fingerprint", "")
    if device_fingerprint and token_fp and device_fingerprint != token_fp:
        raise HTTPException(status_code=401, detail="Device mismatch")

    return SessionUser(
        user_id=data["user_id"],
        email=data["email"],
        name=data["name"],
    )


def revoke_token(token: str) -> None:
    """Revoke a token by adding its signature to the blocklist."""
    try:
        _, signature = token.rsplit("|", 1)
        _revoked_tokens.add(signature)
    except ValueError:
        pass


def get_current_user(request: Request) -> SessionUser:
    """Extract and verify user from Authorization header with device binding."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing authorization token")

    token = auth_header[7:]  # strip "Bearer "
    fingerprint = get_device_fingerprint(request)
    return verify_session_token(token, fingerprint)


def authenticate_user(email: str, password: str) -> Optional[SessionUser]:
    """Authenticate with email/password. Returns user or None."""
    user_data = DEMO_USERS.get(email)
    if not user_data or user_data["password"] != password:
        return None

    return SessionUser(
        user_id=user_data["user_id"],
        email=email,
        name=user_data["name"],
    )
