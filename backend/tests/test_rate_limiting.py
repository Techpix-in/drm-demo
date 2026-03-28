"""
Group 9: Rate Limiting

Tests that rate limits are enforced on login and OTP endpoints.
"""
import pytest
from tests.conftest import auth_headers, end_all_sessions

pytestmark = pytest.mark.asyncio

# Note: Rate limit tests can interfere with each other and with other tests
# because they share the same Redis state. Run these in isolation if needed.
# Login rate limit: 5 per 15 min per IP
# OTP rate limit: 10 per 60s per user


async def test_login_rate_limit(client):
    """6th login attempt from same IP within 15 min should be blocked."""
    # Use a unique IP so we don't interfere with other tests
    headers = {
        "Content-Type": "application/json",
        "X-Device-Fingerprint": "rate-test-fp",
        "X-Forwarded-For": "99.99.99.1",
    }

    blocked = False
    for i in range(7):
        resp = await client.post(
            "/api/auth/login",
            json={"email": "viewer@example.com", "password": "wrong"},
            headers=headers,
        )
        if resp.status_code == 429:
            blocked = True
            assert "Retry-After" in resp.headers
            break

    assert blocked, "Expected rate limit (429) but all requests succeeded"


async def test_otp_rate_limit(client, auth_token):
    """11th OTP request within 60s should be blocked."""
    await end_all_sessions(client, auth_token)

    # Get a video ID first
    resp = await client.get("/api/videos", headers=auth_headers(auth_token))
    videos = resp.json().get("videos", [])
    assert videos, "No videos available"
    video_id = videos[0]["id"]

    blocked = False
    for i in range(12):
        resp = await client.post(
            "/api/video/otp",
            json={"video_id": video_id, "client_tier": "browser"},
            headers=auth_headers(auth_token, ip="10.5.0.1"),
        )

        if resp.status_code == 429:
            blocked = True
            break

        # Clean up session to avoid concurrent limit
        if resp.status_code == 200:
            sid = resp.json().get("session_id")
            if sid:
                await client.delete(
                    f"/api/playback/session/{sid}",
                    headers=auth_headers(auth_token),
                )

    assert blocked, "Expected OTP rate limit (429) but all requests succeeded"
    await end_all_sessions(client, auth_token)


async def test_within_limits_succeeds(client, auth_token):
    """Requests within rate limits should succeed."""
    await end_all_sessions(client, auth_token)

    # Login should work with a fresh IP
    resp = await client.post(
        "/api/auth/login",
        json={"email": "viewer@example.com", "password": "demo123"},
        headers={
            "Content-Type": "application/json",
            "X-Device-Fingerprint": "rate-ok-fp",
            "X-Forwarded-For": "99.99.99.2",
        },
    )
    assert resp.status_code == 200
