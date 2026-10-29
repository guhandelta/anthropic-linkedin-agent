"""Telegram human-in-the-loop review for the LinkedIn agent.

Flow
  1. Send the infographic + the full post text with two buttons:
       [✅ Approve & Post]   [❌ Reject]
  2. Wait up to REVIEW_TIMEOUT (default 3 h) for a tap, pinging every
     REMINDER_EVERY (default 20 min) until you answer.
  3. Approve -> button becomes "⏳ Posting…" (blocks double taps), the agent
     posts once, then the button becomes "✅ Posted" (inert).
     Reject   -> "❌ Rejected — not posted".   Timeout -> "⌛ Expired — not posted".

Every draft has ONE fixed draft_id (also in each button's callback data),
so reminders, retries and repeat taps all point at the same draft and it can
only ever be posted once. Only taps from TELEGRAM_CHAT_ID are accepted.

Helper:  python telegram_review.py --find-chat-id
         (send any message to your bot first; prints your chat id)
         python telegram_review.py --ping
         (sends a test message to verify Telegram bot ping)
"""
from __future__ import annotations
import json
import os
import sys
import time
from pathlib import Path

import requests

API = "https://api.telegram.org/bot{token}/{method}"
STATE = Path(__file__).parent / "state" / "drafts.json"


# ------------------------------------------------------------- draft state
def _load() -> dict:
    return json.loads(STATE.read_text()) if STATE.exists() else {}


def _save(data: dict):
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def get_status(draft_id: str) -> str | None:
    return _load().get(draft_id, {}).get("status")


def set_status(draft_id: str, status: str, **extra):
    data = _load()
    data.setdefault(draft_id, {}).update({"status": status, "updated": int(time.time()), **extra})
    _save(data)


