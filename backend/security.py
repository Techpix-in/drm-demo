import json
import logging
import time
from typing import Dict, List, Set, Tuple

from fastapi import HTTPException

from config import (
    IMPOSSIBLE_TRAVEL_WINDOW,
    MAX_FINGERPRINTS_PER_USER,
    RISK_SCORE_DECAY_SECONDS,
    RISK_SCORE_THRESHOLD,
)

# ─── Structured Audit Logger ─────────────────────────────────────────────

logger = logging.getLogger("securestream.audit")
logger.setLevel(logging.INFO)

if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    )
    logger.addHandler(handler)


def audit_log(
    event_type: str,
    user_id: str = "",
    ip: str = "",
    details: dict = None,
) -> None:
    """Write a structured audit log entry."""
    entry = {
        "event": event_type,
        "user_id": user_id,
        "ip": ip,
        "timestamp": time.time(),
    }
    if details:
        entry["details"] = details

    level = logging.INFO
    if event_type in ("ANOMALY_DETECTED", "LOGIN_FAILED"):
        level = logging.WARNING
    elif event_type == "USER_BLOCKED":
        level = logging.ERROR

    logger.log(level, json.dumps(entry))


# ─── Risk Score Tracker ──────────────────────────────────────────────────

# user_id -> list of (timestamp, points, reason)
_risk_scores: Dict[str, List[Tuple[float, int, str]]] = {}

# user_id -> set of fingerprints seen
_user_fingerprints: Dict[str, Set[str]] = {}

# user_id -> list of (timestamp, ip_address, fingerprint)
_user_request_history: Dict[str, List[Tuple[float, str, str]]] = {}


def add_risk_points(user_id: str, points: int, reason: str, ip: str = "") -> None:
    """Add risk points to a user's score."""
    if user_id not in _risk_scores:
        _risk_scores[user_id] = []
    _risk_scores[user_id].append((time.time(), points, reason))

    audit_log(
        "ANOMALY_DETECTED",
        user_id=user_id,
        ip=ip,
        details={"points": points, "reason": reason},
    )


def get_risk_score(user_id: str) -> int:
    """Get current risk score (expired points are pruned)."""
    if user_id not in _risk_scores:
        return 0

    now = time.time()
    cutoff = now - RISK_SCORE_DECAY_SECONDS

    # Prune expired entries
    entries = [(t, p, r) for t, p, r in _risk_scores[user_id] if t > cutoff]
    _risk_scores[user_id] = entries

    return sum(p for _, p, _ in entries)


def check_user_risk(user_id: str, ip: str = "") -> None:
    """Raise 403 if user's risk score exceeds threshold."""
    score = get_risk_score(user_id)
    if score >= RISK_SCORE_THRESHOLD:
        audit_log(
            "USER_BLOCKED",
            user_id=user_id,
            ip=ip,
            details={"risk_score": score},
        )
        raise HTTPException(
            status_code=403,
            detail="Account temporarily blocked due to suspicious activity. Try again later.",
        )


def analyze_request(user_id: str, ip: str, fingerprint: str) -> None:
    """
    Analyze an OTP request for suspicious patterns.
    Runs 3 checks and accumulates risk points.
    Raises 403 if risk threshold is exceeded.
    """
    now = time.time()

    # Initialize stores
    if user_id not in _user_request_history:
        _user_request_history[user_id] = []
    if user_id not in _user_fingerprints:
        _user_fingerprints[user_id] = set()

    history = _user_request_history[user_id]

    # ── Check 1: Impossible travel (different IP within window) ──
    for ts, prev_ip, _ in reversed(history):
        if now - ts > IMPOSSIBLE_TRAVEL_WINDOW:
            break
        if prev_ip != ip:
            add_risk_points(
                user_id, 30,
                f"Different IP within {IMPOSSIBLE_TRAVEL_WINDOW}s: {prev_ip} -> {ip}",
                ip=ip,
            )
            break  # Only flag once per request

    # ── Check 2: Fingerprint proliferation ──
    _user_fingerprints[user_id].add(fingerprint)
    if len(_user_fingerprints[user_id]) > MAX_FINGERPRINTS_PER_USER:
        add_risk_points(
            user_id, 25,
            f"Too many devices: {len(_user_fingerprints[user_id])} unique fingerprints",
            ip=ip,
        )

    # ── Check 3: Rapid fingerprint switching ──
    if history:
        last_ts, _, last_fp = history[-1]
        if last_fp != fingerprint and (now - last_ts) < 60:
            add_risk_points(
                user_id, 20,
                f"Fingerprint switched within 60s: {last_fp[:8]}.. -> {fingerprint[:8]}..",
                ip=ip,
            )

    # Record this request
    history.append((now, ip, fingerprint))

    # Keep history bounded (last 100 entries)
    if len(history) > 100:
        _user_request_history[user_id] = history[-100:]

    # Final risk check — may raise 403
    check_user_risk(user_id, ip)
