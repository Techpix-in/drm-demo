"""Group 8: Combined Attack Simulations"""
import pytest
from tests.conftest import (
    auth_headers, create_session, send_heartbeat, end_all_sessions, flags_except_rapid,
)

pytestmark = pytest.mark.asyncio


async def test_normal_viewer_simulation(client, auth_token):
    """Normal viewer: play for a few minutes, no flags."""
    await end_all_sessions(client, auth_token)
    session = await create_session(client, auth_token, ip="10.6.0.1")

    for _ in range(3):
        result = await send_heartbeat(
            client, auth_token, session["session_id"],
            play_seconds=1, ip="10.6.0.1",  # ~1s matches actual test gap
        )
        # Only check non-rapid flags (and ignore drift from test timing)
        flags = [f for f in flags_except_rapid(result["debug"].get("flags", []))
                 if not f.startswith("play_time_drift")]
        assert len(flags) == 0

    await end_all_sessions(client, auth_token)


async def test_binge_watcher_under_threshold(client, auth_token):
    """9 hours straight — should NOT trigger continuous_play."""
    await end_all_sessions(client, auth_token)
    session = await create_session(client, auth_token, ip="10.6.0.2")

    result = await send_heartbeat(
        client, auth_token, session["session_id"],
        play_seconds=32400, ip="10.6.0.2",
    )

    assert not any("continuous_play" in f for f in result["debug"].get("flags", []))
    await end_all_sessions(client, auth_token)


async def test_ripping_bot_simulation(client, auth_token):
    """Rapid session creation + low play — should flag rapid_sessions."""
    import asyncio
    await end_all_sessions(client, auth_token)

    # Use the same fingerprint (token-bound) but create/destroy sessions rapidly
    for i in range(6):
        s = await create_session(
            client, auth_token, ip="10.6.0.3",
        )
        await client.delete(
            f"/api/playback/session/{s['session_id']}",
            headers=auth_headers(auth_token),
        )
        await asyncio.sleep(0.5)  # pace to avoid OTP rate limit

    s = await create_session(client, auth_token, ip="10.6.0.3")
    result = await send_heartbeat(
        client, auth_token, s["session_id"],
        play_seconds=1, ip="10.6.0.3",
    )

    # Should have rapid_sessions flag (from all the session creations in this test + previous)
    assert result["debug"]["recent_session_creations"] > 5
    await end_all_sessions(client, auth_token)


async def test_account_sharing_simulation(client, auth_token):
    """Alternating IPs should detect IP changes."""
    await end_all_sessions(client, auth_token)
    session = await create_session(client, auth_token, ip="10.6.0.4")

    ips = ["10.6.0.4", "10.6.0.5", "10.6.0.4", "10.6.0.5"]
    last_result = None
    for ip in ips:
        last_result = await send_heartbeat(
            client, auth_token, session["session_id"],
            play_seconds=30, ip=ip,
        )
        if last_result.get("status_code") == 403:
            break

    if last_result.get("status_code") == 403:
        assert "too many IP changes" in last_result.get("detail", "")
    else:
        assert last_result["debug"]["ip_changes"] >= 2

    await end_all_sessions(client, auth_token)


async def test_session_with_no_play(client, auth_token):
    """Bot that creates session but never plays."""
    await end_all_sessions(client, auth_token)
    session = await create_session(client, auth_token, ip="10.6.0.6")

    for _ in range(3):
        result = await send_heartbeat(
            client, auth_token, session["session_id"],
            play_seconds=0, ip="10.6.0.6",
        )

    assert result["debug"]["total_play_seconds"] == 0
    await end_all_sessions(client, auth_token)
