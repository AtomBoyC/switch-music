from __future__ import annotations

import os
import time
import urllib.parse
from typing import Any, Dict, List

from backend.config import DATA_DIR, make_retry_session, read_json_file, write_json_file

NOTIFICATION_CONFIG_FILE = DATA_DIR / "notification_config.json"
MASK_TOKEN = "********"


def _validate_http_url(url: str, label: str) -> str:
    clean = (url or "").strip()
    if not clean:
        return ""
    parsed = urllib.parse.urlparse(clean)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"{label} 必须以 http:// 或 https:// 开头。")
    return clean


def _normalize_bark_url(raw: str) -> str:
    val = (raw or "").strip().rstrip("/")
    if not val:
        return ""
    if val.startswith(("http://", "https://")):
        return _validate_http_url(val, "Bark 推送地址")
    # Bare Bark device key -> official Bark server
    return f"https://api.day.app/{val}"


class NotificationManager:
    """
    Multi-channel push notifier for headless NAS / Docker runs:
      - Generic Webhook (Feishu / DingTalk / WeCom / Discord / Slack / Gotify / Custom JSON)
      - Bark (iOS push)
      - Telegram Bot
    """

    def load_config(self) -> Dict[str, Any]:
        cfg = read_json_file(NOTIFICATION_CONFIG_FILE, {})
        if not isinstance(cfg, dict):
            cfg = {}
        webhook_url = str(cfg.get("webhook_url") or os.environ.get("SWITCH_MUSIC_WEBHOOK_URL") or "").strip()
        raw_bark = str(cfg.get("bark_url") or os.environ.get("SWITCH_MUSIC_BARK_URL") or "").strip()
        try:
            bark_url = _normalize_bark_url(raw_bark) if raw_bark else ""
        except ValueError:
            bark_url = raw_bark
        tg_token = str(
            cfg.get("telegram_bot_token") or os.environ.get("SWITCH_MUSIC_TG_BOT_TOKEN") or ""
        ).strip()
        tg_chat = str(
            cfg.get("telegram_chat_id") or os.environ.get("SWITCH_MUSIC_TG_CHAT_ID") or ""
        ).strip()
        has_any_channel = bool(webhook_url or bark_url or (tg_token and tg_chat))
        return {
            "enabled": bool(cfg.get("enabled", has_any_channel)),
            "notify_on_sync_error": bool(cfg.get("notify_on_sync_error", True)),
            "notify_on_sync_success": bool(cfg.get("notify_on_sync_success", True)),
            "webhook_url": webhook_url,
            "bark_url": bark_url,
            "telegram_bot_token": tg_token,
            "telegram_chat_id": tg_chat,
        }

    def get_public_config(self) -> Dict[str, Any]:
        cfg = self.load_config()
        return {
            "enabled": cfg["enabled"],
            "notify_on_sync_error": cfg["notify_on_sync_error"],
            "notify_on_sync_success": cfg["notify_on_sync_success"],
            "webhook_url": MASK_TOKEN if cfg["webhook_url"] else "",
            "has_webhook": bool(cfg["webhook_url"]),
            "bark_url": MASK_TOKEN if cfg["bark_url"] else "",
            "has_bark": bool(cfg["bark_url"]),
            "telegram_bot_token": MASK_TOKEN if cfg["telegram_bot_token"] else "",
            "has_telegram_token": bool(cfg["telegram_bot_token"]),
            "telegram_chat_id": cfg["telegram_chat_id"],
        }

    def save_config(self, incoming: Dict[str, Any]) -> Dict[str, Any]:
        existing = self.load_config()

        raw_wh = str(incoming.get("webhook_url") or "").strip()
        webhook_url = existing["webhook_url"] if raw_wh == MASK_TOKEN else _validate_http_url(raw_wh, "Webhook URL")

        raw_bark = str(incoming.get("bark_url") or "").strip()
        bark_url = existing["bark_url"] if raw_bark == MASK_TOKEN else _normalize_bark_url(raw_bark)

        raw_tg_tok = str(incoming.get("telegram_bot_token") or "").strip()
        tg_token = existing["telegram_bot_token"] if raw_tg_tok == MASK_TOKEN else raw_tg_tok
        tg_chat_id = str(incoming.get("telegram_chat_id") or "").strip()

        saved = {
            "enabled": bool(incoming.get("enabled", True)),
            "notify_on_sync_error": bool(incoming.get("notify_on_sync_error", True)),
            "notify_on_sync_success": bool(incoming.get("notify_on_sync_success", True)),
            "webhook_url": webhook_url,
            "bark_url": bark_url,
            "telegram_bot_token": tg_token,
            "telegram_chat_id": tg_chat_id,
            "updated_at": int(time.time()),
        }
        write_json_file(NOTIFICATION_CONFIG_FILE, saved)
        return self.get_public_config()

    def send(self, title: str, message: str, event: str = "info", force: bool = False) -> Dict[str, Any]:
        cfg = self.load_config()
        if not force:
            if not cfg["enabled"]:
                return {"sent": False, "channels": [], "errors": []}
            if event == "sync_error" and not cfg["notify_on_sync_error"]:
                return {"sent": False, "channels": [], "errors": []}
            if event == "sync_success" and not cfg["notify_on_sync_success"]:
                return {"sent": False, "channels": [], "errors": []}

        channels_ok: List[str] = []
        errors: List[str] = []
        sess = make_retry_session(total=2, backoff=0.4)
        full_text = f"🎵 {title}\n{message}"

        # 1. Webhook
        wh = cfg["webhook_url"]
        if wh:
            try:
                low = wh.lower()
                if "feishu.cn" in low or "larksuite.com" in low:
                    body: Dict[str, Any] = {"msg_type": "text", "content": {"text": full_text}}
                elif "dingtalk.com" in low or "weixin.qq.com" in low:
                    body = {"msgtype": "text", "text": {"content": full_text}}
                elif "discord.com/api/webhooks" in low:
                    body = {"content": full_text}
                elif "hooks.slack.com" in low:
                    body = {"text": full_text}
                else:
                    body = {
                        "event": event,
                        "title": title,
                        "message": message,
                        "text": full_text,
                        "timestamp": int(time.time()),
                    }
                r = sess.post(wh, json=body, timeout=10)
                if r.status_code >= 400:
                    raise RuntimeError(f"HTTP {r.status_code}")
                channels_ok.append("webhook")
            except Exception as e:
                errors.append(f"Webhook: {e}")

        # 2. Bark
        bark = cfg["bark_url"]
        if bark:
            try:
                r = sess.post(
                    bark.rstrip("/"),
                    json={"title": f"Switch Music · {title}", "body": message, "group": "SwitchMusic"},
                    timeout=10,
                )
                if r.status_code >= 400:
                    raise RuntimeError(f"HTTP {r.status_code}")
                channels_ok.append("bark")
            except Exception as e:
                errors.append(f"Bark: {e}")

        # 3. Telegram Bot
        tg_tok = cfg["telegram_bot_token"]
        tg_chat = cfg["telegram_chat_id"]
        if tg_tok and tg_chat:
            try:
                tg_url = f"https://api.telegram.org/bot{tg_tok}/sendMessage"
                r = sess.post(
                    tg_url,
                    json={"chat_id": tg_chat, "text": full_text, "disable_web_page_preview": True},
                    timeout=10,
                )
                if r.status_code >= 400:
                    raise RuntimeError(f"HTTP {r.status_code}")
                channels_ok.append("telegram")
            except Exception as e:
                errors.append(f"Telegram: {e}")

        if force and not channels_ok and not errors:
            raise ValueError("尚未配置任何推送渠道（请填写 Webhook、Bark 或 Telegram 配置后再测试）。")

        return {
            "sent": len(channels_ok) > 0,
            "channels": channels_ok,
            "errors": errors,
        }


notifier = NotificationManager()
