# Switch Music 🎵

Self-hosted, unlimited **playlist migration, pre-match review, smart deduplication & scheduled sync** workbench across streaming services and self-hosted NAS music servers:

> **Spotify ⇄ YouTube Music ⇄ NetEase Cloud Music (网易云音乐) ⇄ QQ Music (QQ音乐) ⇄ Kugou Music (酷狗音乐) ⇄ Apple Music ⇄ Navidrome / Subsonic**
>
> Plus **Qishui / Soda Music (汽水音乐)** no-login share URL import, and **CSV / TSV / M3U8 (`#EXTM3U`) / JSON / Text** import & export.

All account cookies, OAuth tokens, Subsonic credentials, match caches, and history stay **100% inside your own `/data` volume** — no track limits, no cloud middlemen. Built-in **简体中文 ⇄ English** bilingual Web UI.

- **GitHub Repository & 中文完整文档**: https://github.com/AtomBoyC/switch-music
- **English Documentation**: https://github.com/AtomBoyC/switch-music/blob/main/README_EN.md
- **Releases & Changelog**: https://github.com/AtomBoyC/switch-music/releases
- **License**: MIT (`https://github.com/AtomBoyC/switch-music/blob/main/LICENSE`)

---

## Highlights in v2.3

- **8 Import Sources & 7 Full Read/Write Targets**: Added **Navidrome / OpenSubsonic** (`v1.16.1` token+salt auth, playlists, `Starred` tracks, ISRC-aware matching & index-safe deduplication) and **Qishui / 汽水音乐** public share URL import.
- **Multi-Format Backup & Portability**: Import & export playlists as **UTF-8 BOM `.csv`**, **standard `#EXTM3U` `.m3u8`** (compatible with Navidrome / Jellyfin / Plex / Foobar2000), or **Portable `.json`**.
- **3 Scheduled Sync Modes + Circuit Breaker**:
  - `append` — One-way incremental additions
  - `mirror` — One-way mirror with **Empty-Snapshot Guard** + configurable **Max Removal Ratio** circuit breaker (default `30%`) to prevent accidental mass deletions
  - `two_way` — Bidirectional echo-free merge across two platforms
- **Push Notification Guardian**: Native **Webhook** (Feishu / Lark / DingTalk / WeCom / Discord / Slack / Custom JSON), **Bark (iOS)**, and **Telegram Bot** alerts for headless NAS sync runs.
- **Visual Match Cache Inspector & Bilingual UI**: Search, inspect, and delete individual cached song mappings (including manual overrides persisted from Pre-Match Review), with one-click **中文 / EN** switching.

---

## Supported Architectures & Tags

- **Platforms**: `linux/amd64`, `linux/arm64` (Intel/AMD, Apple Silicon, Raspberry Pi, Synology, QNAP, fnOS, Unraid)
- **Tags**:
  - `latest` — latest stable build from `main`
  - `2.3.0`, `2.3` — pinned semantic version tags
- **Mirror Registry** (identical tags & multi-arch manifests): `ghcr.io/atomboyc/switch-music:latest`

---

## Quick Start

### 1. Localhost-only (`docker run`)

```bash
docker run -d --name switch-music \
  -p 127.0.0.1:8765:8765 \
  -v "$PWD/switch-music-data:/data" \
  --restart unless-stopped \
  atomboyc/switch-music:latest
```

Open **http://127.0.0.1:8765** in your browser.

### 2. Docker Compose (`docker-compose.yml`)

```yaml
services:
  switch-music:
    image: atomboyc/switch-music:latest
    # Mirror: ghcr.io/atomboyc/switch-music:latest
    container_name: switch-music
    restart: unless-stopped
    ports:
      - "127.0.0.1:8765:8765"
    volumes:
      - ./data:/data
    environment:
      TZ: Asia/Shanghai
      # PUID: "1000"
      # PGID: "1000"
      # SWITCH_MUSIC_PASSWORD: change-me
      # SWITCH_MUSIC_ALLOWED_HOSTS: 192.168.1.10,music.example.com
      # SPOTIFY_REDIRECT_URI: https://music.example.com/api/spotify/callback
      # SUBSONIC_URL: http://navidrome:4533
      # SUBSONIC_USER: admin
      # SUBSONIC_PASSWORD: your-subsonic-password
      # SWITCH_MUSIC_WEBHOOK_URL: https://open.feishu.cn/open-apis/bot/v2/hook/xxx
```

