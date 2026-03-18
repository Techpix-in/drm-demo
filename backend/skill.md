# Backend Service — SecureStream API (FastAPI)

## Overview

FastAPI backend serving as the security layer between the frontend and VdoCipher's DRM video hosting. Implements multi-layered anti-piracy protection with PostgreSQL for persistent data and Redis for ephemeral/real-time data.

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
    ├── Request Playback ───────→ /api/video/otp (requires auth)
    │   [rate limit] → [anomaly detection] → [concurrent check] → [tier check] → VdoCipher API
    │   ← otp + playbackInfo + session_id + tier + max_resolution
    │
    ├── Heartbeat (every 30s) ──→ /api/playback/heartbeat
    │   Sends: session_id + playback_events (seek_count, restart_count, play_seconds)
    │   Validates: IP binding + behavioral analysis
    │   ← status + risk_level
    │
    └── End Session ────────────→ DELETE /api/playback/session/{id}

Backend (FastAPI :8000)
    │
    ├── PostgreSQL (69.62.82.132:5432) — Users, Videos, Audit Logs
    └── Redis (69.62.82.132:6379) — Sessions, Rate Limits, Risk Scores, Behavioral Data
```

## Folder Structure

```
backend/
├── app/
│   ├── main.py              # FastAPI app, lifecycle (startup/shutdown), router registration
│   ├── config.py            # All settings from env vars
│   ├── api/                 # Route handlers (thin — delegate to core/services)
│   │   ├── auth.py          # Login, logout, refresh, me
│   │   ├── videos.py        # Video catalog endpoints
│   │   ├── playback.py      # OTP generation, heartbeat, session management
│   │   └── health.py        # Health check
│   ├── core/                # Business logic
│   │   ├── auth.py          # Token signing/verification, user auth (queries Postgres)
│   │   ├── middleware.py    # Rate limiting (Redis sliding window), IP/fingerprint extraction
│   │   └── security.py     # Risk scoring, anomaly detection (Redis), audit logging (Postgres)
│   ├── db/                  # Data layer
│   │   ├── postgres.py      # SQLAlchemy async engine, table definitions (UserDB, VideoDB, AuditLogDB)
│   │   ├── redis.py         # Redis async connection pool
│   │   └── seed.py          # Seeds initial users + videos on first startup
│   ├── models/
│   │   └── schemas.py       # Pydantic request/response models
│   └── services/            # External integrations + domain logic
│       ├── sessions.py      # Playback session CRUD (Redis hashes + sorted sets)
│       ├── vdocipher.py     # VdoCipher OTP generation with tier-based controls
│       └── videos.py        # Video CRUD (Postgres queries)
├── Dockerfile
├── requirements.txt
└── .env                     # Environment variables (not committed)
```

## Data Storage

| Data | Store | Why |
|------|-------|-----|
| Users (email, password_hash, role) | **PostgreSQL** | Persistent, queryable, relational |
| Videos (id, title, description) | **PostgreSQL** | Persistent catalog |
| Audit Logs (event, user, ip, details) | **PostgreSQL** | Persistent, queryable for investigations |
| Playback Sessions | **Redis** (hash + set) | Fast, auto-expires via TTL (90s) |
| Rate Limits | **Redis** (sorted set) | Sliding window, auto-cleanup |
| Risk Scores | **Redis** (sorted set + hash) | Decays after 1 hour |
| Token Revocations | **Redis** (key with TTL) | Expires with token lifetime |
| Behavioral Data (seeks, restarts) | **Redis** (sorted set per session) | Ephemeral, tied to session lifetime |
| Request History (IPs, fingerprints) | **Redis** (list) | Rolling window for anomaly detection |

## API Routes

| Method | Endpoint | Auth | What It Does |
|--------|----------|------|-------------|
| POST | `/api/auth/login` | No | Authenticates against Postgres, returns tokens. Rate-limited: 5/15min per IP. |
| POST | `/api/auth/refresh` | No | Exchanges refresh token for new session token. Verifies device fingerprint. |
| POST | `/api/auth/logout` | Yes | Revokes token in Redis, ends all playback sessions. |
| GET | `/api/auth/me` | Yes | Returns current user info. |
| GET | `/api/videos` | Yes | Returns video catalog from Postgres. |
| GET | `/api/videos/{id}` | Yes | Returns single video metadata. |
| POST | `/api/video/otp` | Yes | **Core endpoint.** Tier-aware OTP generation with all security layers. |
| POST | `/api/playback/heartbeat` | Yes | Validates IP binding, analyzes behavioral events, refreshes session TTL. |
| DELETE | `/api/playback/session/{id}` | Yes | Ends a playback session. |
| GET | `/api/playback/sessions` | Yes | Lists active sessions for user. |
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

### `app/services/sessions.py` — Playback Sessions (Redis)

**Redis keys per session:**
- `session:{session_id}` — hash with session data (TTL: 90s, refreshed on heartbeat)
- `user_sessions:{user_id}` — set of active session IDs
- `seeks:{session_id}` — sorted set of seek event timestamps
- `restarts:{session_id}` — sorted set of restart event timestamps

**IP Binding:** Heartbeat validates IP hasn't changed. 3+ IP changes → session killed.

**Behavioral Detection (on heartbeat):**
1. **Excessive Seeking** (>15/min): Detects ripping tools that seek through video
2. **Rapid Restarts** (>10/hr): Detects automation scripts
3. **Continuous Play** (>8h): Nobody watches 8 hours straight

**Page Refresh Handling:** Same user+video+device reuses existing session instead of creating new one.

### `app/services/vdocipher.py` — VdoCipher Integration

**Tier-based OTP generation:**

| Tier | OTP TTL | Max Resolution | Watermark |
|------|---------|---------------|-----------|
| `browser` | 120s | 480p | Yes |
| `mobile_app` | 300s | 1080p | Yes |
| `smart_tv` | 300s | 4K | Yes |

**Dynamic Forensic Watermark:**
- 10% opacity (near-invisible to viewers)
- Moves every 3 seconds (harder to crop out)
- Contains: `userId|timestamp|deviceFingerprint`
- Survives re-encoding and cropping

**OTP parameters sent to VdoCipher:**

| Parameter | Value | Purpose |
|-----------|-------|---------|
| `ttl` | 120s (browser) / 300s (mobile) | Prevents token sharing |
| `annotate` | Dynamic watermark | Forensic tracing of leaks |
| `userId` | user_id (max 36 chars) | VdoCipher viewer analytics |
| `whitelisthref` | production domain | Blocks playback on pirate sites |

### `app/db/postgres.py` — Database Tables

**`users`**: id, email, name, password_hash, role, is_active, created_at, updated_at
**`videos`**: id (VdoCipher ID), title, description, thumbnail, duration, is_active, created_at
**`audit_logs`**: id, event_type, user_id, ip_address, details (JSON), created_at

### `app/db/seed.py` — Initial Data

On first startup (tables empty), seeds:
- 2 users: `viewer@example.com` / `demo123`, `admin@example.com` / `admin123`
- 1 video: VdoCipher video ID `bd3ca7a235663ed1570e305f3775414a`

## Security Layers (applied on every OTP request)

```
Request arrives at POST /api/video/otp
    │
    ├── Layer 1: Authentication (Bearer token + device binding)
    ├── Layer 2: Rate Limiting (10 req/min per user — Redis)
    ├── Layer 3: Anomaly Detection (impossible travel, fingerprint abuse — Redis)
    ├── Layer 4: Concurrent Stream Limit (max 2 active sessions — Redis)
    ├── Layer 5: Tier-Based Controls (browser=480p/120s, mobile=1080p/300s)
    ├── Layer 6: Dynamic Forensic Watermark (10% opacity, moves every 3s)
    └── Layer 7: Behavioral Monitoring (seeks, restarts, continuous play — Redis)
    │
    ← Returns: otp + playbackInfo + session_id + tier + max_resolution
```

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
