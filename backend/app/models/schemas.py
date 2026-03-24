from typing import List
from pydantic import BaseModel


class Video(BaseModel):
    id: str
    title: str
    description: str
    thumbnail: str
    duration: str


class OTPRequest(BaseModel):
    video_id: str
    client_tier: str = "browser"


class OTPResponse(BaseModel):
    otp: str
    playback_info: str
    session_id: str
    tier: str
    max_resolution: str
    rotation_interval: int = 90


class OTPRotateRequest(BaseModel):
    session_id: str
    video_id: str


class LoginRequest(BaseModel):
    email: str
    password: str


class SessionUser(BaseModel):
    user_id: str
    email: str
    name: str


class LoginResponse(BaseModel):
    token: str
    refresh_token: str
    user: SessionUser


class RefreshRequest(BaseModel):
    refresh_token: str


class RefreshResponse(BaseModel):
    token: str


class HeartbeatRequest(BaseModel):
    session_id: str
    playback_events: dict = {}


class HeartbeatResponse(BaseModel):
    status: str
    expires_in: int
    risk_level: str = "normal"
    debug: dict = {}
    flags: list = []


class DebugInfoResponse(BaseModel):
    session: dict = {}
    rate_limits: dict = {}
    risk: dict = {}


class PlaybackSession(BaseModel):
    session_id: str
    user_id: str
    video_id: str
    device_fingerprint: str
    ip_address: str
    created_at: float
    last_heartbeat: float


class ActiveSessionsResponse(BaseModel):
    sessions: List[dict]
    max_allowed: int
