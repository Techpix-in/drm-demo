# Backend Service — SecureStream API (FastAPI)

## Overview

FastAPI backend serving as the security layer between the frontend and VdoCipher's DRM video hosting. Implements multi-layered anti-piracy protection with PostgreSQL for persistent data and Redis for ephemeral/real-time data. All anomaly detection runs server-side — no reliance on client-reported behavioral events.

## How to Run

```bash
# Using Docker (recommended)
docker compose up --build -d

# Or using the start script (starts everything)
./start.sh
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
    ├── Sync Videos ────────────→ POST /api/videos/sync (fetches from VdoCipher API)
    │
    ├── Request Playback ───────→ /api/video/otp (requires auth)
    │   [rate limit] → [concurrent check] → [tier check] → VdoCipher API
    │   ← otp + playbackInfo + session_id + tier + max_resolution
    │
    ├── Heartbeat (every 30s) ──→ /api/playback/heartbeat
    │   Sends: session_id + playback_events (play_seconds = wall-clock elapsed)
    │   Server runs: 8 anomaly signals, persists flags for watermark decisions
    │   ← status + risk_level + debug (flags, watermark_active, play_ratio, etc.)
    │
    ├── OTP Rotation (every 90s) → POST /api/video/otp/rotate
    │   Checks session_has_anomaly() → if flags exist, watermark injected into new OTP
    │
    ├── Debug Info ─────────────→ GET /api/playback/debug/{session_id}
    │   ← session state + rate limits + risk score
    │
    └── End Session ────────────→ DELETE /api/playback/session/{id}

Backend (FastAPI :8000)
    │
    ├── PostgreSQL (69.62.82.132:5432) — Users, Videos, Audit Logs
    └── Redis (69.62.82.132:6379) — Sessions, Rate Limits, Risk Scores, Signal Data
```

## Folder Structure

```
backend/
├── app/
│   ├── main.py              # FastAPI app, lifecycle (startup/shutdown), router registration
│   ├── config.py            # All settings from env vars
│   ├── api/                 # Route handlers (thin — delegate to core/services)
│   │   ├── auth.py          # Login, logout, refresh, me
│   │   ├── videos.py        # Video catalog endpoints + VdoCipher sync
│   │   ├── playback.py      # OTP generation, OTP rotation, heartbeat, session management, debug
│   │   └── health.py        # Health check
│   ├── core/                # Business logic
│   │   ├── auth.py          # Token signing/verification, user auth (queries Postgres)
│   │   ├── middleware.py    # Rate limiting (Redis sliding window), IP/fingerprint extraction
│   │   └── security.py     # Risk scoring, anomaly detection (Redis), audit logging (Postgres)
│   ├── db/                  # Data layer
│   │   ├── postgres.py      # SQLAlchemy async engine, table definitions (UserDB, VideoDB, AuditLogDB)
│   │   ├── redis.py         # Redis async connection pool
│   │   └── seed.py          # Seeds initial users on first startup
│   ├── models/
│   │   └── schemas.py       # Pydantic request/response models
│   └── services/            # External integrations + domain logic
│       ├── sessions.py      # Playback session CRUD, heartbeat with 8 server-side signals,
│       │                    # session_has_anomaly() for watermark decisions
│       ├── vdocipher.py     # VdoCipher OTP generation with conditional watermark + tier config
│       └── videos.py        # Video CRUD (Postgres) + VdoCipher catalog sync
├── tests/                   # Integration tests (require running backend + Redis + Postgres)
│   ├── conftest.py          # Shared fixtures (auth, session creation, heartbeat helpers)
│   ├── test_session_mgmt.py # Session reuse, concurrent limits, heartbeat, expiry
│   ├── test_ip_detection.py # IP change detection and session termination
│   ├── test_play_ratio.py   # Low play ratio detection
│   ├── test_continuous_play.py # Continuous play hour detection
│   ├── test_rapid_sessions.py  # Rapid session creation detection
│   ├── test_seek_proxy.py   # Play-time drift and variance detection
│   ├── test_combined_attacks.py # Multi-signal attack simulations
│   └── test_rate_limiting.py    # Login and OTP rate limit tests
├── pytest.ini
├── Dockerfile
├── requirements.txt
└── .env                     # Environment variables (not committed)
```

## Data Storage

| Data | Store | Why |
|------|-------|-----|
| Users (email, password_hash, role) | **PostgreSQL** | Persistent, queryable, relational |
| Videos (id, title, description) | **PostgreSQL** | Persistent catalog, synced from VdoCipher |
| Audit Logs (event, user, ip, details) | **PostgreSQL** | Persistent, queryable for investigations |
| Playback Sessions | **Redis** (hash + set) | Fast, auto-expires via TTL (90s) |
| Rate Limits | **Redis** (sorted set) | Sliding window, auto-cleanup |
| Risk Scores | **Redis** (sorted set + hash) | Decays after 1 hour |
| Token Revocations | **Redis** (key with TTL) | Expires with token lifetime |
| Session Creation Rate | **Redis** (sorted set per user) | Rapid creation detection, 10min window |
| Ghost Session Tracking | **Redis** (sorted set per user) | Detect sessions that never heartbeat |
| Play-Time Deltas | **Redis** (list per session) | Drift and variance detection (last 6 values) |
| Session Flags | **Redis** (field in session hash) | Persisted anomaly flags for watermark decisions |

