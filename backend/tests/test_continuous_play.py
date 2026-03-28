"""
Group 4: Continuous Play Detection

Tests that sessions playing for extremely long durations are flagged.
"""
import pytest
from tests.conftest import create_session, send_heartbeat, end_all_sessions

pytestmark = pytest.mark.asyncio


async def test_normal_duration_no_flag(client, auth_token):
    """Normal: 2 hours of play time — no flag."""
    await end_all_sessions(client, auth_token)
    session = await create_session(client, auth_token, ip="10.2.0.1")

    # Simulate 2 hours: send one heartbeat with 7200s of play
    result = await send_heartbeat(
        client, auth_token, session["session_id"],
        play_seconds=7200, ip="10.2.0.1",
    )

    assert not any("continuous_play" in f for f in result["debug"].get("flags", []))
    assert result["debug"]["total_play_seconds"] == 7200
    await end_all_sessions(client, auth_token)


async def test_ten_plus_hours_flagged(client, auth_token):
    """Flagged: 10+ hours of continuous play should trigger."""
    await end_all_sessions(client, auth_token)
    session = await create_session(client, auth_token, ip="10.2.0.2")

    # Send play_seconds that exceeds 10 hours (36001 seconds)
    result = await send_heartbeat(
        client, auth_token, session["session_id"],
        play_seconds=36001, ip="10.2.0.2",
    )

    assert any("continuous_play" in f for f in result["debug"].get("flags", []))
    await end_all_sessions(client, auth_token)


async def test_just_under_threshold_no_flag(client, auth_token):
    """Edge: just under 10 hours (35999s) should NOT flag."""
    await end_all_sessions(client, auth_token)
    session = await create_session(client, auth_token, ip="10.2.0.3")

    result = await send_heartbeat(
        client, auth_token, session["session_id"],
        play_seconds=35999, ip="10.2.0.3",
    )

    assert not any("continuous_play" in f for f in result["debug"].get("flags", []))
    await end_all_sessions(client, auth_token)
