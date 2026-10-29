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
import uuid
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
    def download_photo(self, photo_list: list, dest_path: Path) -> Path:
        """Download highest resolution photo from Telegram message to dest_path."""
        if not photo_list:
            raise ValueError("No photo found in message.")
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        file_id = photo_list[-1]["file_id"]
        res = self._call("getFile", file_id=file_id)
        file_path = res["file_path"]
        download_url = f"https://api.telegram.org/file/bot{self.token}/{file_path}"
        r = requests.get(download_url, timeout=60)
        r.raise_for_status()
        dest_path.write_bytes(r.content)
        return dest_path

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

    def send_text_draft(self, draft_id: str, topic: str, post: str) -> int:
        self._skip_old_updates()
        text = (f"📝 LinkedIn Direct Draft (Text Only)\n📌 {topic}\n"
                f"📏 {len(post)} characters\n🆔 {draft_id}\n\n{post}")
        msg = self._call("sendMessage", chat_id=self.chat_id, text=text[:4096],
                         reply_markup=self._buttons([("✅ Approve & Post", f"approve:{draft_id}"),
                                                     ("❌ Reject", f"reject:{draft_id}")]))
        set_status(draft_id, "pending", topic=topic, message_id=msg["message_id"])
        return msg["message_id"]

    def prompt_direct_choice(self, text: str, timeout_s: int = 300) -> str:
        """Ask user if they want an auto-designed infographic for their direct post."""
        choice_id = uuid.uuid4().hex[:8]
        preview = (text[:280] + "...") if len(text) > 280 else text
        msg = self._call(
            "sendMessage", chat_id=self.chat_id,
            text=f"📝 Direct post received ({len(text)} chars):\n\n\"{preview}\"\n\nHow would you like to publish?",
            reply_markup=self._buttons(
                [("🎨 Auto-Design Infographic & Review", f"direct_info:{choice_id}")],
                [("⚡ Post As-Is (Text Only)", f"direct_text:{choice_id}")],
                [("❌ Cancel", f"direct_cancel:{choice_id}")]
            )
        )
        message_id = msg["message_id"]
        start = time.time()
        while time.time() - start < timeout_s:
            params = {"timeout": 20, "allowed_updates": ["callback_query"]}
            if self.offset is not None:
                params["offset"] = self.offset
            for up in self._call("getUpdates", **params):
                self.offset = up["update_id"] + 1
                cq = up.get("callback_query")
                if not cq:
                    continue
                data = cq.get("data", "")
                act, _, cid = data.partition(":")
                if cid != choice_id:
                    continue
                if act == "direct_info":
                    self._answer_cq(cq["id"], text="Generating infographic...")
                    self._set_button(message_id, "🎨 Generating Infographic...", choice_id)
                    return "infographic"
                elif act == "direct_text":
                    self._answer_cq(cq["id"], text="Preparing text-only post...")
                    self._set_button(message_id, "⚡ Text-Only Selected", choice_id)
                    return "text_only"
                elif act == "direct_cancel":
                    self._answer_cq(cq["id"], text="Cancelled.")
                    self._set_button(message_id, "❌ Cancelled", choice_id)
                    return "cancel"
        return "cancel"

    def wait_for_decision(self, draft_id: str, message_id: int) -> dict:
        """Returns dict:
        {'action': 'approved'}
        {'action': 'revise', 'feedback': '...'}
        {'action': 'suggest_topics'}
        {'action': 'new_topic', 'topic': '...', 'source': '...'}
        {'action': 'rejected'}
        {'action': 'expired'}
        """
        start = time.time()
        next_ping = start + self.remind_every_s
        awaiting_feedback = False

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
                return {"action": "expired"}

            if now >= next_ping and not awaiting_feedback:
                left = int((self.timeout_s - (now - start)) // 60)
                try:
                    self._call("sendMessage", chat_id=self.chat_id, reply_to_message_id=message_id,
                               text=f"⏰ Reminder: today's LinkedIn draft is waiting for you. "
                                    f"Tap Approve or Reject above ({left} min left).")
                except Exception:
                    pass
                next_ping += self.remind_every_s

            wait = int(max(1, min(40, next_ping - time.time(), self.timeout_s - (time.time() - start))))
            params = {"timeout": wait, "allowed_updates": ["callback_query", "message"]}
            if self.offset is not None:
                params["offset"] = self.offset

            for up in self._call("getUpdates", **params):
                self.offset = up["update_id"] + 1

                # Handle text messages (e.g. revisions or manual topic command)
                msg = up.get("message")
                if msg:
                    sender = str(msg.get("from", {}).get("id"))
                    chat = str(msg.get("chat", {}).get("id"))
                    text = (msg.get("text") or "").strip()

                    if sender == self.chat_id or chat == self.chat_id:
                        if text.startswith(("/topic ", "/post ")):
                            custom_topic = text.split(" ", 1)[1].strip()
                            self._call("sendMessage", chat_id=self.chat_id,
                                       text=f"🎯 Understood! Switched to topic:\n'{custom_topic}'\nRegenerating draft...")
                            return {"action": "new_topic", "topic": custom_topic, "source": None}

                        if awaiting_feedback and text:
                            self._call("sendMessage", chat_id=self.chat_id, reply_to_message_id=msg["message_id"],
                                       text=f"✍️ Feedback received:\n\"{text}\"\n\nRegenerating post & infographic...")
                            return {"action": "revise", "feedback": text}

                # Handle button callbacks
                cq = up.get("callback_query")
                if not cq:
                    continue

                if str(cq["from"]["id"]) != self.chat_id and str(cq["message"]["chat"]["id"]) != self.chat_id:
                    self._answer_cq(cq["id"], text="Not authorised.")
                    continue

                data = cq.get("data", "")
                action, _, cb_draft = data.partition(":")

                if action == "noop":
                    self._answer_cq(cq["id"], text="This action is complete.")
                    continue

                if action == "approve" and cb_draft == draft_id:
                    set_status(draft_id, "approved")
                    self._answer_cq(cq["id"], text="🚀 Posting to LinkedIn & groups…")
                    self._set_button(message_id, "⏳ Posting…", draft_id)
                    return {"action": "approved"}

                if action == "reject" and cb_draft == draft_id:
                    self._answer_cq(cq["id"], text="Draft rejected.")
                    self._set_button(message_id, "❌ Rejected", draft_id)
                    keyboard = self._buttons(
                        [("✍️ Revise with Corrections", f"opt_revise:{draft_id}")],
                        [("💡 Suggest Topics from Allowed Domains", f"opt_suggest:{draft_id}")],
                        [("⏹️ Skip Today", f"opt_skip:{draft_id}")]
                    )
                    self._call("sendMessage", chat_id=self.chat_id, reply_to_message_id=message_id,
                               text="❌ Draft rejected. How would you like to proceed?",
                               reply_markup=keyboard)
                    continue

                if action == "opt_revise" and cb_draft == draft_id:
                    self._answer_cq(cq["id"], text="Awaiting your feedback...")
                    awaiting_feedback = True
                    self._call("sendMessage", chat_id=self.chat_id,
                               text="✍️ Please send your corrections or notes as a reply message. The agent will rewrite the draft and redraw the infographic.")
                    continue

                if action == "opt_suggest" and cb_draft == draft_id:
                    self._answer_cq(cq["id"], text="Generating suggestions...")
                    self._call("sendMessage", chat_id=self.chat_id,
                               text="🔍 Scanning allowed domains for fresh topic suggestions...")
                    return {"action": "suggest_topics"}

                if action == "opt_skip" and cb_draft == draft_id:
                    set_status(draft_id, "rejected")
                    self._answer_cq(cq["id"], text="Skipped.")
                    self._call("sendMessage", chat_id=self.chat_id,
                               text="⏹️ Skipped for today. Nothing will be posted.")
                    return {"action": "rejected"}

        return {"action": "rejected"}

    def choose_topic(self, draft_id: str, topic_options: list[dict], timeout_s: int = 1800) -> dict:
        """Presents topic options with buttons and waits for user choice or custom text reply."""
        if not topic_options:
            return {"action": "none"}

        rows = []
        summary_lines = ["💡 **Pick a topic from allowed domains:**\n"]
        for idx, opt in enumerate(topic_options, 1):
            t = opt.get("topic", "Topic")
            s = opt.get("source", "")
            summary_lines.append(f"{idx}. {t} (Source: {s})")
            short_label = (f"{idx}. {t}")[:36]
            rows.append([(short_label, f"pick_topic:{idx-1}:{draft_id}")])

        rows.append([("✍️ Custom Topic (reply with text)", f"opt_custom:{draft_id}"),
                     ("⏹️ Skip Today", f"opt_skip:{draft_id}")])

        msg = self._call("sendMessage", chat_id=self.chat_id,
                         text="\n".join(summary_lines),
                         reply_markup=self._buttons(*rows))

        start = time.time()
        awaiting_custom = False

        while time.time() - start < timeout_s:
            wait = 30
            params = {"timeout": wait, "allowed_updates": ["callback_query", "message"]}
            if self.offset is not None:
                params["offset"] = self.offset

            for up in self._call("getUpdates", **params):
                self.offset = up["update_id"] + 1

                msg_obj = up.get("message")
                if msg_obj:
                    sender = str(msg_obj.get("from", {}).get("id"))
                    text = (msg_obj.get("text") or "").strip()
                    if sender == self.chat_id and text:
                        if text.startswith(("/topic ", "/post ")):
                            text = text.split(" ", 1)[1].strip()
                        self._call("sendMessage", chat_id=self.chat_id,
                                   text=f"🎯 Understood! Drafting on:\n'{text}'")
                        return {"action": "new_topic", "topic": text, "source": None}

                cq = up.get("callback_query")
                if not cq:
                    continue

                data = cq.get("data", "")
                action, _, rest = data.partition(":")

                if action == "pick_topic":
                    idx_str, _, cb_draft = rest.partition(":")
                    idx = int(idx_str)
                    chosen = topic_options[idx]
                    self._answer_cq(cq["id"], text="Selected!")
                    self._call("sendMessage", chat_id=self.chat_id,
                               text=f"🎯 You selected:\n**{chosen['topic']}**\n(Source: {chosen.get('source')})\nDrafting post...")
                    return {"action": "new_topic", "topic": chosen["topic"], "source": chosen.get("source")}

                if action == "opt_custom":
                    self._answer_cq(cq["id"], text="Type your custom topic...")
                    awaiting_custom = True
                    self._call("sendMessage", chat_id=self.chat_id,
                               text="✍️ Reply to this message with your topic or article link.")
                    continue

                if action == "opt_skip":
                    self._answer_cq(cq["id"], text="Skipped.")
                    return {"action": "rejected"}

        return {"action": "rejected"}

    def listen_for_commands(self, on_topic_callback, on_direct_callback, on_daily_callback=None, poll_interval_s: int = 5):
        """Polls for incoming /topic, /direct, photos, or manual prompts from user."""
        self._skip_old_updates()
        print(f"Listening on Telegram for commands from chat {self.chat_id}...")
        help_text = (
            "🤖 **LinkedIn Agent is live!**\n\n"
            "Here is what you can send:\n"
            "• `/topic <topic>`: Research, draft post + infographic, get consent -> post to Wall & all groups\n"
            "• `/direct <post text>`: Provide your own post. Choose auto-infographic or text-only, get consent -> post to Wall & all groups\n"
            "• **Send any photo with a caption**: Posts your photo + caption to Wall & all groups\n"
            "• `/daily`: Run today's automated post from allowed_domains\n"
            "• Or simply paste your post or type any topic!"
        )
        self._call("sendMessage", chat_id=self.chat_id, text=help_text)

        while True:
            params = {"timeout": 30, "allowed_updates": ["message"]}
            if self.offset is not None:
                params["offset"] = self.offset

            try:
                updates = self._call("getUpdates", **params)
            except Exception as e:
                print(f"Telegram polling error: {e}")
                time.sleep(poll_interval_s)
                continue

            for up in updates:
                self.offset = up["update_id"] + 1
                msg = up.get("message")
                if not msg:
                    continue

                sender = str(msg.get("from", {}).get("id"))
                chat = str(msg.get("chat", {}).get("id"))
                if sender != self.chat_id and chat != self.chat_id:
                    continue

                text = (msg.get("text") or msg.get("caption") or "").strip()
                photos = msg.get("photo")

                if text in ("/start", "/help"):
                    self._call("sendMessage", chat_id=self.chat_id, text=help_text)
                    continue

                if text == "/daily":
                    self._call("sendMessage", chat_id=self.chat_id,
                               text="🚀 Triggering today's automated post discovery from allowed_domains...")
                    if on_daily_callback:
                        try:
                            on_daily_callback()
                        except Exception as e:
                            self._call("sendMessage", chat_id=self.chat_id, text=f"⚠️ Error: {str(e)[:1000]}")
                    continue

                # Case 1: Photo uploaded with caption
                if photos:
                    from pathlib import Path
                    uploads_dir = Path(__file__).parent / "output" / "telegram_uploads"
                    img_path = uploads_dir / f"upload_{int(time.time())}.png"
                    try:
                        self.download_photo(photos, img_path)
                        self._call("sendMessage", chat_id=self.chat_id,
                                   text="📸 Photo received! Preparing direct post with your image...")
                        on_direct_callback(text or "Shared update", custom_image_path=img_path, generate_infographic=False)
                    except Exception as e:
                        self._call("sendMessage", chat_id=self.chat_id, text=f"⚠️ Failed to process photo: {e}")
                    continue

                if not text:
                    continue

                # Case 2: Explicit /topic command
                if text.startswith(("/topic ", "/idea ", "/draft ")):
                    topic = text.split(" ", 1)[1].strip()
                    self._call("sendMessage", chat_id=self.chat_id,
                               text=f"🎯 Researching & drafting on topic:\n'{topic}'\nI will send the draft + infographic for your approval.")
                    try:
                        on_topic_callback(topic)
                    except Exception as e:
                        self._call("sendMessage", chat_id=self.chat_id, text=f"⚠️ Error: {str(e)[:1000]}")
                    continue

                # Case 3: Explicit /direct or /publish command
                if text.startswith(("/direct ", "/publish ")):
                    direct_text = text.split(" ", 1)[1].strip()
                    choice = self.prompt_direct_choice(direct_text)
                    if choice == "infographic":
                        on_direct_callback(direct_text, custom_image_path=None, generate_infographic=True)
                    elif choice == "text_only":
                        on_direct_callback(direct_text, custom_image_path=None, generate_infographic=False)
                    continue

                # Case 4: Free-form text
                # If long (>=80 chars), treat as direct post; else treat as topic
                if len(text) >= 80:
                    choice = self.prompt_direct_choice(text)
                    if choice == "infographic":
                        on_direct_callback(text, custom_image_path=None, generate_infographic=True)
                    elif choice == "text_only":
                        on_direct_callback(text, custom_image_path=None, generate_infographic=False)
                else:
                    self._call("sendMessage", chat_id=self.chat_id,
                               text=f"🎯 Researching & drafting on topic:\n'{text}'\nI will send the draft + infographic for your approval.")
                    try:
                        on_topic_callback(text)
                    except Exception as e:
                        self._call("sendMessage", chat_id=self.chat_id, text=f"⚠️ Error: {str(e)[:1000]}")

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

