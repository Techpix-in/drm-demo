# Backend Service — SecureStream API (FastAPI)

## Overview

This is the FastAPI backend that serves as the security layer between the frontend and VdoCipher's DRM video hosting. It implements 7 layers of anti-piracy protection to prevent browser-based content downloading.

## How to Run

```bash
cd backend
python3 -m uvicorn main:app --reload --port 8000
```

## Architecture

```
Frontend (Next.js :3000)
    │
    ├── Login ──────────────────→ /api/auth/login
    │   ← session_token + refresh_token
    │
    ├── Get Videos ─────────────→ /api/videos (requires auth)
    │
    ├── Request Playback ───────→ /api/video/otp (requires auth)
    │   [rate limit] → [anomaly detection] → [concurrent check] → VdoCipher API
    │   ← otp + playbackInfo + session_id
    │
    ├── Heartbeat (every 30s) ──→ /api/playback/heartbeat
    │
    └── End Session ────────────→ DELETE /api/playback/session/{id}
```

## File-by-File Explanation

### `main.py` — Application Entry Point

The FastAPI app that wires all modules together. Defines all API routes and a background task for session cleanup.

**Routes:**

| Method | Endpoint | Auth | What It Does |
|--------|----------|------|-------------|
| POST | `/api/auth/login` | No | Authenticates user, returns session + refresh tokens. Rate-limited to 5 attempts per 15min per IP. |
| POST | `/api/auth/refresh` | No | Exchanges a valid refresh token for a new session token. Verifies device fingerprint matches. |
| POST | `/api/auth/logout` | Yes | Revokes the session token and terminates all active playback sessions for the user. |
| GET | `/api/auth/me` | Yes | Returns the currently authenticated user's info. |
| GET | `/api/videos` | Yes | Returns the video catalog. |
| GET | `/api/videos/{id}` | Yes | Returns a single video's metadata. |
| POST | `/api/video/otp` | Yes | **Core endpoint.** Generates a DRM playback token. This is where all 7 security layers are applied (see below). |
| POST | `/api/playback/heartbeat` | Yes | Keeps a playback session alive. Must be called every 30 seconds. |
| DELETE | `/api/playback/session/{id}` | Yes | Ends a specific playback session, freeing up a concurrent stream slot. |
| GET | `/api/playback/sessions` | Yes | Lists all active playback sessions for the user. |
| GET | `/api/health` | No | Health check. |

**Background Task:** Every 30 seconds, `cleanup_expired_sessions()` runs to remove sessions that haven't received a heartbeat within 90 seconds.

---

### `config.py` — Configuration

Loads environment variables and defines anti-piracy constants.

| Setting | Default | What It Controls |
|---------|---------|-----------------|
| `VDOCIPHER_API_SECRET` | (required) | VdoCipher API key for OTP generation |
| `SESSION_SECRET` | dev-secret | HMAC key for signing session/refresh tokens |
| `MAX_CONCURRENT_STREAMS` | 2 | How many videos a user can watch simultaneously |
| `SESSION_TOKEN_TTL` | 3600 (1h) | How long a session token is valid |
| `REFRESH_TOKEN_TTL` | 604800 (7d) | How long a refresh token is valid |
| `SESSION_EXPIRY` | 90s | How long a playback session survives without heartbeat |
| `LOGIN_RATE_LIMIT` | 5/15min | Max login attempts per IP |
| `OTP_RATE_LIMIT` | 10/1min | Max OTP requests per user |
| `RISK_SCORE_THRESHOLD` | 100 | Risk score at which a user is temporarily blocked |

---

### `auth.py` — Authentication & Token Management

Handles user login, token creation, verification, and revocation.

**How tokens work:**
- Tokens are JSON payloads signed with HMAC-SHA256. Format: `{json_payload}|{signature}`
- Session tokens expire in 1 hour, refresh tokens in 7 days
- Both tokens embed a `device_fingerprint` — if a token is used from a different device, it's rejected
- On logout, the token's signature is added to a revocation set so it can't be reused

**Key functions:**
- `create_session_token(user, fingerprint)` — Creates a 1-hour session token bound to the device
- `create_refresh_token(user, fingerprint)` — Creates a 7-day refresh token bound to the device
- `verify_session_token(token, fingerprint)` — Verifies signature, expiry, revocation, and device match
- `verify_refresh_token(token, fingerprint)` — Same as above but for refresh tokens
- `revoke_token(token)` — Adds token signature to blocklist
- `get_current_user(request)` — FastAPI dependency that extracts and verifies the user from the Authorization header

---

### `middleware.py` — Rate Limiting & Device Fingerprinting

**Rate Limiter (`InMemoryRateLimiter`):**
- Sliding window algorithm using in-memory dict of timestamps
- `check(key, limit, window)` — Returns True if the request is allowed
- When a limit is hit, the API returns HTTP 429 with a `Retry-After` header

