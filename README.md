# SecureStream — DRM-Protected Video Streaming Platform

A full-stack DRM (Digital Rights Management) video streaming platform built to demonstrate enterprise-grade content protection against browser-based piracy. Uses **VdoCipher** for Widevine/FairPlay DRM encryption with a custom **FastAPI backend** handling session management, behavioral detection, and anti-piracy controls.

> **Goal:** Make large-scale automated downloading impossible and leaks traceable — not to stop piracy completely, but to make it costly, slow, and risky.

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Tech Stack](#tech-stack)
- [DRM Protection Features](#drm-protection-features)
  - [1. Widevine/FairPlay DRM Encryption](#1-widevinefairplay-drm-encryption)
  - [2. OTP Rotation](#2-otp-rotation)
  - [3. Tier-Based Resolution Capping](#3-tier-based-resolution-capping)
  - [4. Dynamic Forensic Watermarking](#4-dynamic-forensic-watermarking)
  - [5. Concurrent Stream Limiting](#5-concurrent-stream-limiting)
  - [6. Behavioral Anomaly Detection](#6-behavioral-anomaly-detection)
  - [7. IP Binding & Impossible Travel Detection](#7-ip-binding--impossible-travel-detection)
  - [8. Device Fingerprinting & Binding](#8-device-fingerprinting--binding)
  - [9. Rate Limiting](#9-rate-limiting)
  - [10. Session-Bound Playback Tokens](#10-session-bound-playback-tokens)
  - [11. Audit Logging](#11-audit-logging)
  - [12. CORS & Content Security Policy](#12-cors--content-security-policy)
  - [13. Mixed Content Proxy](#13-mixed-content-proxy)
- [Backend Architecture](#backend-architecture)
- [Frontend Architecture](#frontend-architecture)
- [API Endpoints](#api-endpoints)
- [Database Schema](#database-schema)
- [Data Flow](#data-flow)
- [Configuration Reference](#configuration-reference)
- [Getting Started](#getting-started)
- [Deployment](#deployment)
- [Demo Credentials](#demo-credentials)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        FRONTEND (Next.js)                       │
│                        Vercel / localhost:3000                   │
│                                                                 │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌───────────────┐   │
│  │LoginForm │  │VideoCard │  │VdoPlayer │  │ AuthProvider  │   │
│  │          │  │          │  │          │  │ (React Context)│   │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └───────┬───────┘   │
│       │              │              │                │           │
│       └──────────────┴──────────────┴────────────────┘           │
│                              │                                   │
│                    /api/* (Next.js Rewrite Proxy)                │
└──────────────────────────────┬───────────────────────────────────┘
                               │ HTTPS → HTTP (server-side)
┌──────────────────────────────┴───────────────────────────────────┐
│                      BACKEND (FastAPI)                           │
│                      Docker / Port 8000                          │
│                                                                  │
│  ┌─────────┐  ┌──────────┐  ┌───────────┐  ┌────────────────┐   │
│  │  Auth   │  │ Playback │  │  Videos   │  │   Middleware   │   │
│  │  API    │  │   API    │  │   API     │  │  (Security)    │   │
│  └────┬────┘  └────┬─────┘  └─────┬─────┘  └───────┬────────┘   │
│       │             │              │                 │            │
│  ┌────┴─────────────┴──────────────┴─────────────────┴────────┐  │
│  │                    Service Layer                            │  │
│  │  ┌──────────┐  ┌────────────┐  ┌────────────────────────┐  │  │
│  │  │ Sessions │  │ VdoCipher  │  │ Anomaly Detection      │  │  │
│  │  │ Manager  │  │ OTP Client │  │ (Behavioral + Request) │  │  │
│  │  └────┬─────┘  └──────┬─────┘  └───────────┬────────────┘  │  │
│  └───────┼───────────────┼─────────────────────┼──────────────┘  │
│          │               │                     │                 │
│  ┌───────┴───────┐  ┌────┴──────┐  ┌───────────┴──────────────┐  │
│  │   Redis       │  │ VdoCipher │  │    PostgreSQL            │  │
│  │  - Sessions   │  │   API     │  │  - Users                 │  │
│  │  - Rate Limits│  │ (External)│  │  - Videos                │  │
│  │  - Risk Scores│  └───────────┘  │  - Audit Logs            │  │
│  │  - Behaviors  │                 └──────────────────────────┘  │
│  └───────────────┘                                               │
└──────────────────────────────────────────────────────────────────┘
```

---

## Tech Stack

### Backend
| Component | Technology | Purpose |
|-----------|-----------|---------|
| Framework | FastAPI 0.115.0 | Async REST API |
| Server | Uvicorn 0.32.0 | ASGI server |
| Database | PostgreSQL + SQLAlchemy 2.0.35 | Persistent storage (users, videos, audit logs) |
| Cache | Redis 5.2.1 (hiredis) | Sessions, rate limiting, risk scores, behavioral data |
| HTTP Client | httpx 0.27.0 | Async VdoCipher API calls |
| Auth | passlib + bcrypt | Password hashing |
| Validation | Pydantic 2.9.0 | Request/response schemas |
| Container | Docker + Docker Compose | Deployment |

### Frontend
| Component | Technology | Purpose |
|-----------|-----------|---------|
| Framework | Next.js 15.1.0 | React SSR + API proxy |
| UI | React 19.0.0 | Component framework |
| Styling | Tailwind CSS 4.0.0 | Utility-first CSS |
| Language | TypeScript 5.7.0 | Type safety |
| DRM Player | VdoCipher iframe | Encrypted video playback |

---

## DRM Protection Features

### 1. Widevine/FairPlay DRM Encryption

All video content is encrypted using **Widevine** (Chrome, Firefox, Android) and **FairPlay** (Safari, iOS) via VdoCipher. The encryption happens at the CDN level — video segments are 2-6 second encrypted chunks that are useless without DRM license keys.

```
Raw Video → Transcoding → Segmenting → DRM Encryption → CDN
                                            │
                          Encrypted segments are useless
                          without license keys from CDM
```

The browser's **Content Decryption Module (CDM)** handles decryption in a secure sandbox. Keys never leave the CDM.

---

### 2. OTP Rotation

Instead of issuing one OTP per session, the player **rotates OTPs** during playback. When an OTP expires, a fresh one is fetched without interrupting the viewer.

| Tier | OTP Lifetime | Rotation Interval |
|------|-------------|-------------------|
| Browser | 120 seconds | Every 90 seconds |
| Mobile | 300 seconds | Every 240 seconds |

```
Player loads → OTP #1 (120s TTL)
                 ↓ 90s later
               OTP #2 (120s TTL) ← seamless swap
                 ↓ 90s later
               OTP #3 (120s TTL)
                 ↓ ...continues
```

**Why it matters:** If an attacker intercepts an OTP, it expires in under 2 minutes. Rotation makes automated ripping extremely difficult because the attacker must maintain a live authenticated session.

**Implementation:**
- Backend: `POST /api/video/otp/rotate` — validates session ownership before issuing fresh OTP
- Frontend: `VdoPlayer.tsx` runs a rotation interval timer that calls the rotate endpoint server-side. The iframe is **not reloaded** — the player continues uninterrupted while the backend logs fresh OTP generation and keeps the session alive

---

### 3. Tier-Based Resolution Capping

Browsers use **Widevine L3** (software decryption, insecure). Mobile apps use **Widevine L1** (hardware TEE, secure). Resolution is capped based on platform trust:

| Platform | DRM Level | Max Resolution | OTP TTL |
|----------|----------|---------------|---------|
| Browser | Widevine L3 | 480p | 120s |
| Mobile App | Widevine L1 / FairPlay | 1080p | 300s |
| Smart TV | Hardware DRM | 4K | 300s |

**Why it matters:** Even if a browser-based pirate extracts the video, they only get 480p — not worth distributing.

---

### 4. Dynamic Forensic Watermarking

Watermarking is **anomaly-triggered** — watermarks are OFF by default and automatically enabled when the system detects suspicious behavior during playback.

```
Normal playback → No watermark (clean viewing experience)
    ↓
Anomaly detected (IP change, low play ratio, drift, etc.)
    ↓
Flags stored on session in Redis
    ↓
Next OTP rotation (~90s) checks flags → Watermark ON
    ↓
Watermark embeds: "{user_id}|{timestamp}|{device_fingerprint}"
```

**Watermark properties (when active):**
- 10% opacity (near-invisible during normal viewing)
- White color, 12pt font
- Moves position every 3 seconds
- Survives re-encoding, cropping, and screen recording

**How it activates:** Every heartbeat (30s) runs 8 server-side anomaly signals. If any flag is raised, the `flags` field is persisted on the session in Redis. On the next OTP rotation, `session_has_anomaly()` checks this field — if flags exist, the watermark is injected into the new OTP. Once flags clear (no anomalies on subsequent heartbeats), the next rotation issues a clean OTP without watermark.

If pirated content surfaces, the watermark identifies **who** leaked it, **when**, and from **which device**.

---

### 5. Concurrent Stream Limiting

Each user is limited to **2 simultaneous streams**. Enforced server-side in Redis.

```
User tries to start stream #3:
  → HTTP 403: "Maximum concurrent streams reached (2)"

Same user + same device + same video:
  → Reuses existing session (no new slot consumed)
```

Sessions expire if no heartbeat is received within **90 seconds** (auto-cleanup for stale sessions from page refreshes or crashes).

---

### 6. Server-Side Anomaly Detection

All anomaly detection runs **server-side** during heartbeat processing — no reliance on client-reported behavioral events. The frontend sends `play_seconds` (wall-clock elapsed time since last heartbeat) and the backend cross-references this against its own measurements.

**8 server-side signals checked on every heartbeat:**

| # | Signal | Threshold | What It Detects |
|---|--------|-----------|-----------------|
| 1 | **IP change** | 3+ changes → session killed | Token/session sharing, VPN switching |
| 2 | **Heartbeat gaps** | 3+ missed heartbeats (75s+ gap) | Scripts holding sessions without real playback |
| 3 | **Low play ratio** | `play_seconds / session_age < 0.3` | Script downloads segments while barely "playing" |
| 4 | **Continuous play** | >10 hours nonstop | No human watches 10h+ — likely a bot |
| 5 | **Rapid session creation** | >5 sessions in 10 minutes | Automated ripping creating many sessions |
| 6 | **Ghost sessions** | 3+ sessions with 0 heartbeats | Session harvesting without actual playback |
| 7 | **OTP rotation abuse** | >3x expected rotations | Rapid OTP harvesting for parallel decryption |
| 8 | **Seek proxy detection** | Play-time drift >50% or erratic variance | Client-reported time doesn't match server-measured gap |

**Risk level per heartbeat:**
```
0 flags    → "normal"  — playback continues
1-2 flags  → "warning" — logged, watermark activated on next OTP rotation
3+ flags   → "blocked" — +25 risk points added, session flagged
```

**Global risk score system:**
```
0-49 points   → "normal"  — playback continues
50-99 points  → "warning" — logged, playback continues
100+ points   → "blocked" — session terminated, account flagged
Points decay after 1 hour → legitimate users recover
```

**Escalation:** Risk points are only added to the global user score when the heartbeat returns `"blocked"` (3+ simultaneous flags). Warnings are logged but don't accumulate risk — this prevents false positives during normal viewing.

**Dynamic watermarking:** When any flag is raised, the session's `flags` field is persisted in Redis. On the next OTP rotation (~90s), the system checks for active flags and injects a forensic watermark into the new OTP if anomalies are present.

**Storage:** Session signals are stored in Redis hashes per session with auto-expiry. Play-time deltas for variance detection are stored in Redis lists (`play_deltas:{session_id}`). Session creation rates tracked via sorted sets (`session_creations:{user_id}`).

---

### 7. IP Binding & Impossible Travel Detection

**Session IP Binding:**
Every heartbeat checks if the viewer's IP has changed. 3+ IP changes during a single session terminates it immediately.

```
Heartbeat 1: IP 1.2.3.4    → OK
Heartbeat 2: IP 1.2.3.4    → OK
Heartbeat 3: IP 5.6.7.8    → IP change #1 (logged)
Heartbeat 4: IP 9.10.11.12 → IP change #2 (logged)
Heartbeat 5: IP 13.14.15.16 → IP change #3 → SESSION TERMINATED
```

**Impossible Travel Detection:**
Detects when the same user makes requests from different IPs within 5 minutes. This catches token sharing or VPN switching during a rip.

> **Note:** Impossible travel detection runs on login/auth requests only — not on OTP or playback endpoints. This avoids false positives caused by proxy IP variance (Cloudflare/Vercel edge nodes can report different IPs for the same user). IP monitoring during playback is handled per-session via heartbeat instead.

---

### 8. Device Fingerprinting & Binding

A client-side fingerprint is generated from browser characteristics:

```
Hash of:
  - User-Agent string
  - Screen width × height
  - Color depth
  - Timezone offset
  - Language
  - Hardware concurrency (CPU cores)
```

This fingerprint is:
- Embedded in the session token (HMAC-signed)
- Validated on every API request via `X-Device-Fingerprint` header
- Used to detect device switching (+20 risk if fingerprint changes within 60s)
- Limited to **5 unique devices per user** (+25 risk per excess device)

---

### 9. Rate Limiting

Redis sliding window rate limiting on critical endpoints:

| Endpoint | Limit | Window | Response |
|----------|-------|--------|----------|
| Login | 5 attempts | 15 minutes | HTTP 429 + Retry-After header |
| OTP generation | 10 requests | 60 seconds | HTTP 429 |
| License requests | 20 requests | 60 seconds | HTTP 429 |

**Why it matters:** Prevents brute-force login attacks and automated OTP harvesting.

---

### 10. Session-Bound Playback Tokens

Every playback session is tied to:

- **User ID** — only the authenticated user can use the session
- **Device fingerprint** — session is locked to the device that created it
- **IP address** — logged and monitored for changes
- **Video ID** — session is for a specific video only

Tokens use **HMAC-SHA256** signing:
```
token = "{payload_json}|{hmac_sha256_signature}"
```

Server-side revocation via Redis — logging out invalidates all tokens immediately.

---

### 11. Audit Logging

Every security-relevant event is logged to PostgreSQL for forensic analysis:

| Event Type | Trigger |
|-----------|---------|
| `LOGIN_SUCCESS` | Successful authentication |
| `LOGIN_FAILED` | Wrong password or unknown email |
| `OTP_GENERATED` | New playback session started |
| `OTP_ROTATED` | OTP refreshed during playback |
| `ANOMALY_DETECTED` | Suspicious behavior flagged |
| `USER_BLOCKED` | Risk score exceeded 100 |
| `LOGOUT` | User logged out |

Each log entry includes: `user_id`, `ip_address`, `details` (JSON), `created_at` (indexed for fast queries).

---

### 12. CORS & Content Security Policy

**CORS:**
- Origins restricted to configured frontend URLs
- Credentials enabled for cookie/token auth
- Methods limited to GET, POST, DELETE

**CSP Headers (Next.js):**
```
default-src 'self'
frame-src   https://player.vdocipher.com https://*.vdocipher.com
connect-src 'self' https://*.vdocipher.com https://*.cloudfront.net
script-src  'self' 'unsafe-inline' 'unsafe-eval' https://*.vdocipher.com
style-src   'self' 'unsafe-inline' https://*.vdocipher.com
media-src   'self' https://*.vdocipher.com https://*.cloudfront.net blob:
img-src     'self' data: https:
worker-src  'self' blob:
```

CSP is widened to allow VdoCipher's player to load scripts, styles, media segments, and DRM license requests from its CDN (CloudFront). `blob:` is required for media source extensions (MSE) used by adaptive streaming.

---

### 13. Mixed Content Proxy

**Problem:** Vercel (HTTPS) cannot directly call a backend on HTTP — browsers block mixed content.

**Solution:** Next.js rewrites proxy `/api/*` requests server-side, hiding the backend URL from clients entirely.

```
Browser → https://drm-demo.vercel.app/api/auth/login
                        ↓ (Next.js rewrite, server-side)
         http://backend-server:8000/api/auth/login
```

---

## Backend Architecture

```
backend/
├── Dockerfile
├── requirements.txt
└── app/
    ├── main.py                 # FastAPI app, startup/shutdown, lifespan events
    ├── config.py               # All configuration from environment variables
    │
    ├── api/                    # Route handlers (thin layer, delegates to services)
    │   ├── auth.py             # POST /login, /logout, /refresh, GET /me
    │   ├── playback.py         # POST /otp, /otp/rotate, /heartbeat, DELETE /session
    │   ├── videos.py           # GET /videos, /videos/{id}
    │   └── health.py           # GET /health
    │
    ├── core/                   # Cross-cutting concerns
    │   ├── auth.py             # Token creation, validation, HMAC signing
    │   ├── middleware.py        # Request logging, anomaly detection per-request
    │   └── security.py         # Rate limiting, risk scoring, request analysis
    │
    ├── services/               # Business logic
    │   ├── sessions.py         # Session CRUD in Redis, heartbeat processing,
    │   │                       # behavioral analysis, concurrent stream enforcement
    │   ├── vdocipher.py        # VdoCipher OTP generation with watermark + tier config
    │   └── videos.py           # Video catalog from PostgreSQL
    │
    ├── db/                     # Data layer
    │   ├── postgres.py         # SQLAlchemy async engine, session factory, table models
    │   ├── redis.py            # Redis async connection pool
    │   └── seed.py             # Initial data: demo users + video
    │
    └── models/                 # Pydantic schemas
        └── schemas.py          # Request/response models (LoginRequest, OTPRequest,
                                # HeartbeatRequest, SessionUser, etc.)
```

### Key Design Decisions

- **Async everywhere**: All I/O operations (DB, Redis, HTTP) use `async/await` for high concurrency
- **Service layer pattern**: API routes are thin — business logic lives in `services/`
- **Redis for ephemeral data**: Sessions, rate limits, risk scores, behavioral timestamps — all with TTL-based auto-expiry
- **PostgreSQL for persistent data**: Users, videos, audit logs — survives restarts
- **HMAC tokens over JWT**: Simpler, no library dependency, server-controlled validation with Redis revocation

---

## Frontend Architecture

```
src/
├── app/
│   ├── layout.tsx              # Root layout with CSP headers
│   ├── page.tsx                # Home: video library grid + auth gate
│   ├── globals.css             # Tailwind CSS imports
│   └── watch/
│       └── [videoId]/
│           └── page.tsx        # Video player page (dynamic route)
│
├── components/
│   ├── AuthProvider.tsx        # React Context: login/logout, token refresh,
│   │                          # localStorage persistence, 401 auto-retry
│   ├── LoginForm.tsx           # Email/password form with error handling
│   ├── Header.tsx              # Nav bar with user greeting + logout
│   ├── VideoCard.tsx           # Video tile with DRM/watermark badges
│   └── VdoPlayer.tsx           # Core playback component:
│                               #   - OTP fetching on mount
│                               #   - OTP rotation (interval timer)
│                               #   - Heartbeat every 30s with behavioral events
│                               #   - Seek/restart tracking via message events
│                               #   - Risk level response handling
│                               #   - Session cleanup on unmount
│
└── lib/
    └── api.ts                  # API client class:
                                #   - Token management (localStorage)
                                #   - Device fingerprint generation
                                #   - Auto token refresh on 401
                                #   - All endpoint methods (login, OTP, heartbeat, etc.)
```

### Key Design Decisions

- **VdoCipher iframe embed**: Uses VdoCipher's secure iframe player (not a custom player) — DRM negotiation is handled inside the iframe sandbox
- **Client-side behavioral tracking**: Seek counts, restart counts, and play duration are tracked between heartbeats and sent server-side for analysis
- **React Context for auth**: Single source of truth for authentication state across all components
- **Next.js rewrites as proxy**: Avoids mixed-content issues and hides the backend URL from browser DevTools

---

## API Endpoints

### Authentication

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|:---:|
| POST | `/api/auth/login` | Login with email + password | No |
| POST | `/api/auth/refresh` | Refresh expired session token | No (refresh token) |
| POST | `/api/auth/logout` | Logout and revoke all tokens | Yes |
| GET | `/api/auth/me` | Get current user info | Yes |

### Video Catalog

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|:---:|
| GET | `/api/videos` | List all active videos | Yes |
| GET | `/api/videos/{id}` | Get single video details | Yes |
| POST | `/api/videos/sync` | Sync video catalog from VdoCipher API | Yes |

### Playback Control

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|:---:|
| POST | `/api/video/otp` | Generate OTP + create playback session | Yes |
| POST | `/api/video/otp/rotate` | Rotate OTP for active session | Yes |
| POST | `/api/playback/heartbeat` | Send heartbeat + behavioral events | Yes |
| DELETE | `/api/playback/session/{id}` | End a playback session | Yes |
| GET | `/api/playback/sessions` | List user's active sessions | Yes |
| GET | `/api/playback/debug/{id}` | Get debug info for a session | Yes |

### Health

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|:---:|
| GET | `/api/health` | Backend health check | No |

---

## Database Schema

### PostgreSQL Tables

**users**
| Column | Type | Description |
|--------|------|-------------|
| id | String (PK) | User ID (e.g., "user-001") |
| email | String (unique, indexed) | Login email |
| name | String | Display name |
| password_hash | String | bcrypt hash |
| role | String | "viewer" or "admin" |
| is_active | Boolean | Account active flag |
| created_at | DateTime | Account creation |
| updated_at | DateTime | Last update |

**videos**
| Column | Type | Description |
|--------|------|-------------|
| id | String (PK) | VdoCipher video ID |
| title | String(500) | Video title |
| description | Text | Video description |
| thumbnail | String | Thumbnail URL |
| duration | String | Display duration (e.g., "24:30") |
| is_active | Boolean | Available for playback |
| created_at | DateTime | Added date |

**audit_logs**
| Column | Type | Description |
|--------|------|-------------|
| id | Integer (PK, auto) | Log ID |
| event_type | String (indexed) | Event classification |
| user_id | String (indexed) | Who triggered it |
| ip_address | String | Source IP |
| details | Text | JSON details |
| created_at | DateTime (indexed) | When it happened |

### Redis Keys

| Key Pattern | Type | TTL | Purpose |
|------------|------|-----|---------|
| `session:{session_id}` | Hash | 90s | Active playback session data (incl. `flags` for watermark decisions) |
| `user_sessions:{user_id}` | Set | — | Set of active session IDs |
| `session_creations:{user_id}` | Sorted Set | 660s | Session creation timestamps (rapid creation detection) |
| `ghost_check:{user_id}` | Sorted Set | 180s | Sessions pending first heartbeat (ghost detection) |
| `play_deltas:{session_id}` | List | 90s | Recent play_seconds values (variance/drift detection) |
| `risk:{user_id}` | String | 3600s | Accumulated risk score |
| `ratelimit:login:{ip}` | Sorted Set | 900s | Login attempt timestamps |
| `ratelimit:otp:{user_id}` | Sorted Set | 60s | OTP request timestamps |
| `revoked:{token_hash}` | String | token TTL | Revoked token marker |

---

## Data Flow

### Login Flow
```
User                Frontend               Backend              PostgreSQL    Redis
 │                     │                      │                      │          │
 │── email/password ──→│                      │                      │          │
 │                     │── POST /auth/login ─→│                      │          │
 │                     │                      │── verify password ──→│          │
 │                     │                      │←── user record ──────│          │
 │                     │                      │── rate limit check ────────────→│
 │                     │                      │── audit log ────────→│          │
 │                     │←── token + user ─────│                      │          │
 │←── redirect home ──│                      │                      │          │
```

### Playback Flow
```
User                VdoPlayer              Backend              VdoCipher    Redis
 │                     │                      │                     │          │
 │── click play ──────→│                      │                     │          │
 │                     │── POST /video/otp ──→│                     │          │
 │                     │                      │── create session ──────────────→│
 │                     │                      │── rate limit check ────────────→│
 │                     │                      │── generate OTP ────→│          │
 │                     │                      │←── otp + playback ──│          │
 │                     │←── otp + session_id ─│                     │          │
 │                     │                      │                     │          │
 │                     │══ load iframe ══════════════════════════════│          │
 │                     │                      │                     │          │
 │   ┌────────────── PLAYBACK LOOP (every 30s) ─────────────────┐  │          │
 │   │                 │                      │                  │  │          │
 │   │                 │── POST /heartbeat ──→│                  │  │          │
 │   │                 │   {seeks, restarts}  │── analyze ──────────────────→│
 │   │                 │                      │── update risk ─────────────→│
 │   │                 │←── risk_level ───────│                  │  │          │
 │   │                 │                      │                  │  │          │
 │   └─────────────────┼──────────────────────┼──────────────────┘  │          │
 │                     │                      │                     │          │
 │   ┌────────────── OTP ROTATION (every 90s) ──────────────────┐  │          │
 │   │                 │                      │                  │  │          │
 │   │                 │── POST /otp/rotate ─→│                  │  │          │
 │   │                 │                      │── fresh OTP ────→│  │          │
 │   │                 │←── ack ──────────────│                  │  │          │
 │   │                 │   (iframe NOT reloaded — playback continues)│          │
 │   │                 │                      │                  │  │          │
 │   └─────────────────┼──────────────────────┼──────────────────┘  │          │
 │                     │                      │                     │          │
 │── leave page ──────→│                      │                     │          │
 │                     │── DELETE /session ───→│                     │          │
 │                     │                      │── remove ──────────────────────→│
```

---

## Configuration Reference

### Backend Environment Variables (`backend/.env`)

```bash
# VdoCipher
VDOCIPHER_API_SECRET=your_api_secret
ALLOWED_DOMAIN=https://your-frontend.com

# Database
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/dbname
REDIS_URL=redis://:password@host:6379

# Auth
SESSION_SECRET=your_secret_key
SESSION_TOKEN_TTL=3600          # 1 hour
REFRESH_TOKEN_TTL=604800        # 7 days

# Anti-Piracy
MAX_CONCURRENT_STREAMS=2
OTP_TTL_BROWSER=120             # 2 minutes
OTP_TTL_MOBILE=300              # 5 minutes
OTP_ROTATION_INTERVAL_BROWSER=90
OTP_ROTATION_INTERVAL_MOBILE=240

# Rate Limiting
LOGIN_RATE_LIMIT=5
LOGIN_RATE_WINDOW=900           # 15 minutes
OTP_RATE_LIMIT=10
OTP_RATE_WINDOW=60

# Behavioral Detection (tuned to avoid false positives)
MAX_SEEKS_PER_MINUTE=30
MAX_RESTARTS_PER_HOUR=15
MAX_CONTINUOUS_PLAY_HOURS=10
RISK_SCORE_THRESHOLD=100

# CORS
FRONTEND_URL=http://localhost:3000,https://your-app.vercel.app
```

### Frontend Environment Variables (`.env.local`)

```bash
NEXT_PUBLIC_API_URL=http://localhost:8000
```

---

## Getting Started

### Prerequisites

- Docker & Docker Compose
- Node.js 18+
- PostgreSQL (local or remote)
- Redis (local or remote)
- VdoCipher account + API secret

### Quick Start

```bash
# Clone the repo
git clone https://github.com/Techpix-in/drm-demo.git
cd drm-demo

# Configure environment
cp backend/.env.example backend/.env    # Edit with your credentials
cp .env.local.example .env.local        # Edit with backend URL

# Run everything with one command
chmod +x start.sh
./start.sh
```

The `start.sh` script:
1. Starts the Docker backend container (FastAPI)
2. Waits for health check to pass
3. Seeds the database with demo users + video
4. Starts the Next.js frontend on port 3000
5. Cleans up all processes on Ctrl+C / exit

### Manual Start

```bash
# Terminal 1: Backend
docker compose up --build -d

# Terminal 2: Frontend
npm install
npm run dev
```

- Frontend: http://localhost:3000
- Backend: http://localhost:8000
- API docs: http://localhost:8000/docs

---

## Deployment

### Frontend — Vercel

1. Push to GitHub
2. Import project in Vercel
3. Set environment variable: `NEXT_PUBLIC_API_URL=http://your-backend:8000`
4. Deploy

### Backend — Docker on any server

```bash
docker compose up -d
```

Or use **Cloudflare Tunnel** for HTTPS without a domain:
```bash
cloudflared tunnel --url http://localhost:8000
```

### Mixed Content Note

If your frontend is on HTTPS (Vercel) and backend is on HTTP, the Next.js rewrite proxy handles this server-side — no mixed content errors.

---

## Demo Credentials

| Email | Password | Role |
|-------|----------|------|
| viewer@example.com | demo123 | Viewer |
| admin@example.com | admin123 | Admin |

---

## Security Summary

| Layer | Protection | Implementation |
|-------|-----------|----------------|
| **Encryption** | Widevine L3 / FairPlay | VdoCipher CDN |
| **Token Security** | Short-lived, rotating OTPs | 120s TTL, 90s rotation |
| **Resolution** | Tier-based capping | Browser=480p, Mobile=1080p |
| **Watermarking** | Anomaly-triggered forensic ID | Activates on anomaly, embeds user+device+timestamp |
| **Streams** | Concurrent limit | Max 2 per user |
| **Behavior** | 8 server-side signals | IP, gaps, ratio, drift, ghosts, rotation abuse |
| **Network** | IP binding | 3+ changes = session killed |
| **Device** | Fingerprint binding | Token-bound, max 5 devices |
| **Rate Limits** | Sliding window | Login, OTP, license endpoints |
| **Audit** | Full event log | PostgreSQL with indexed queries |
| **Transport** | CSP + CORS + Proxy | Mixed content mitigation |

> **Philosophy:** We don't aim to stop piracy completely. We aim to make automated downloading impossible, reduce leak quality, and ensure every leak is traceable back to the source account.

---

## License

Private — Techpix Solutions

---

Built with VdoCipher DRM + FastAPI + Next.js