## API Routes

| Method | Endpoint | Auth | What It Does |
|--------|----------|------|-------------|
| POST | `/api/auth/login` | No | Authenticates against Postgres, returns tokens. Rate-limited: 5/15min per IP. |
| POST | `/api/auth/refresh` | No | Exchanges refresh token for new session token. Verifies device fingerprint. |
| POST | `/api/auth/logout` | Yes | Revokes token in Redis, ends all playback sessions. |
| GET | `/api/auth/me` | Yes | Returns current user info. |
| GET | `/api/videos` | Yes | Returns video catalog from Postgres. |
| GET | `/api/videos/{id}` | Yes | Returns single video metadata. |
| POST | `/api/videos/sync` | Yes | Fetches all videos from VdoCipher API and upserts into Postgres. |
| POST | `/api/video/otp` | Yes | **Core endpoint.** Tier-aware OTP generation with all security layers. |
| POST | `/api/video/otp/rotate` | Yes | Rotate OTP for active session. Checks `session_has_anomaly()` — enables watermark if flags exist. |
| POST | `/api/playback/heartbeat` | Yes | Runs 8 server-side anomaly signals, persists flags, refreshes session TTL. |
| DELETE | `/api/playback/session/{id}` | Yes | Ends a playback session. |
| GET | `/api/playback/sessions` | Yes | Lists active sessions for user. |
| GET | `/api/playback/debug/{id}` | Yes | Returns session state, rate limits, and risk score for debug panel. |
| GET | `/api/health` | No | Health check (v3.0.0). |

## Module Details

### `app/core/auth.py` — Authentication & Tokens

- Tokens are JSON payloads signed with HMAC-SHA256: `{json_payload}|{signature}`
- Session tokens: 1 hour TTL, Refresh tokens: 7 days TTL
- Both embed `device_fingerprint` — rejected if used from a different device
- Token revocation stored in Redis with TTL matching token lifetime
- `authenticate_user()` queries Postgres, verifies bcrypt password hash

### `app/core/middleware.py` — Rate Limiting (Redis)

- **Sliding window algorithm** using Redis sorted sets (not in-memory dicts)
- Each rate limit key: `ratelimit:{type}:{identifier}` with scores as timestamps
- Survives container restarts (Redis-backed)
- Three limiters: login (5/15min per IP), OTP (10/min per user), license (20/min per user)

### `app/core/security.py` — Anomaly Detection & Risk Scoring

**Risk Score System (Redis):**
- Points stored in sorted set `risk:{user_id}` with hash `risk_points:{user_id}`
- Points decay after 1 hour automatically (zremrangebyscore)
- At 100 points → user blocked (HTTP 403)

**`analyze_request()` — 3 checks on every OTP request:**
1. **Impossible Travel** (+30 pts): IP changes within 5 minutes
2. **Fingerprint Proliferation** (+25 pts): >5 unique devices
3. **Rapid Fingerprint Switching** (+20 pts): Device changes within 60 seconds

**Audit Logging:** Writes to both console (structured JSON) and Postgres `audit_logs` table.

### `app/services/sessions.py` — Playback Sessions & Server-Side Signals (Redis)

**Redis keys per session:**
- `session:{session_id}` — hash with session data + `flags` field (TTL: 90s, refreshed on heartbeat)
- `user_sessions:{user_id}` — set of active session IDs
- `session_creations:{user_id}` — sorted set of creation timestamps (rapid creation detection)
- `ghost_check:{user_id}` — sorted set of sessions pending first heartbeat
- `play_deltas:{session_id}` — list of recent play_seconds values (drift/variance detection)

**IP Binding:** Heartbeat validates IP hasn't changed. 3+ IP changes → session killed.

**8 Server-Side Signals (on every heartbeat):**
1. **IP change detection** — Flags IP changes, kills session at 3+
2. **Heartbeat gap detection** — Flags if gap > 75s (missed heartbeat), threshold: 3+ missed
3. **Play ratio detection** — `total_play_seconds / session_age` < 0.3 after 2 min grace period
4. **Continuous play** — Total play > 10 hours
5. **Rapid session creation** — >5 new sessions in 10 minutes for the user
6. **Ghost sessions** — 3+ sessions created with 0 heartbeats
7. **OTP rotation abuse** — Actual rotations > 3x expected (based on session age / 90s interval)
8. **Seek proxy detection** — Play-time drift (client vs server > 50% divergence) + erratic variance (std_dev > 150)

**Risk level determination:**
- 0 flags → `"normal"`
- 1-2 flags → `"warning"` (flags persisted → triggers watermark on next OTP rotation)
- 3+ flags → `"blocked"` (+25 risk points added to global user score)

