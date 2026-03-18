import json
import logging
import time

from fastapi import HTTPException

from app.config import (
    IMPOSSIBLE_TRAVEL_WINDOW,
    MAX_FINGERPRINTS_PER_USER,
    RISK_SCORE_DECAY_SECONDS,
    RISK_SCORE_THRESHOLD,
)
from app.db.postgres import async_session, AuditLogDB
from app.db.redis import get_redis

logger = logging.getLogger("securestream.audit")
logger.setLevel(logging.INFO)

if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(handler)


async def audit_log(
    event_type: str, user_id: str = "", ip: str = "", details: dict = None
) -> None:
    entry = {"event": event_type, "user_id": user_id, "ip": ip, "timestamp": time.time()}
    if details:
        entry["details"] = details

    level = logging.INFO
    if event_type in ("ANOMALY_DETECTED", "LOGIN_FAILED"):
        level = logging.WARNING
    elif event_type == "USER_BLOCKED":
        level = logging.ERROR

    logger.log(level, json.dumps(entry))

    try:
        async with async_session() as session:
            session.add(AuditLogDB(
                event_type=event_type,
                user_id=user_id,
                ip_address=ip,
                details=json.dumps(details) if details else "",
            ))
            await session.commit()
    except Exception as e:
        logger.error(f"Failed to persist audit log: {e}")


async def add_risk_points(user_id: str, points: int, reason: str, ip: str = "") -> None:
    r = get_redis()
    now = time.time()
    key = f"risk:{user_id}"
    member = f"{reason}:{now}"

    await r.zadd(key, {member: now})
    await r.hset(f"risk_points:{user_id}", member, str(points))
    await r.expire(key, RISK_SCORE_DECAY_SECONDS + 60)
    await r.expire(f"risk_points:{user_id}", RISK_SCORE_DECAY_SECONDS + 60)

    await audit_log("ANOMALY_DETECTED", user_id=user_id, ip=ip, details={"points": points, "reason": reason})


async def get_risk_score(user_id: str) -> int:
    r = get_redis()
    now = time.time()
    cutoff = now - RISK_SCORE_DECAY_SECONDS
    key = f"risk:{user_id}"

    await r.zremrangebyscore(key, 0, cutoff)
    members = await r.zrange(key, 0, -1)
    if not members:
        return 0

    total = 0
    for member in members:
        pts = await r.hget(f"risk_points:{user_id}", member)
        if pts:
            total += int(pts)
    return total


async def check_user_risk(user_id: str, ip: str = "") -> None:
    score = await get_risk_score(user_id)
    if score >= RISK_SCORE_THRESHOLD:
        await audit_log("USER_BLOCKED", user_id=user_id, ip=ip, details={"risk_score": score})
        raise HTTPException(
            status_code=403,
            detail="Account temporarily blocked due to suspicious activity. Try again later.",
        )


async def analyze_request(user_id: str, ip: str, fingerprint: str) -> None:
    r = get_redis()
    now = time.time()
    history_key = f"request_history:{user_id}"
    fp_key = f"fingerprints:{user_id}"

    recent = await r.lrange(history_key, 0, 0)
    if recent:
        last_entry = json.loads(recent[0])
        if last_entry["ip"] != ip and (now - last_entry["ts"]) < IMPOSSIBLE_TRAVEL_WINDOW:
            await add_risk_points(user_id, 30, f"ip_change:{last_entry['ip']}->{ip}", ip=ip)

    await r.sadd(fp_key, fingerprint)
    await r.expire(fp_key, RISK_SCORE_DECAY_SECONDS)
    fp_count = await r.scard(fp_key)
    if fp_count > MAX_FINGERPRINTS_PER_USER:
        await add_risk_points(user_id, 25, f"too_many_devices:{fp_count}", ip=ip)

    if recent:
        last_entry = json.loads(recent[0])
        if last_entry.get("fp") != fingerprint and (now - last_entry["ts"]) < 60:
            await add_risk_points(
                user_id, 20,
                f"fp_switch:{last_entry.get('fp', '')[:8]}->{fingerprint[:8]}",
                ip=ip,
            )

    entry = json.dumps({"ts": now, "ip": ip, "fp": fingerprint})
    await r.lpush(history_key, entry)
    await r.ltrim(history_key, 0, 99)
    await r.expire(history_key, RISK_SCORE_DECAY_SECONDS)

    await check_user_risk(user_id, ip)
