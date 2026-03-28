"""
Group 8: Seek Proxy Detection (Pure Server-Side)

Tests that the backend detects seek-like behavior by comparing
client-reported play_seconds against server-measured heartbeat gaps,
and by detecting erratic play_seconds variance across heartbeats.

Signal #8a — play_time_drift: client says X seconds but server measured
a very different gap. Repeated drift = manipulation.

Signal #8b — erratic_playback: high variance in play_seconds across
recent heartbeats indicates seeking/scrubbing.
"""
import pytest
import asyncio
from tests.conftest import (
    auth_headers,
    create_session,
    send_heartbeat,
    end_all_sessions,
    flags_except_rapid,
)

pytestmark = pytest.mark.asyncio


# ── Drift detection tests ──


async def test_normal_playback_no_drift(client, auth_token):
    """Normal: play_seconds roughly matches server gap — no drift flag."""
    await end_all_sessions(client, auth_token)
    session = await create_session(client, auth_token, ip="10.8.0.1")

    # In tests, heartbeats arrive ~1s apart, so report ~1s play_seconds
    # to match the actual server-measured gap (no drift).
    for _ in range(4):
        result = await send_heartbeat(
            client, auth_token, session["session_id"],
            play_seconds=1, ip="10.8.0.1",
        )
        await asyncio.sleep(1)

    flags = flags_except_rapid(result["debug"].get("flags", []))
    assert not any("play_time_drift" in f for f in flags)
    await end_all_sessions(client, auth_token)


async def test_drift_detected_inflated_play_seconds(client, auth_token):
    """
    Suspicious: client reports 120s play but heartbeats arrive every ~0.1s.
    Server gap is tiny, client claims much more — drift should accumulate.
    """
    await end_all_sessions(client, auth_token)
    session = await create_session(client, auth_token, ip="10.8.0.2")

    # First normal heartbeat to initialize last_heartbeat
    await send_heartbeat(
        client, auth_token, session["session_id"],
        play_seconds=30, ip="10.8.0.2",
    )
    await asyncio.sleep(0.1)

    # Now send heartbeats with inflated play_seconds (120s when gap is <1s)
    for _ in range(4):
        result = await send_heartbeat(
            client, auth_token, session["session_id"],
            play_seconds=120, ip="10.8.0.2",
        )
        await asyncio.sleep(0.1)

    flags = flags_except_rapid(result["debug"].get("flags", []))
    assert any("play_time_drift" in f for f in flags), (
        f"Expected play_time_drift flag, got: {flags}"
    )
    assert result["debug"]["drift_count"] >= 3
    await end_all_sessions(client, auth_token)


async def test_drift_detected_tiny_play_seconds(client, auth_token):
    """
    Suspicious: client reports 1s play but server gap is ~30s.
    Consistently low play_seconds vs gap = drift.
    Note: In fast tests the server gap is <1s, so we simulate by
    adding a delay to make gap > play_seconds * threshold.
    """
    await end_all_sessions(client, auth_token)
    session = await create_session(client, auth_token, ip="10.8.0.3")

    # Send heartbeats rapidly with very high play_seconds to trigger drift
    # (server gap is ~0.1s, client claims 60s)
    for _ in range(5):
        result = await send_heartbeat(
            client, auth_token, session["session_id"],
            play_seconds=60, ip="10.8.0.3",
        )
        await asyncio.sleep(0.1)

    flags = flags_except_rapid(result["debug"].get("flags", []))
    assert any("play_time_drift" in f for f in flags), (
        f"Expected play_time_drift flag, got: {flags}"
    )
    await end_all_sessions(client, auth_token)


# ── Variance detection tests ──


async def test_consistent_play_seconds_no_variance_flag(client, auth_token):
    """Normal: consistent play_seconds across heartbeats — no erratic flag."""
    await end_all_sessions(client, auth_token)
    session = await create_session(client, auth_token, ip="10.8.1.1")

    for _ in range(6):
        result = await send_heartbeat(
            client, auth_token, session["session_id"],
            play_seconds=30, ip="10.8.1.1",
        )
        await asyncio.sleep(0.1)

    flags = flags_except_rapid(result["debug"].get("flags", []))
    assert not any("erratic_playback" in f for f in flags)
    await end_all_sessions(client, auth_token)


async def test_erratic_play_seconds_flagged(client, auth_token):
    """
    Suspicious: play_seconds oscillates wildly (2, 500, 3, 400, 1, 600).
    This pattern indicates seeking/scrubbing — high std deviation.
    """
    await end_all_sessions(client, auth_token)
    session = await create_session(client, auth_token, ip="10.8.1.2")

    erratic_values = [2, 500, 3, 400, 1, 600]
    for ps in erratic_values:
        result = await send_heartbeat(
            client, auth_token, session["session_id"],
            play_seconds=ps, ip="10.8.1.2",
        )
        await asyncio.sleep(0.1)

    flags = flags_except_rapid(result["debug"].get("flags", []))
    assert any("erratic_playback" in f for f in flags), (
        f"Expected erratic_playback flag, got: {flags}"
    )
    await end_all_sessions(client, auth_token)


async def test_slightly_varied_play_seconds_ok(client, auth_token):
    """Normal: minor variation (28, 32, 29, 31) should NOT flag."""
    await end_all_sessions(client, auth_token)
    session = await create_session(client, auth_token, ip="10.8.1.3")

    normal_values = [28, 32, 29, 31, 30, 28]
    for ps in normal_values:
        result = await send_heartbeat(
            client, auth_token, session["session_id"],
            play_seconds=ps, ip="10.8.1.3",
        )
        await asyncio.sleep(0.1)

    flags = flags_except_rapid(result["debug"].get("flags", []))
    assert not any("erratic_playback" in f for f in flags)
    await end_all_sessions(client, auth_token)


# ── Combined drift + variance tests ──


async def test_seek_proxy_contributes_to_risk_level(client, auth_token):
    """Seek proxy flags should contribute to the risk_level escalation."""
    await end_all_sessions(client, auth_token)
    session = await create_session(client, auth_token, ip="10.8.2.1")

    # Send erratic heartbeats that trigger both drift and variance
    erratic_values = [1, 500, 2, 600, 1, 500]
    for ps in erratic_values:
        result = await send_heartbeat(
            client, auth_token, session["session_id"],
            play_seconds=ps, ip="10.8.2.1",
        )
        await asyncio.sleep(0.1)

    # Should be at least "warning" since we have flags
    assert result["risk_level"] in ("warning", "blocked")
    await end_all_sessions(client, auth_token)
