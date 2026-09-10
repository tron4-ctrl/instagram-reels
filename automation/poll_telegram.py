#!/usr/bin/env python3
"""Optional Telegram ingestion adapter. No-op when Telegram secrets are absent."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "automation" / "telegram_offset.json"
LOG = ROOT / "automation" / "telegram_messages.jsonl"
URL_RE = re.compile(r"https?://(?:www\.)?instagram\.com/reel/[A-Za-z0-9_-]+(?:/)?(?:[?#]\S*)?", re.I)


def api(method: str, params=None):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        return {"ok": True, "result": []}
    url = f"https://api.telegram.org/bot{token}/{method}"
    if params:
        url += "?" + urlencode(params)
    req = Request(url, headers={"User-Agent": "InstagramReelsAutoSync/4.0"})
    with urlopen(req, timeout=40) as resp:
        return json.loads(resp.read().decode("utf-8"))


def send(chat_id: str, text: str) -> None:
    api("sendMessage", {"chat_id": chat_id, "text": text, "disable_web_page_preview": "true"})


def load_offset() -> int:
    try:
        return int(json.loads(STATE.read_text("utf-8")).get("offset", 0))
    except Exception:
        return 0


def save_offset(value: int) -> None:
    STATE.write_text(json.dumps({"offset": value, "updated_at": datetime.now(timezone.utc).isoformat()}), encoding="utf-8")


def main() -> None:
    if not os.environ.get("TELEGRAM_BOT_TOKEN", "").strip():
        print("Telegram disabled: TELEGRAM_BOT_TOKEN not configured")
        return

    allowed = os.environ.get("TELEGRAM_ALLOWED_CHAT_ID", "").strip()
    offset = load_offset()
    data = api("getUpdates", {"offset": offset, "limit": 100, "timeout": 0, "allowed_updates": json.dumps(["message", "channel_post"])})
    updates = data.get("result", [])
    max_seen = offset
    LOG.parent.mkdir(parents=True, exist_ok=True)

    for upd in updates:
        max_seen = max(max_seen, int(upd["update_id"]) + 1)
        msg = upd.get("message") or upd.get("channel_post") or {}
        chat = msg.get("chat") or {}
        chat_id = str(chat.get("id", ""))
        if allowed and chat_id != allowed:
            continue
        text = msg.get("text", "") or msg.get("caption", "") or ""
        urls = list(dict.fromkeys(URL_RE.findall(text)))
        if not urls:
            continue

        for url in urls:
            proc = subprocess.run([sys.executable, str(ROOT / "automation" / "sync_reels.py"), url], capture_output=True, text=True)
            try:
                result = json.loads(proc.stdout.strip())[0]
            except Exception:
                result = {"status": "error", "reason": (proc.stderr or proc.stdout or "Unknown error")[-1000:]}
            with LOG.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"timestamp": datetime.now(timezone.utc).isoformat(), "chat_id": chat_id, "url": url, "result": result}, ensure_ascii=False) + "\n")

            status = result.get("status")
            sc = result.get("shortcode", "")
            if status == "added":
                send(chat_id, f"✅ Reel added: {sc}\nCategory: {result.get('category', '')}\nLibrary: {result.get('total')} Reels")
            elif status == "duplicate":
                send(chat_id, f"ℹ️ Already in library: {sc}\nTotal: {result.get('total')} Reels")
            elif status == "ignored":
                send(chat_id, "⚠️ Ignored: not a valid Instagram Reel URL")
            else:
                send(chat_id, f"❌ Reel not added.\n{result.get('reason', 'Unknown error')}")

    if updates:
        save_offset(max_seen)


if __name__ == "__main__":
    main()
