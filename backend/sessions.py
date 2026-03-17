import secrets
import time
from typing import Dict, List, Set

from fastapi import HTTPException

from config import MAX_CONCURRENT_STREAMS, SESSION_EXPIRY


# session_id -> session data dict
_active_sessions: Dict[str, dict] = {}

# user_id -> set of session_ids
_user_sessions: Dict[str, Set[str]] = {}


def _is_alive(session: dict) -> bool:
    """Check if a session is still alive (heartbeat within expiry window)."""
    return (time.time() - session["last_heartbeat"]) < SESSION_EXPIRY


def _evict_expired_for_user(user_id: str) -> None:
    """Remove expired sessions for a specific user."""
    if user_id not in _user_sessions:
        return

    dead = set()
    for sid in _user_sessions[user_id]:
        session = _active_sessions.get(sid)
        if not session or not _is_alive(session):
            dead.add(sid)

    for sid in dead:
        _active_sessions.pop(sid, None)
        _user_sessions[user_id].discard(sid)


def create_playback_session(
    user_id: str,
    video_id: str,
    device_fingerprint: str,
    ip_address: str,
) -> str:
    """
    Create a new playback session.
    If the same user+video+device already has a session, reuse it (handles page refresh).
    Raises 403 if concurrent stream limit is reached.
    Returns session_id.
    """
    # Evict expired sessions first
    _evict_expired_for_user(user_id)

    if user_id not in _user_sessions:
        _user_sessions[user_id] = set()

    # Check if this user+video+device already has an active session (page refresh)
    for sid in list(_user_sessions[user_id]):
        session = _active_sessions.get(sid)
        if (
            session
            and session["video_id"] == video_id
            and session["device_fingerprint"] == device_fingerprint
        ):
            # Reuse existing session — just refresh the heartbeat
            session["last_heartbeat"] = time.time()
            return sid

    # Check concurrent limit
    active_count = len(_user_sessions[user_id])
    if active_count >= MAX_CONCURRENT_STREAMS:
        raise HTTPException(
            status_code=403,
            detail=f"Maximum concurrent streams reached ({MAX_CONCURRENT_STREAMS}). "
            "Stop another stream first.",
        )

    # Create new session
    session_id = secrets.token_urlsafe(16)
    now = time.time()

    _active_sessions[session_id] = {
        "session_id": session_id,
        "user_id": user_id,
        "video_id": video_id,
        "device_fingerprint": device_fingerprint,
        "ip_address": ip_address,
        "created_at": now,
        "last_heartbeat": now,
    }

    _user_sessions[user_id].add(session_id)

    return session_id


def heartbeat(session_id: str) -> dict:
    """
    Update heartbeat for a playback session.
    Returns session status.
    """
    session = _active_sessions.get(session_id)
    if not session:
        raise HTTPException(
            status_code=404,
            detail="Session not found or expired",
        )

    if not _is_alive(session):
        # Clean up the dead session
        end_session(session_id)
        raise HTTPException(
            status_code=404,
            detail="Session expired due to inactivity",
        )

    session["last_heartbeat"] = time.time()
    return {"status": "alive", "expires_in": SESSION_EXPIRY}


def end_session(session_id: str) -> None:
    """End a playback session."""
    session = _active_sessions.pop(session_id, None)
    if session:
        user_id = session["user_id"]
        if user_id in _user_sessions:
            _user_sessions[user_id].discard(session_id)


def get_user_sessions(user_id: str) -> List[dict]:
    """Return all active sessions for a user."""
    _evict_expired_for_user(user_id)

    sessions = []
    for sid in _user_sessions.get(user_id, set()):
        session = _active_sessions.get(sid)
        if session:
            sessions.append({
                "session_id": session["session_id"],
                "video_id": session["video_id"],
                "device_fingerprint": session["device_fingerprint"][:8] + "...",
                "ip_address": session["ip_address"],
                "created_at": session["created_at"],
                "last_heartbeat": session["last_heartbeat"],
            })
    return sessions


def cleanup_expired_sessions() -> None:
    """Remove all expired sessions across all users. Called periodically."""
    dead_sessions = []
    for sid, session in _active_sessions.items():
        if not _is_alive(session):
            dead_sessions.append(sid)

    for sid in dead_sessions:
        end_session(sid)
