"""Group 10: Session Management"""
import pytest
import asyncio
from tests.conftest import auth_headers, create_session, send_heartbeat, end_all_sessions, TEST_FINGERPRINT

pytestmark = pytest.mark.asyncio


async def _get_video_ids(client, auth_token):
    """Get all available video IDs."""
    resp = await client.get("/api/videos", headers=auth_headers(auth_token))
    videos = resp.json().get("videos", [])
    assert len(videos) >= 2, "Need at least 2 videos for session tests"
    return [v["id"] for v in videos]


async def test_session_reuse_same_device_video(client, auth_token):
    """Same user + same video + same device should reuse session."""
    await end_all_sessions(client, auth_token)

    s1 = await create_session(client, auth_token, ip="10.4.0.2")
    s2 = await create_session(client, auth_token, ip="10.4.0.2")
    assert s1["session_id"] == s2["session_id"]

    await end_all_sessions(client, auth_token)


async def test_concurrent_stream_limit(client, auth_token):
    """3rd concurrent session should be blocked."""
    await end_all_sessions(client, auth_token)

    video_ids = await _get_video_ids(client, auth_token)

    # Create 2 sessions on different videos (same fingerprint, different video = different session)
    await create_session(client, auth_token, video_id=video_ids[0], ip="10.4.0.1")
    await asyncio.sleep(0.5)
    await create_session(client, auth_token, video_id=video_ids[1], ip="10.4.0.1")

    # 3rd session on a 3rd video should be blocked by concurrent limit
    # Retry past any rate limit to get the actual 403
    for _ in range(5):
        resp = await client.post(
            "/api/video/otp",
            json={"video_id": video_ids[2] if len(video_ids) > 2 else video_ids[0], "client_tier": "browser"},
            headers=auth_headers(auth_token, ip="10.4.0.1"),
        )
        if resp.status_code == 429:
            retry = int(resp.headers.get("Retry-After", "5"))
            await asyncio.sleep(min(retry + 1, 15))
            continue
        break

    assert resp.status_code == 403, f"Expected 403 but got {resp.status_code}: {resp.text}"
    assert "Maximum concurrent streams" in resp.json().get("detail", "")

    await end_all_sessions(client, auth_token)


async def test_end_session_frees_slot(client, auth_token):
    """Ending a session should free a slot."""
    await end_all_sessions(client, auth_token)

    video_ids = await _get_video_ids(client, auth_token)

    s1 = await create_session(client, auth_token, video_id=video_ids[0], ip="10.4.0.3")
    await create_session(client, auth_token, video_id=video_ids[1], ip="10.4.0.3")

    await client.delete(
        f"/api/playback/session/{s1['session_id']}",
        headers=auth_headers(auth_token),
    )

    # Slot freed — creating a new session should work
    s3 = await create_session(client, auth_token, video_id=video_ids[0], ip="10.4.0.3")
    assert s3["session_id"] is not None

    await end_all_sessions(client, auth_token)


async def test_heartbeat_keeps_session_alive(client, auth_token):
    """Heartbeat should keep session alive."""
    await end_all_sessions(client, auth_token)
    s = await create_session(client, auth_token, ip="10.4.0.4")

    result = await send_heartbeat(client, auth_token, s["session_id"], ip="10.4.0.4")
    assert result["status"] == "alive"
    assert result["debug"]["session_ttl"] > 0

    await end_all_sessions(client, auth_token)


async def test_heartbeat_expired_session_returns_404(client, auth_token):
    """Heartbeat on non-existent session should 404."""
    result = await send_heartbeat(client, auth_token, "fake-session-xyz", ip="10.4.0.5")
    assert result["status_code"] == 404
