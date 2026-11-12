from __future__ import annotations

import http.cookies
import json
import os
import re
import shlex
import threading
from pathlib import Path
from typing import Any, Dict, List, Tuple

BASE_DIR = Path(__file__).resolve().parent.parent
# Data directory (credentials, cache, history). Override in Docker to point at a mounted volume.
DATA_DIR = Path(os.environ.get("SWITCH_MUSIC_DATA_DIR") or (BASE_DIR / "data")).expanduser().resolve()
JOBS_DIR = DATA_DIR / "jobs"
STATIC_DIR = BASE_DIR / "static"

DATA_DIR.mkdir(parents=True, exist_ok=True)
JOBS_DIR.mkdir(exist_ok=True)
STATIC_DIR.mkdir(exist_ok=True)

YTM_AUTH_FILE = DATA_DIR / "ytm_browser.json"
SPOTIFY_CONFIG_FILE = DATA_DIR / "spotify_config.json"
SPOTIFY_CACHE_FILE = DATA_DIR / ".spotify_cache"
NETEASE_AUTH_FILE = DATA_DIR / "netease_auth.json"
QQMUSIC_AUTH_FILE = DATA_DIR / "qqmusic_auth.json"
KUGOU_AUTH_FILE = DATA_DIR / "kugou_auth.json"
KUGOU_DEVICE_FILE = DATA_DIR / "kugou_device.json"
APPLEMUSIC_AUTH_FILE = DATA_DIR / "applemusic_auth.json"
APPLEMUSIC_TOKEN_CACHE_FILE = DATA_DIR / "applemusic_dev_token.json"

MATCH_CACHE_FILE = DATA_DIR / "match_cache.json"
HISTORY_FILE = DATA_DIR / "migration_history.json"
SYNC_TASKS_FILE = DATA_DIR / "sync_tasks.json"

DEFAULT_PORT = int(os.environ.get("PORT") or 8765)
# Bind address: 127.0.0.1 locally; the Docker image sets HOST=0.0.0.0.
DEFAULT_HOST = os.environ.get("HOST") or "127.0.0.1"
# Spotify only accepts plain-http redirect URIs on loopback; remote deployments need an https URL.
SPOTIFY_REDIRECT_URI_ENV = (os.environ.get("SPOTIFY_REDIRECT_URI") or "").strip()
DEFAULT_SPOTIFY_REDIRECT_URI = SPOTIFY_REDIRECT_URI_ENV or f"http://127.0.0.1:{DEFAULT_PORT}/api/spotify/callback"
# Optional access password (HTTP Basic auth, any username). Strongly recommended when the
# service is reachable from other machines, because it stores your music-account credentials.
ACCESS_PASSWORD = os.environ.get("SWITCH_MUSIC_PASSWORD") or ""

_file_lock = threading.RLock()

PLATFORM_META: Dict[str, Dict[str, Any]] = {
    "ytm": {
        "id": "ytm",
        "name": "YouTube Music",
        "short_name": "YTM",
        "supports_url_import": True,
        "supports_oauth": False,
        "supports_cookie_auth": True,
        "supports_write": True,
        "supports_liked": True,
        "supports_dedupe": True,
    },
    "spotify": {
        "id": "spotify",
        "name": "Spotify",
        "short_name": "Spotify",
        "supports_url_import": False,
        "supports_oauth": True,
        "supports_cookie_auth": False,
        "supports_write": True,
        "supports_liked": True,
        "supports_dedupe": True,
    },
    "netease": {
        "id": "netease",
        "name": "网易云音乐",
        "short_name": "网易云",
        "supports_url_import": True,
        "supports_oauth": False,
        "supports_cookie_auth": True,
        "supports_write": True,
        "supports_liked": True,
        "supports_dedupe": True,
    },
    "qqmusic": {
        "id": "qqmusic",
        "name": "QQ音乐",
        "short_name": "QQ音乐",
        "supports_url_import": True,
        "supports_oauth": False,
        "supports_cookie_auth": True,
        "supports_write": True,
        "supports_liked": True,
        "supports_dedupe": True,
    },
    "kugou": {
        "id": "kugou",
        "name": "酷狗音乐",
        "short_name": "酷狗",
        "supports_url_import": True,
        "supports_oauth": False,
        "supports_cookie_auth": True,
        "supports_qr_login": True,
        "supports_write": True,
        "supports_liked": True,
        "supports_dedupe": True,
    },
    "applemusic": {
        "id": "applemusic",
        "name": "Apple Music",
        "short_name": "Apple",
        "supports_url_import": True,
        "supports_oauth": False,
        "supports_cookie_auth": True,
        "supports_write": True,
        "supports_liked": True,
        # Apple's API has no endpoint for removing a track from a library playlist:
        # duplicates can be scanned but have to be removed in the Music app.
        "supports_dedupe": False,
    },
}


