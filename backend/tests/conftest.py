"""
Shared test fixtures for anomaly detection integration tests.

Tests run against the actual FastAPI app with real Redis and Postgres.
Requires: backend + Redis + Postgres running.
"""
import os
import time
import json
import random
import pytest
import httpx
import asyncio

BASE_URL = "http://localhost:8000"
TEST_EMAIL = "admin@example.com"
TEST_PASSWORD = "admin123"
TEST_FINGERPRINT = "test-fp-admin"
TOKEN_CACHE = "/tmp/drm_test_token.json"


def _get_cached_token():
    """Read cached token if still valid (< 30 min old)."""
    try:
        with open(TOKEN_CACHE) as f:
            data = json.load(f)
        if time.time() - data.get("time", 0) < 1800:
            return data["token"]
    except Exception:
        pass
    return None


def _save_cached_token(token):
    with open(TOKEN_CACHE, "w") as f:
        json.dump({"token": token, "time": time.time()}, f)


@pytest.fixture
async def client():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as c:
        yield c


@pytest.fixture
async def auth_token(client):
    # Try cached token first
    cached = _get_cached_token()
    if cached:
        # Verify it still works
        resp = await client.get(
            "/api/auth/me",
            headers=auth_headers(cached, TEST_FINGERPRINT),
        )
        if resp.status_code == 200:
            return cached

    # Login with TEST_FINGERPRINT so token is device-bound to the test fingerprint.
    resp = await client.post(
        "/api/auth/login",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
        headers={
            "Content-Type": "application/json",
            "X-Forwarded-For": "200.0.0.1",
            "X-Device-Fingerprint": TEST_FINGERPRINT,
        },
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    token = resp.json()["token"]
    _save_cached_token(token)
    return token


def auth_headers(token, fingerprint=TEST_FINGERPRINT, ip=""):
    h = {
        "Authorization": f"Bearer {token}",
        "X-Device-Fingerprint": fingerprint,
        "Content-Type": "application/json",
    }
    if ip:
        h["X-Forwarded-For"] = ip
    return h


async def create_session(client, token, video_id="",
                         fingerprint=TEST_FINGERPRINT, ip="1.2.3.4"):
    if not video_id:
        # Always use TEST_FINGERPRINT for video list (must match token fingerprint)
        resp = await client.get("/api/videos", headers=auth_headers(token, TEST_FINGERPRINT))
        videos = resp.json().get("videos", [])
        assert videos, "No videos available"
        video_id = videos[0]["id"]

    for _ in range(5):
        resp = await client.post(
            "/api/video/otp",
            json={"video_id": video_id, "client_tier": "browser"},
            headers=auth_headers(token, fingerprint, ip),
        )
        if resp.status_code == 429:
            retry = int(resp.headers.get("Retry-After", "5"))
            await asyncio.sleep(min(retry + 1, 15))
            continue
        break

    assert resp.status_code == 200, f"OTP failed ({resp.status_code}): {resp.text}"
    data = resp.json()
    data["video_id"] = video_id
    return data


async def send_heartbeat(client, token, session_id,
                         play_seconds=30, fingerprint=TEST_FINGERPRINT, ip="1.2.3.4"):
    resp = await client.post(
        "/api/playback/heartbeat",
        json={
            "session_id": session_id,
            "playback_events": {"play_seconds": play_seconds},
        },
        headers=auth_headers(token, fingerprint, ip),
    )
    return {"status_code": resp.status_code, **resp.json()}


async def end_all_sessions(client, token):
    try:
        resp = await client.get("/api/playback/sessions", headers=auth_headers(token))
        if resp.status_code == 200:
            for s in resp.json().get("sessions", []):
                await client.delete(
                    f"/api/playback/session/{s['session_id']}",
                    headers=auth_headers(token),
                )
    except Exception:
        pass


def flags_except_rapid(flags):
    """Filter out rapid_sessions from flags list — it fires in tests due to
    many session creations across tests sharing the same Redis state."""
    return [f for f in flags if not f.startswith("rapid_sessions")]
