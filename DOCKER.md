# Switch Music 🎵

Self-hosted **playlist migration, dedupe & scheduled sync** between
**Spotify ⇄ YouTube Music ⇄ NetEase Cloud Music (网易云) ⇄ QQ Music ⇄ Kugou (酷狗) ⇄ Apple Music**, plus CSV / text import & export.
All credentials, cache and history stay in your own `/data` volume.

Source & full docs: https://github.com/AtomBoyC/switch-music

## Quick start

```bash
docker run -d --name switch-music \
  -p 127.0.0.1:8765:8765 \
  -v "$PWD/switch-music-data:/data" \
  --restart unless-stopped \
  atomboyc/switch-music:latest
```

Open **http://127.0.0.1:8765**.

Or with Docker Compose: download [`docker-compose.yml`](https://github.com/AtomBoyC/switch-music/blob/main/docker-compose.yml) and run `docker compose up -d`.

Images: `linux/amd64`, `linux/arm64` (Apple Silicon, Raspberry Pi, most NAS).
Also available from GitHub Container Registry: `ghcr.io/atomboyc/switch-music` (same tags).
Versioned tags (e.g. `:2.2.0`, `:2.2`) and release notes: https://github.com/AtomBoyC/switch-music/releases

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `SWITCH_MUSIC_PASSWORD` | *(empty)* | Access password (HTTP Basic auth, any username). **Set it whenever the port is reachable from other machines** — the app stores your music-account cookies/tokens. |
| `SWITCH_MUSIC_ALLOWED_HOSTS` | *(empty)* | Extra hostnames/IPs allowed in the `Host` header, e.g. `192.168.1.10,music.example.com`. `*` allows any (use only with a password). |
| `SPOTIFY_REDIRECT_URI` | `http://127.0.0.1:8765/api/spotify/callback` | Spotify only accepts plain-http redirects on `127.0.0.1`; on a remote server use an **https** URL behind a reverse proxy and register the same URL in the Spotify dashboard. |
| `PORT` | `8765` | Listening port inside the container. |
| `PUID` / `PGID` | `10001` | User/group the app runs as (the entrypoint fixes `/data` ownership). |
| `TZ` | `Asia/Shanghai` | Time zone for the sync scheduler and history. |

## LAN / NAS example

```bash
docker run -d --name switch-music \
  -p 8765:8765 \
  -v /volume1/docker/switch-music:/data \
  -e SWITCH_MUSIC_PASSWORD='a-strong-password' \
  -e SWITCH_MUSIC_ALLOWED_HOSTS='192.168.1.10' \
  --restart unless-stopped \
  atomboyc/switch-music:latest
```

> Tip: Spotify authorization must be completed from a `127.0.0.1` URL or an https domain. On a NAS without https,
> you can open an SSH tunnel (`ssh -L 8765:127.0.0.1:8765 nas`) and authorize via `http://127.0.0.1:8765` once —
> the token is then stored in `/data` and refreshed automatically.
