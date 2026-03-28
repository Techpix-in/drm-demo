"""Group 1: IP Change Detection"""
import pytest
from tests.conftest import create_session, send_heartbeat, end_all_sessions, flags_except_rapid

pytestmark = pytest.mark.asyncio


async def test_same_ip_no_flag(client, auth_token):
    """Same IP throughout — no flags (except rapid_sessions from test suite)."""
    await end_all_sessions(client, auth_token)
    session = await create_session(client, auth_token, ip="10.0.0.1")
    result = await send_heartbeat(client, auth_token, session["session_id"], ip="10.0.0.1")

    assert result["debug"]["ip_changes"] == 0
    assert not any("ip_change" in f for f in flags_except_rapid(result["debug"].get("flags", [])))
    await end_all_sessions(client, auth_token)


async def test_one_ip_change_warning(client, auth_token):
    """1 IP change should produce an ip_change flag."""
    await end_all_sessions(client, auth_token)
    session = await create_session(client, auth_token, ip="10.0.1.1")
    result = await send_heartbeat(client, auth_token, session["session_id"], ip="10.0.1.2")

    # ip_change flag should be present
    assert any("ip_change" in f for f in result["debug"].get("flags", []))
    await end_all_sessions(client, auth_token)


async def test_three_ip_changes_kills_session(client, auth_token):
    """3 IP changes should terminate the session."""
    await end_all_sessions(client, auth_token)
    session = await create_session(client, auth_token, ip="10.0.2.1")

    await send_heartbeat(client, auth_token, session["session_id"], ip="10.0.2.2")
    await send_heartbeat(client, auth_token, session["session_id"], ip="10.0.2.3")
    result = await send_heartbeat(client, auth_token, session["session_id"], ip="10.0.2.4")

    assert result["status_code"] == 403
    assert "too many IP changes" in result.get("detail", "")
