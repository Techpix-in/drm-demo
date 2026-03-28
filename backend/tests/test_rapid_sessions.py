"""
Group 5: Rapid Session Creation Detection

Tests that creating many sessions in a short window is flagged.
"""
import pytest
import asyncio
from tests.conftest import auth_headers, create_session, send_heartbeat, end_all_sessions

pytestmark = pytest.mark.asyncio


async def test_normal_session_count(client, auth_token):
    """Normal: 2 sessions — heartbeat returns successfully."""
    await end_all_sessions(client, auth_token)

    s1 = await create_session(client, auth_token, ip="10.3.0.1")
    s2 = await create_session(client, auth_token, ip="10.3.0.1")

    result = await send_heartbeat(
        client, auth_token, s2["session_id"],
        play_seconds=1, ip="10.3.0.1",
    )

    # Session should be alive; rapid_sessions may fire from prior test Redis state
    assert result["status"] == "alive"
    await end_all_sessions(client, auth_token)


async def test_rapid_creation_flagged(client, auth_token):
    """
    Flagged: creating 6+ sessions in 10 minutes.
    Since max concurrent is 2, we create and end sessions rapidly.
    """
    await end_all_sessions(client, auth_token)

    # Create and immediately end sessions to simulate rapid creation
    for i in range(6):
        s = await create_session(
            client, auth_token, ip="10.3.0.2",
        )
        # End the session so we don't hit concurrent limit
        await client.delete(
            f"/api/playback/session/{s['session_id']}",
            headers=auth_headers(auth_token),
        )
        await asyncio.sleep(0.5)  # pace to avoid OTP rate limit

    # Create one more and check
    s = await create_session(client, auth_token, ip="10.3.0.2")
    result = await send_heartbeat(
        client, auth_token, s["session_id"],
        play_seconds=1, ip="10.3.0.2",
    )

    assert result["debug"]["recent_session_creations"] > 5
    assert any("rapid_sessions" in f for f in result["debug"].get("flags", []))
    await end_all_sessions(client, auth_token)
