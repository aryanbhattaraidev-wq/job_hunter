"""Notifications: Telegram Bot API (free) + Gmail API (free quota). Digest = top-scored unseen jobs."""
from __future__ import annotations
import html, json, os
import httpx
from .. import db
from ..config import Config, load_config


def build_digest(cfg: Config) -> tuple[list, str, str]:
    """Returns (job_rows, plain_text, html). Only jobs not yet notified and above min_score."""
    c = db.conn()
    rows = c.execute("SELECT * FROM jobs WHERE status='scored' AND score>=? ORDER BY score DESC LIMIT ?",
                     (cfg.notify.min_score, cfg.notify.digest_max)).fetchall()
    if not rows:
        return [], "", ""
    lines, hl = [], []
    for r in rows:
        where = r["location"] or ("Remote" if r["remote"] else "")
        note = (json.loads(r["score_json"] or "{}").get("llm", {}) or {}).get("one_line", "")
        lines.append(f"{r['score']:.0f}  {r['title']} @ {r['company']} ({where})" + (f"\n    {note}" if note else "") + f"\n    {r['url']}")
        hl.append(f"<li><b>{r['score']:.0f}</b> &middot; <a href=\"{html.escape(r['url'])}\">{html.escape(r['title'])}</a> "
                  f"@ {html.escape(r['company'])} <i>({html.escape(where)})</i></li>")
    text = f"{len(rows)} new matching jobs\n\n" + "\n".join(lines)
    return rows, text, f"<h3>{len(rows)} new matching jobs</h3><ul>{''.join(hl)}</ul>"


def send_telegram(text: str, chat_id: str | None = None) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat = chat_id or load_config().notify.telegram_chat_id
    if not token or not chat:
        raise RuntimeError("Telegram needs TELEGRAM_BOT_TOKEN and a chat id")
    for i in range(0, len(text), 3900):  # Telegram limit is 4096 chars
        r = httpx.post(f"https://api.telegram.org/bot{token}/sendMessage",
                       json={"chat_id": chat, "text": text[i:i + 3900], "disable_web_page_preview": True}, timeout=30)
        r.raise_for_status()


def find_telegram_chat_id() -> str | None:
    """User sends any message to their bot, then this discovers the chat id (no manual API digging)."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    r = httpx.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=30)
    r.raise_for_status()
    for u in reversed(r.json().get("result", [])):
        m = u.get("message") or u.get("channel_post")
        if m:
            return str(m["chat"]["id"])
    return None


def notify_all(cfg: Config | None = None) -> dict:
    cfg = cfg or load_config()
    rows, text, html_body = build_digest(cfg)
    if not rows:
        return {"sent": 0}
    res = {"sent": len(rows), "channels": [], "errors": {}}
    if cfg.notify.telegram_enabled:
        try:
            send_telegram(text)
            res["channels"].append("telegram")
        except Exception as e:
            res["errors"]["telegram"] = str(e)
    if cfg.notify.email_enabled:
        try:
            from .gmail import send_email
            send_email(cfg.notify.email_to, f"[jobhunter] {len(rows)} new matching jobs", text, html_body)
            res["channels"].append("email")
        except Exception as e:
            res["errors"]["email"] = str(e)
    if res["channels"]:  # only mark as notified when something actually went out
        c = db.conn()
        c.executemany("UPDATE jobs SET status='notified' WHERE id=?", [(r["id"],) for r in rows])
        c.commit()
    return res