**Device Fingerprint:**
- `get_device_fingerprint(request)` — Reads the `X-Device-Fingerprint` header sent by the frontend
- If the header is missing, it generates a fallback fingerprint from `SHA256(User-Agent + IP)` (truncated to 16 chars)
- The fingerprint is used for: device binding in tokens, anomaly detection, watermarking

**Client IP:**
- `get_client_ip(request)` — Reads `X-Forwarded-For` (for proxied setups) or falls back to `request.client.host`

---

### `security.py` — Anomaly Detection & Audit Logging

**Audit Logger:**
- `audit_log(event_type, user_id, ip, details)` — Writes structured JSON log entries
- Log levels: INFO for normal events, WARNING for anomalies, ERROR for blocks
- Events tracked: `LOGIN_SUCCESS`, `LOGIN_FAILED`, `OTP_GENERATED`, `ANOMALY_DETECTED`, `USER_BLOCKED`, `LOGOUT`

**Risk Score System:**
- Each user accumulates risk points from suspicious behavior
- Points decay after 1 hour (so legitimate users recover)
- At 100 points, the user is temporarily blocked (HTTP 403)

**`analyze_request(user_id, ip, fingerprint)` — runs 3 checks on every OTP request:**

1. **Impossible Travel** (+30 points): If the user's IP changes within 5 minutes. Catches VPN-hopping or token sharing between different networks.

2. **Fingerprint Proliferation** (+25 points): If a user has used more than 5 different device fingerprints. Catches credential sharing across many devices.

3. **Rapid Fingerprint Switching** (+20 points): If the device fingerprint changes within 60 seconds of the last request. Catches automated tools that rotate browser profiles.

---

### `sessions.py` — Concurrent Stream Limiting

Tracks active playback sessions and enforces a per-user limit.

**How it works:**
1. When a user requests an OTP (`/api/video/otp`), a playback session is created
2. The frontend sends a heartbeat every 30 seconds to keep the session alive
3. If no heartbeat arrives within 90 seconds, the session is considered dead
4. If the user tries to start a 3rd stream (with limit = 2), they get HTTP 403

**Key functions:**
- `create_playback_session(user_id, video_id, fingerprint, ip)` — Creates a session, returns session_id. Raises 403 if at limit.
- `heartbeat(session_id)` — Updates the last_heartbeat timestamp
- `end_session(session_id)` — Explicitly ends a session (called on page unmount or logout)
- `cleanup_expired_sessions()` — Background cleanup of dead sessions

---

### `vdocipher.py` — VdoCipher DRM Integration

Calls VdoCipher's OTP API with all security parameters.

**`generate_otp(video_id, user, ip_address, device_fingerprint)` sends:**

| Parameter | Value | What It Does |
|-----------|-------|-------------|
| `ttl` | 300 (5min) | OTP expires in 5 minutes — prevents token sharing |
| `annotate` | `[{type:"rtext", text:"email\|user_id\|fingerprint"}]` | Forensic watermark burned into the video stream with the viewer's identity |
| `ipGeo` | `{"allow": ["viewer_ip"]}` | Locks the OTP to the viewer's current IP address |
| `licenseRules` | `{"canPersist": false}` | **Most impactful parameter.** Tells the DRM CDM to reject any attempt to save decryption keys for offline use. Blocks most ripping tools. |
| `userId` | user_id (max 36 chars) | Enables VdoCipher's viewer analytics dashboard |
| `whitelisthref` | production domain | Locks playback to your domain only (prevents iframe embedding on pirate sites) |

---

### `models.py` — Pydantic Data Models

Defines all request/response schemas used by the API. Key models:
- `LoginResponse` — includes both `token` and `refresh_token`
- `OTPResponse` — includes `session_id` for heartbeat tracking
- `PlaybackSession` — tracks session_id, user, video, device, IP, timestamps
- `ActiveSessionsResponse` — lists sessions with `max_allowed` count

---

### `videos.py` — Video Catalog

Hardcoded list of VdoCipher video IDs with metadata. In production, replace with a database.

---

## 7 Security Layers (applied on every OTP request)

```
Request arrives at POST /api/video/otp
    │
    ├── Layer 1: Authentication (Bearer token with device binding)
    ├── Layer 2: Rate Limiting (10 req/min per user)
    ├── Layer 3: Anomaly Detection (impossible travel, fingerprint abuse)
    ├── Layer 4: Concurrent Stream Limit (max 2 active sessions)
    ├── Layer 5: IP-Bound OTP (VdoCipher ipGeo locks to viewer's IP)
    ├── Layer 6: canPersist: false (blocks offline ripping tools)
    └── Layer 7: Forensic Watermark (viewer identity burned into stream)
    │
    ← Returns: otp + playbackInfo + session_id
```

## Environment Variables

Create a `.env` file in the backend directory:

```
VDOCIPHER_API_SECRET=your_api_secret_here
SESSION_SECRET=a-long-random-string-for-production
FRONTEND_URL=http://localhost:3000
ALLOWED_DOMAIN=
MAX_CONCURRENT_STREAMS=2
SESSION_TOKEN_TTL=3600
```