# ------------------------------------------------------------- bot client
class TelegramReviewer:
    def __init__(self, token: str, chat_id: str, timeout_s: int = 3 * 3600,
                 remind_every_s: int = 20 * 60):
        self.token, self.chat_id = token, str(chat_id)
        self.timeout_s, self.remind_every_s = timeout_s, remind_every_s
        self.offset = None

    def _call(self, method: str, files=None, **params):
        url = API.format(token=self.token, method=method)
        if files:
            r = requests.post(url, data=params, files=files, timeout=70)
        else:
            r = requests.post(url, json=params, timeout=70)
        body = r.json()
        if not body.get("ok"):
            raise RuntimeError(f"Telegram {method} failed: {body}")
        return body["result"]

    @staticmethod
    def _buttons(*rows):
        return {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in row] for row in rows]}

    def _set_button(self, message_id: int, text: str, draft_id: str):
        # Telegram can't grey out a button; an inert "noop" button is the standard way.
        try:
            self._call("editMessageReplyMarkup", chat_id=self.chat_id, message_id=message_id,
                       reply_markup=self._buttons([(text, f"noop:{draft_id}")]))
        except Exception:
            pass

    def _answer_cq(self, cq_id: str, text: str):
        try:
            self._call("answerCallbackQuery", callback_query_id=cq_id, text=text)
        except Exception:
            pass

    def _skip_old_updates(self):
        """Ignore taps made before this draft was sent."""
        ups = self._call("getUpdates", offset=-1, timeout=0)
        self.offset = ups[-1]["update_id"] + 1 if ups else None

    # ---------------------------------------------------------- public API
    def send_draft(self, draft_id: str, topic: str, post: str, image_path: Path) -> int:
        self._skip_old_updates()
        with open(image_path, "rb") as f:
            self._call("sendPhoto", chat_id=self.chat_id,
                       caption=f"🖼️ Infographic for today's draft\n🆔 {draft_id}",
                       files={"photo": f})
        text = (f"📝 New LinkedIn draft for review\n📌 Topic: {topic}\n"
                f"📏 {len(post)} characters\n🆔 {draft_id}\n\n{post}")
        msg = self._call("sendMessage", chat_id=self.chat_id, text=text[:4096],
                         reply_markup=self._buttons([("✅ Approve & Post", f"approve:{draft_id}"),
                                                     ("❌ Reject", f"reject:{draft_id}")]))
        set_status(draft_id, "pending", topic=topic, message_id=msg["message_id"])
        return msg["message_id"]

    def wait_for_decision(self, draft_id: str, message_id: int) -> str:
        """Returns 'approved', 'rejected' or 'expired'."""
        start = time.time()
        next_ping = start + self.remind_every_s
        while True:
            now = time.time()
            if now - start >= self.timeout_s:
                self._set_button(message_id, "⌛ Expired — not posted", draft_id)
                try:
                    self._call("sendMessage", chat_id=self.chat_id,
                               reply_to_message_id=message_id,
                               text="⌛ No answer within 3 hours, so this draft was NOT posted.")
                except Exception:
                    pass
                set_status(draft_id, "expired")
                return "expired"
            if now >= next_ping:
                left = int((self.timeout_s - (now - start)) // 60)
                try:
                    self._call("sendMessage", chat_id=self.chat_id, reply_to_message_id=message_id,
                               text=f"⏰ Reminder: today's LinkedIn draft is waiting for you. "
                                    f"Tap Approve or Reject above ({left} min left).")
                except Exception:
                    pass
                next_ping += self.remind_every_s

            wait = int(max(1, min(50, next_ping - time.time(), self.timeout_s - (time.time() - start))))
            params = {"timeout": wait, "allowed_updates": ["callback_query"]}
            if self.offset is not None:
                params["offset"] = self.offset
            for up in self._call("getUpdates", **params):
                self.offset = up["update_id"] + 1
                decision = self._handle(up.get("callback_query"), draft_id, message_id)
                if decision:
                    return decision

    def _handle(self, cq, draft_id, message_id):
        if not cq:
            return None
        if str(cq["from"]["id"]) != self.chat_id and str(cq["message"]["chat"]["id"]) != self.chat_id:
            self._answer_cq(cq["id"], text="Not authorised.")
            return None
        action, _, cb_draft = cq.get("data", "").partition(":")
        if cb_draft != draft_id or action == "noop" or get_status(draft_id) != "pending":
            self._answer_cq(cq["id"], text="This draft is already handled. 👍")
            return None
        if action == "approve":
            set_status(draft_id, "approved")          # lock before posting: no double post
            self._answer_cq(cq["id"], text="🚀 Posting to LinkedIn…")
            self._set_button(message_id, "⏳ Posting…", draft_id)
            return "approved"
        if action == "reject":
            set_status(draft_id, "rejected")
            self._answer_cq(cq["id"], text="Rejected. Nothing will be posted.")
            self._set_button(message_id, "❌ Rejected — not posted", draft_id)
            return "rejected"
        return None

    def mark_posted(self, draft_id: str, message_id: int, post_urn: str):
        set_status(draft_id, "posted", post_urn=post_urn)
        self._set_button(message_id, "✅ Posted", draft_id)
        link = f"https://www.linkedin.com/feed/update/{post_urn}/" if post_urn else ""
        self._call("sendMessage", chat_id=self.chat_id, reply_to_message_id=message_id,
                   text=f"🎉 Posted to LinkedIn! {link}")

    def mark_failed(self, draft_id: str, message_id: int, error: str):
        set_status(draft_id, "failed", error=error[:500])
        self._set_button(message_id, "⚠️ Post failed", draft_id)
        self._call("sendMessage", chat_id=self.chat_id, reply_to_message_id=message_id,
                   text=f"⚠️ Posting failed, nothing went out:\n{error[:3500]}")


# ------------------------------------------------------------- helper CLI
if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
    token = os.environ["TELEGRAM_BOT_TOKEN"]

    if "--find-chat-id" in sys.argv:
        ups = requests.get(API.format(token=token, method="getUpdates"), timeout=30).json()["result"]
        chats = {(u.get("message") or {}).get("chat", {}).get("id") for u in ups} - {None}
        print("Chat id(s):", chats or "none yet — send any message to your bot, then run again")
    elif "--test" in sys.argv or "--ping" in sys.argv:
        chat_id = os.environ["TELEGRAM_CHAT_ID"]
        reviewer = TelegramReviewer(token, chat_id)
        msg = reviewer._call("sendMessage", chat_id=chat_id, text="🤖 Test ping from LinkedIn Agent bot! Connection verified.")
        print(f"Ping delivered successfully to chat {chat_id}! Message ID: {msg.get('message_id')}")