def read_json_file(path: Path, default: Any) -> Any:
    with _file_lock:
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default


def write_json_file(path: Path, data: Any) -> None:
    """
    Atomically write JSON. Files inside data/ hold account cookies / OAuth tokens,
    so they are always created with owner-only (0600) permissions.
    """
    with _file_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        fd = os.open(str(tmp_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, payload)
        finally:
            os.close(fd)
        try:
            os.chmod(tmp_path, 0o600)
        except OSError:
            pass
        os.replace(tmp_path, path)


def harden_data_dir_permissions() -> None:
    """Restrict data/ (credentials, tokens, history) to the current user only."""
    try:
        os.chmod(DATA_DIR, 0o700)
        for p in DATA_DIR.rglob("*"):
            try:
                os.chmod(p, 0o700 if p.is_dir() else 0o600)
            except OSError:
                pass
    except OSError:
        pass


# Hosts allowed to reach the local web server (DNS-rebinding protection).
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1"}
# Extra hosts for LAN / server deployments, e.g. SWITCH_MUSIC_ALLOWED_HOSTS="192.168.1.10,music.example.com".
# "*" disables the Host check (only do this behind SWITCH_MUSIC_PASSWORD or a trusted proxy).
_EXTRA_HOSTS = {h.strip().lower() for h in (os.environ.get("SWITCH_MUSIC_ALLOWED_HOSTS") or "").split(",") if h.strip()}
ALLOW_ANY_HOST = "*" in _EXTRA_HOSTS
ALLOWED_HOSTS |= _EXTRA_HOSTS - {"*"}


def is_allowed_host(host_header: str) -> bool:
    host = (host_header or "").strip().lower()
    if not host:
        return False
    if ALLOW_ANY_HOST:
        return True
    if host.startswith("["):
        name = host.split("]")[0] + "]"
    else:
        name = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
    return name in ALLOWED_HOSTS


def is_allowed_origin(origin: str, request_host: str = "") -> bool:
    """Origin header check for state-changing requests (CSRF protection)."""
    if not origin:
        # Non-browser clients (curl, scripts) and same-origin navigations send no Origin.
        return True
    if origin.strip().lower() == "null":
        return False
    m = re.match(r"^https?://([^/]+)$", origin.strip().lower())
    if not m:
        return False
    origin_host = m.group(1)
    # Same-origin request (works for any deployment host, incl. behind a reverse proxy).
    if request_host and origin_host == request_host.strip().lower():
        return True
    # Explicit allow-list only — the "*" Host wildcard must never open up cross-site writes.
    name = origin_host.rsplit(":", 1)[0] if origin_host.count(":") == 1 else origin_host
    return name in ALLOWED_HOSTS


def make_retry_session(total: int = 3, backoff: float = 0.6):
    """
    requests.Session with automatic retry + exponential backoff on transient
    failures (connection errors, HTTP 429 / 502 / 503 / 504), honoring Retry-After.
    """
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    retry_kwargs: Dict[str, Any] = dict(
        total=total,
        connect=total,
        read=1,
        backoff_factor=backoff,
        status_forcelist=(429, 502, 503, 504),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    methods = frozenset(["GET", "HEAD", "POST", "OPTIONS"])
    try:
        retry = Retry(allowed_methods=methods, **retry_kwargs)
    except TypeError:  # urllib3 < 1.26
        retry = Retry(method_whitelist=methods, **retry_kwargs)
    adapter = HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=16)
    sess = requests.Session()
    sess.mount("https://", adapter)
    sess.mount("http://", adapter)
    return sess


def parse_cookie_string_to_dict(cookie_str: str) -> Dict[str, str]:
    result: Dict[str, str] = {}
    if not cookie_str:
        return result
    # Try SimpleCookie first, then fallback to manual ';' split for unescaped special chars
    for part in cookie_str.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        k, v = part.split("=", 1)
        k = k.strip()
        v = v.strip()
        if k:
            result[k] = v
    try:
        sc = http.cookies.SimpleCookie()
        sc.load(cookie_str)
        for k, morsel in sc.items():
            if k and morsel.value:
                result.setdefault(k, morsel.value)
    except Exception:
        pass
    return result


def parse_cookie_and_headers(raw: str) -> Tuple[str, Dict[str, str], Dict[str, str]]:
    """
    Universal parser that extracts (cookie_str, cookie_dict, headers_dict) from:
      1. Copy as cURL (Chrome / Safari / Firefox / Edge)
      2. Cookie-Editor JSON array or JSON headers dict
      3. Netscape cookies.txt
      4. Copy as fetch (Node.js)
      5. Raw HTTP Request Headers (1-line or Chrome 2-line format)
      6. Raw Cookie string (k1=v1; k2=v2)
    """
    raw = (raw or "").strip()
    if not raw:
        raise ValueError("输入内容为空，请粘贴有效的 Copy as cURL、请求头或 Cookie。")

    if raw.startswith("fetch(") and '"cookie"' not in raw.lower():
        raise ValueError(
            "检测到你复制的是普通「Copy as fetch」（浏览器出于安全限制默认不包含 Cookie）。"
            "请右键请求选择「Copy → Copy as cURL」或「Copy as fetch (Node.js)」！"
        )

    user_headers: Dict[str, str] = {}

    # 1. JSON array (Cookie-Editor export) or JSON dict
    if raw.startswith("[") or raw.startswith("{"):
        try:
            parsed_json = json.loads(raw)
            if isinstance(parsed_json, list):
                pairs: List[str] = [
                    f"{item['name']}={item['value']}"
                    for item in parsed_json
                    if isinstance(item, dict) and "name" in item and "value" in item
                ]
                if pairs:
                    user_headers["cookie"] = "; ".join(pairs)
            elif isinstance(parsed_json, dict):
                # Could be {"cookie": "..."} or {"cookies": {...}} or flat cookie dict
                if "cookie" in {k.lower() for k in parsed_json.keys()}:
                    for k, v in parsed_json.items():
                        if isinstance(v, str):
                            user_headers[k.lower().strip()] = v.strip()
                else:
                    pairs = [
                        f"{k}={v}"
                        for k, v in parsed_json.items()
                        if isinstance(v, (str, int)) and ":" not in str(k)
                    ]
                    if pairs:
                        user_headers["cookie"] = "; ".join(pairs)
        except Exception:
            pass

    # 2. Netscape cookies.txt format
    if "cookie" not in user_headers and (
        "\tTRUE\t" in raw or "\tFALSE\t" in raw or "# Netscape HTTP Cookie File" in raw
    ):
        pairs = []
        for line in raw.splitlines():
            line_s = line.strip()
            if not line_s or line_s.startswith("#"):
                continue
            parts = line_s.split("\t")
            if len(parts) >= 7:
                pairs.append(f"{parts[5].strip()}={parts[6].strip()}")
        if pairs:
            user_headers["cookie"] = "; ".join(pairs)

    # 3. Copy as cURL
    if "cookie" not in user_headers and raw.lstrip().startswith("curl "):
        joined = re.sub(r"\\\r?\n", " ", raw)
        joined = re.sub(r"(?<=\s)\$'", "'", joined)
        cookie_chunks: List[str] = []
        try:
            tokens = shlex.split(joined)
            i = 0
            while i < len(tokens):
                tok = tokens[i]
                if tok in ("-H", "--header") and i + 1 < len(tokens):
                    h = tokens[i + 1]
                    if ":" in h:
                        k, v = h.split(":", 1)
                        kl = k.strip().lower()
                        if kl == "cookie":
                            cookie_chunks.append(v.strip())
                        else:
                            user_headers[kl] = v.strip()
                    i += 2
                    continue
                if tok in ("-b", "--cookie") and i + 1 < len(tokens):
                    cookie_chunks.append(tokens[i + 1].strip())
                    i += 2
                    continue
                i += 1
        except ValueError:
            for m in re.finditer(r"(?:-H|--header)\s+(?:'([^']*)'|\"([^\"]*)\")", joined):
                h = m.group(1) or m.group(2) or ""
                if ":" in h:
                    k, v = h.split(":", 1)
                    kl = k.strip().lower()
                    if kl == "cookie":
                        cookie_chunks.append(v.strip())
                    else:
                        user_headers[kl] = v.strip()
            for m in re.finditer(r"(?:-b|--cookie)\s+(?:'([^']*)'|\"([^\"]*)\")", joined):
                c = m.group(1) or m.group(2) or ""
                if c:
                    cookie_chunks.append(c.strip())
        if cookie_chunks:
            user_headers["cookie"] = "; ".join(cookie_chunks)

    # 4. Copy as fetch (Node.js)
    if "cookie" not in user_headers and raw.startswith("fetch("):
        m = re.search(r'"cookie"\s*:\s*"((?:[^"\\]|\\.)*)"', raw, re.IGNORECASE)
        if m:
            user_headers["cookie"] = bytes(m.group(1), "utf-8").decode("unicode_escape")
        m_auth = re.search(r'"x-goog-authuser"\s*:\s*"([^"]*)"', raw, re.IGNORECASE)
        if m_auth:
            user_headers["x-goog-authuser"] = m_auth.group(1)

    # 5. Raw Request Headers or raw Cookie string
    if "cookie" not in user_headers:
        if "=" in raw and "\n" not in raw and not raw.lower().startswith("cookie:"):
            user_headers["cookie"] = raw.strip()
        else:
            remembered_key = ""
            for line in raw.splitlines():
                line_s = line.strip()
                if not line_s or line_s.startswith(":"):
                    continue
                if ": " in line_s:
                    k, v = line_s.split(": ", 1)
                    user_headers[k.strip().lower()] = v.strip()
                    remembered_key = ""
                elif line_s.endswith(":"):
                    remembered_key = line_s[:-1].strip().lower()
                elif remembered_key:
                    user_headers[remembered_key] = line_s
                    remembered_key = ""
                elif ":" in line_s and not line_s.lower().startswith(("http:", "https:")):
                    k, v = line_s.split(":", 1)
                    user_headers[k.strip().lower()] = v.strip()
                elif "=" in line_s and ";" in line_s and "cookie" not in user_headers:
                    user_headers["cookie"] = line_s

    cookie_str = user_headers.get("cookie", "").strip()
    cookie_dict = parse_cookie_string_to_dict(cookie_str)
    if not cookie_str or not cookie_dict:
        raise ValueError(
            "未能从粘贴的内容中提取到有效的 Cookie。请在浏览器开发者工具 Network 面板右键请求 → 选择「Copy → Copy as cURL」后重试。"
        )
    return cookie_str, cookie_dict, user_headers
