# Switch Music 🎵

[![Release](https://img.shields.io/github/v/release/AtomBoyC/switch-music?logo=github&label=Release)](https://github.com/AtomBoyC/switch-music/releases)
[![Docker CI](https://github.com/AtomBoyC/switch-music/actions/workflows/docker.yml/badge.svg)](https://github.com/AtomBoyC/switch-music/actions/workflows/docker.yml)
[![Docker Hub](https://img.shields.io/docker/pulls/atomboyc/switch-music?logo=docker&label=Docker%20Hub)](https://hub.docker.com/r/atomboyc/switch-music)
[![Arch](https://img.shields.io/badge/arch-amd64%20%7C%20arm64-0db7ed?logo=linux&logoColor=white)](https://hub.docker.com/r/atomboyc/switch-music)
[![Python](https://img.shields.io/badge/python-3.9%2B-3776ab?logo=python&logoColor=white)](./requirements.txt)

[简体中文](./README.md) | **English** | [Docker Hub Quick Guide](./DOCKER.md)

Self-hosted, unlimited **multi-platform playlist migration, pre-match review, smart deduplication, and scheduled incremental sync** workbench:

> **Spotify ⇄ YouTube Music ⇄ NetEase Cloud Music (网易云音乐) ⇄ QQ Music (QQ音乐) ⇄ Kugou Music (酷狗音乐) ⇄ Apple Music** — plus **CSV / TSV / JSON / Plain-Text** import & export.

All account credentials, OAuth tokens, match caches, and history stay **100% locally inside your own `data/` directory (or `/data` Docker volume)** — zero track limits, zero cloud middlemen, zero credential uploads.

---

## 📊 6-Platform Capability Matrix

| Platform | Public URL Import (No Login) | Account Auth Method | Read Playlists & Liked | Target Search & Matching | Create / Append / Like | Playlist Deduplication |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **YouTube Music** | ✅ `music.youtube.com/playlist?list=PL...` | Browser `Copy as cURL` / Cookie | ✅ Playlists + `Liked Music` | ✅ Progressive fallback | ✅ / ✅ / ✅ | ✅ Scan + Remove |
| **Spotify** | ⚠️ Login required (see Feb 2026 rules) | Official OAuth 2.0 | ✅ Owned/Collab + `Liked Songs` | ✅ Includes **ISRC** lookup | ✅ / ✅ / ✅ | ✅ Scan + Index-preserving remove |
| **NetEase (网易云)** | ✅ Playlist URL / `163cn.tv` (no 1k cap) | Browser `Copy as cURL` / Cookie | ✅ Playlists + `Liked` | ✅ Pure-Python `weapi` | ✅ / ✅ / ✅ | ✅ Scan + Remove |
| **QQ Music (QQ音乐)** | ✅ Playlist URL / `c6.y.qq.com` (paginated) | Browser `Copy as cURL` / Cookie | ✅ Playlists + `Liked` | ✅ `musicu.fcg` gateway | ✅ / ✅ / ✅ | ✅ Scan + Remove |
| **Kugou (酷狗音乐)** | ✅ `gcid_...` URL / short link / `collection_...` | **Kugou App QR Scan** (or client token) | ✅ Playlists + `Liked` | ✅ Client gateway search | ✅ / ✅ / ✅ | ✅ Scan + Remove |
| **Apple Music** | ✅ Public playlist / album / `apple.co` (with ISRC) | Web `Copy as cURL` (**no $99 dev account**) | ✅ Library playlists + songs | ✅ Includes **ISRC** lookup | ✅ / ✅ / ✅ (Add + Love) | 🔍 Scan only¹ |
| **CSV / JSON / Text** | ✅ Multi-file merge (Exportify / TuneMyMusic / Soundiiz) | Local offline parser (UTF-8 / GB18030) | — | — | ✅ Export UTF-8 BOM `.csv` | ✅ Source list dedupe |

> ¹ **Note**: Apple Music's web API (`amp-api`) does not expose an endpoint to delete individual tracks from library playlists; duplicates are detected and grouped so you can remove them in the Music app. Except for Spotify's official Web API, other adapters rely on web/client endpoints that may require updates if upstream platforms change.

---

## ✨ Key Features

1. **Any-to-Any Migration & Full-Length Public URL Import**
   - Paste public playlist URLs without logging into the source platform: bypasses NetEase's 10/1,000-track web truncation via full `trackIds` batching, paginates large QQ Music playlists, decodes Kugou Base-35 `gcid_` share codes locally, and scrapes/caches Apple Music's public web token automatically while preserving **ISRC** codes.
   - Drag-and-drop multiple `.csv`, `.tsv`, or `.json` files (compatible with Exportify, TuneMyMusic, Soundiiz) or paste `Artist - Title` plain-text lists.
2. **Multi-Dimensional Scoring & Pre-Match Review Workbench**
   - Scores candidates (0–100) using **ISRC**, Simplified/Traditional Chinese normalization, multi-artist overlap, album similarity, and duration proximity (`±3s`), while **penalizing unintended Karaoke / Instrumental / Cover / DJ / Sped-up / Live versions**.
   - Run **Pre-Match Review** before writing a single song: filter by High Confidence (`≥65`), Low Confidence, or Unmatched, preview tracks, and manually search/override matches in place.
3. **Order-Preserving Concurrency, Crash Recovery & Safe Dedupe**
   - Sliding-window `ThreadPoolExecutor` (1–6 workers) accelerates matching 3–5× while **preserving 100% of original playlist order**, paired with sequential retrying writes.
   - Local 30-day `match_cache.json` (up to 15,000 entries) gives `0ms` hits across playlists and retries.
   - Pre-reads existing target tracks (without 2,000-song caps) before appending; **fails safely without writing** if reading target state errors out (e.g., expired session), preventing duplicate floods.
   - Automatic exponential backoff on HTTP `429/502/503/504` and throttling codes, plus automatic disk checkpoints every 100 tracks for one-click resume after restarts.
4. **Duplicate Group Cleaner, CSV Backup & Scheduled Sync**
   - Scan playlists in **Standard** (ID + normalized title/artist), **Strict** (ID only), or **Deep** (title + `±3s` duration) mode, listen inline, and pick exactly which copy to keep.
   - Export any playlist or unmatched list to Excel-friendly UTF-8 BOM `.csv`, or configure background **scheduled incremental sync** rules.
5. **Local-First Security**
   - Enforces `0700` / `0600` permissions on `data/`, DNS-rebinding `Host` allowlist, state-changing `Origin` CSRF checks, and optional constant-time HTTP Basic auth (`SWITCH_MUSIC_PASSWORD`) for NAS/LAN deployments.

---

## 🚀 Quick Start

### Option 1: Docker / NAS (Recommended)

Multi-arch images (`linux/amd64` & `linux/arm64` — Intel/AMD, Apple Silicon, Raspberry Pi, Synology, QNAP, Unraid) are published simultaneously to:

- **Docker Hub**: `atomboyc/switch-music:latest` (or versioned tags like `atomboyc/switch-music:2.2.0`)
- **GitHub Container Registry**: `ghcr.io/atomboyc/switch-music:latest`

#### Localhost-only deployment

```bash
docker run -d --name switch-music \
  -p 127.0.0.1:8765:8765 \
  -v "$PWD/data:/data" \
  --restart unless-stopped \
  atomboyc/switch-music:latest
```

Open **http://127.0.0.1:8765** (or download [`docker-compose.yml`](./docker-compose.yml) and run `docker compose up -d`).

#### LAN / NAS deployment

> [!CAUTION]
> Because `/data` stores your music-account cookies and OAuth tokens, **always set `SWITCH_MUSIC_PASSWORD` and `SWITCH_MUSIC_ALLOWED_HOSTS` whenever exposing the port beyond `127.0.0.1`**.

```bash
docker run -d --name switch-music \
  -p 8765:8765 \
  -v /volume1/docker/switch-music:/data \
  -e PUID=1000 \
  -e PGID=1000 \
  -e TZ=Asia/Shanghai \
  -e SWITCH_MUSIC_PASSWORD='your-strong-password' \
  -e SWITCH_MUSIC_ALLOWED_HOSTS='192.168.1.10,nas.local' \
  --restart unless-stopped \
  atomboyc/switch-music:latest
```

#### Environment Variables

| Variable | Default | Description |
| :--- | :--- | :--- |
| `SWITCH_MUSIC_PASSWORD` | *(empty)* | HTTP Basic auth password (enter **any username** + this password; `/api/health` stays unauthenticated for container healthchecks). |
| `SWITCH_MUSIC_ALLOWED_HOSTS` | *(empty)* | Comma-separated LAN IPs/domains allowed in the `Host` header (e.g. `192.168.1.10,music.example.com`), or `*` (use only with a password). |
| `SPOTIFY_REDIRECT_URI` | `http://127.0.0.1:8765/api/spotify/callback` | Spotify OAuth redirect URI. Spotify only permits plain `http://` on `127.0.0.1`; on remote servers use an `https://` reverse-proxy URL matching your Spotify Dashboard. |
| `PORT` | `8765` | Listening port inside the container / process. |
| `HOST` | `127.0.0.1` (local) / `0.0.0.0` (Docker) | Bind address. |
| `SWITCH_MUSIC_DATA_DIR` | `./data` (local) / `/data` (Docker) | Persistent storage directory. |
| `PUID` / `PGID` | `10001` / `10001` | Non-root UID/GID inside Docker (entrypoint fixes `/data` ownership and drops root via `setpriv`). |
| `TZ` | `Asia/Shanghai` | Time zone for sync schedules and migration history. |

> [!TIP]
> **Authorizing Spotify on a headless NAS without HTTPS**: Forward the port once over SSH (`ssh -L 8765:127.0.0.1:8765 user@nas-ip`), open `http://127.0.0.1:8765` locally, and complete Spotify OAuth once. The refresh token is saved in `/data` and renews automatically thereafter.

---

### Option 2: macOS One-Click (`start.command`) & Manual Python Setup

Double-click [`start.command`](./start.command) on macOS (zero Node.js build step), or run manually on macOS / Linux / Windows (Python 3.9+):

```bash
git clone https://github.com/AtomBoyC/switch-music.git
cd switch-music

python3 -m venv .venv
source .venv/bin/activate        # Windows PowerShell: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

python app.py                    # Opens on http://127.0.0.1:8765
```

---

## 🔑 Connecting Music Accounts

1. **Spotify (OAuth 2.0)**:
   - Create an app in the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard) (requires an active **Spotify Premium** subscription on the developer account).
   - Set **Redirect URIs** to `http://127.0.0.1:8765/api/spotify/callback` (**must** be `127.0.0.1`, never `localhost`), and check **Web API**.
   - Under **Settings → User Management**, add your Spotify account name and email to the allowlist.
   - Paste **Client ID** & **Client Secret** into Switch Music and authorize. *(Note: Under Spotify's February 2026 Development Mode rules, apps can only read items of playlists you own or collaborate on — duplicate third-party playlists to your own account in Spotify first, or export via [Exportify](https://exportify.net/).)*
2. **Apple Music (No Paid Developer Account Needed)**:
   - Sign in at [https://music.apple.com](https://music.apple.com) (active Apple Music subscription required for personal library access).
   - Open DevTools (`F12` / `Cmd+Option+I`) → **Network** → filter by `amp-api.music.apple.com` and click **Library → Playlists**.
   - Right-click any `amp-api.music.apple.com` request (carrying `media-user-token`) → **Copy → Copy as cURL**, and paste into Switch Music.
3. **Kugou Music (QR Code Login)**:
   - Click the **Kugou** card → generate QR code → scan and confirm with the **Kugou Music mobile app**.
4. **YouTube Music / NetEase / QQ Music (`Copy as cURL`)**:
   - Sign in at `music.youtube.com` (filter `browse`, needs `SAPISID`), `music.163.com` (filter `weapi`, needs `MUSIC_U`), or `y.qq.com` (filter `musicu.fcg`, needs `uin` + `qm_keyst`/`qqmusic_key`).
   - Right-click an authenticated API request → **Copy → Copy as cURL** (do **not** use plain `Copy as fetch`, which strips cookies) and paste into Switch Music. Also accepts `Copy as fetch (Node.js)`, raw headers, Cookie-Editor JSON, and Netscape `cookies.txt`.

---

## 🛠️ Development & Testing

```bash
# Run unit & integration tests
./.venv/bin/python -m unittest discover -s tests -t . -v

# Healthcheck endpoint
curl http://127.0.0.1:8765/api/health
```

---

## ⚠️ Disclaimer

Switch Music is a personal, self-hosted playlist metadata utility. It **does not** download, decrypt, or redistribute audio streams. All account credentials remain strictly on your own machine. Please use reasonable concurrency and respect each music service's Terms of Use.