**Dynamic watermarking integration:**
- Heartbeat persists `flags` field on session hash in Redis
- `session_has_anomaly(session_id)` checks if flags exist
- OTP rotation endpoint calls this before generating OTP — if anomaly present, watermark is enabled
- Debug info includes `watermark_active: bool` field

**Page Refresh Handling:** Same user+video+device reuses existing session instead of creating new one.

### `app/services/vdocipher.py` — VdoCipher Integration

**Tier-based OTP generation:**

| Tier | OTP TTL | Max Resolution |
|------|---------|---------------|
| `browser` | 120s | 480p |
| `mobile_app` | 300s | 1080p |
| `smart_tv` | 300s | 4K |

**Anomaly-Triggered Forensic Watermark:**
- Watermark is OFF by default — enabled only when `enable_watermark=True` is passed
- OTP rotation checks `session_has_anomaly()` and passes the result to `generate_otp()`
- When active: 10% opacity, moves every 3 seconds, contains `userId|timestamp|deviceFingerprint`
- Survives re-encoding and cropping

**Video Catalog Sync:**
- `fetch_all_videos_from_vdocipher()` paginates through VdoCipher API (`/videos?page=N&limit=20`)
- Only includes videos with `status: "ready"` (fully processed)
- `sync_videos_from_vdocipher()` upserts into Postgres (adds new, updates existing, sets `is_active=True`)

**OTP parameters sent to VdoCipher:**

| Parameter | Value | Purpose |
|-----------|-------|---------|
| `ttl` | 120s (browser) / 300s (mobile) | Prevents token sharing |
| `annotate` | Dynamic watermark (only if anomaly detected) | Forensic tracing of leaks |
| `userId` | user_id (max 36 chars) | VdoCipher viewer analytics |
| `whitelisthref` | production domain | Blocks playback on pirate sites |

### `app/db/postgres.py` — Database Tables

**`users`**: id, email, name, password_hash, role, is_active, created_at, updated_at
**`videos`**: id (VdoCipher ID), title, description, thumbnail, duration, is_active, created_at
**`audit_logs`**: id, event_type, user_id, ip_address, details (JSON), created_at

### `app/db/seed.py` — Initial Data

On first startup (tables empty), seeds:
- 2 users: `viewer@example.com` / `demo123`, `admin@example.com` / `admin123`

Videos are synced from VdoCipher via `POST /api/videos/sync` — no longer hardcoded in seed.

## Security Layers (applied on every OTP request)

```
Request arrives at POST /api/video/otp
    │
    ├── Layer 1: Authentication (Bearer token + device binding)
    ├── Layer 2: Rate Limiting (10 req/min per user — Redis)
    ├── Layer 3: Concurrent Stream Limit (max 2 active sessions — Redis)
    ├── Layer 4: Tier-Based Controls (browser=480p/120s, mobile=1080p/300s)
    └── Layer 5: Session created — heartbeat monitoring begins
    │
    ← Returns: otp + playbackInfo + session_id + tier + max_resolution

During playback (every heartbeat):
    │
    ├── Layer 6: 8 Server-Side Anomaly Signals (IP, gaps, ratio, drift, etc.)
    ├── Layer 7: Flag persistence → triggers dynamic watermark on next OTP rotation
    └── Layer 8: Risk score escalation at 3+ simultaneous flags
```

## Configuration Reference

### Server-Side Signal Thresholds (`config.py`)

| Setting | Default | Purpose |
|---------|---------|---------|
| `MAX_CONTINUOUS_PLAY_HOURS` | 10 | Continuous play flag threshold |
| `RAPID_SESSION_CREATION_LIMIT` | 5 | Max new sessions per window |
| `RAPID_SESSION_CREATION_WINDOW` | 600 (10 min) | Window for rapid creation detection |
| `GHOST_SESSION_THRESHOLD` | 3 | Sessions with 0 heartbeats before flagging |
| `MIN_PLAY_RATIO` | 0.3 | Minimum play_seconds/session_age ratio |
| `HEARTBEAT_GAP_TOLERANCE` | 3 | Missed heartbeats before flagging |
| `PLAY_TIME_DRIFT_THRESHOLD` | 0.5 | Client vs server time divergence (50%) |
| `PLAY_TIME_DRIFT_MIN_SAMPLES` | 3 | Heartbeats needed before flagging drift |
| `PLAY_TIME_VARIANCE_WINDOW` | 6 | Number of recent deltas for variance check |
| `PLAY_TIME_VARIANCE_THRESHOLD` | 150.0 | Std deviation threshold for erratic playback |
| `BEHAVIORAL_RISK_POINTS` | 25 | Points added when session is "blocked" |

## Environment Variables

```
# VdoCipher
VDOCIPHER_API_SECRET=your_api_secret_here

# Auth
SESSION_SECRET=a-long-random-string-for-production

# CORS
FRONTEND_URL=http://localhost:3000,https://drm-demo.vercel.app

# VdoCipher domain lock (leave empty for dev)
ALLOWED_DOMAIN=

# Database
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/securestream
REDIS_URL=redis://:password@host:6379/0
```