Run `docker compose up -d`.

---

## LAN / NAS & Reverse Proxy Deployment

> **Security Warning:** Because `/data` stores your music-account cookies and OAuth tokens, **always set `SWITCH_MUSIC_PASSWORD` and `SWITCH_MUSIC_ALLOWED_HOSTS` whenever publishing port `8765` beyond `127.0.0.1`.** Without `SWITCH_MUSIC_ALLOWED_HOSTS`, non-loopback `Host` headers are rejected with `403 Forbidden host` (DNS-rebinding protection).

```bash
docker run -d --name switch-music \
  -p 8765:8765 \
  -v /volume1/docker/switch-music:/data \
  -e PUID=1000 \
  -e PGID=1000 \
  -e TZ=Asia/Shanghai \
  -e SWITCH_MUSIC_PASSWORD='replace-with-a-strong-password' \
  -e SWITCH_MUSIC_ALLOWED_HOSTS='192.168.1.10,nas.local' \
  --restart unless-stopped \
  atomboyc/switch-music:latest
```

> **Tip — Spotify OAuth on a NAS without HTTPS:** Spotify only permits plain-HTTP redirect URIs on `127.0.0.1` (or `https://` behind a reverse proxy). On a LAN-only NAS, forward the port once via SSH (`ssh -L 8765:127.0.0.1:8765 user@nas`) and authorize at `http://127.0.0.1:8765` — the refresh token is saved in `/data` and renews automatically thereafter.

---

## Environment Variables

| Variable | Default | Description |
| :--- | :--- | :--- |
| `SWITCH_MUSIC_PASSWORD` | *(empty)* | Access password via HTTP Basic auth (enter **any username** + this password; `/api/health` remains exempt for Docker healthchecks). |
| `SWITCH_MUSIC_ALLOWED_HOSTS` | *(empty)* | Comma-separated LAN IPs or domain names allowed in the `Host` header (e.g. `192.168.1.10,music.example.com`). `*` allows any host (use only with a password). |
| `SPOTIFY_REDIRECT_URI` | `http://127.0.0.1:8765/api/spotify/callback` | Custom `https://` callback URL when running behind a reverse proxy (must match your Spotify Developer Dashboard). |
| `SUBSONIC_URL` / `SUBSONIC_USER` / `SUBSONIC_PASSWORD` | *(empty)* | Optional default Navidrome / Subsonic server credentials (can also be configured directly in the Web UI). |
| `SWITCH_MUSIC_WEBHOOK_URL` | *(empty)* | Optional Webhook URL for sync notifications (auto-formats Feishu, DingTalk, WeCom, Discord, Slack, or generic JSON). |
| `SWITCH_MUSIC_BARK_URL` | *(empty)* | Optional iOS Bark push URL or device key (`https://api.day.app/<key>`). |
| `SWITCH_MUSIC_TG_BOT_TOKEN` / `SWITCH_MUSIC_TG_CHAT_ID` | *(empty)* | Optional Telegram Bot token and target Chat ID for sync notifications. |
| `PORT` | `8765` | HTTP port inside the container. |
| `HOST` | `0.0.0.0` | Bind address inside the container. |
| `SWITCH_MUSIC_DATA_DIR` | `/data` | Directory inside the container for credentials, match cache, history, sync tasks, and push config. |
| `PUID` / `PGID` | `10001` / `10001` | Non-root UID/GID the server runs as (the entrypoint fixes `/data` ownership and drops root privileges via `setpriv`). |
| `TZ` | `Asia/Shanghai` | Container time zone for scheduled sync and history timestamps. |

---

## Data Volume & Healthcheck

- **Volume `/data`**: Persists `*_auth.json`, `.spotify_cache`, `subsonic_auth.json`, `notification_config.json`, `match_cache.json`, `migration_history.json`, `jobs/`, and `sync_tasks.json` with `0700` / `0600` permissions. Safe across `docker pull` upgrades.
- **Healthcheck**: Built-in `HEALTHCHECK` queries `GET http://127.0.0.1:8765/api/health` (`{"status":"ok","version":"2.3.0"}`).
