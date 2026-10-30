"""Telegram human-in-the-loop review and interactive command center for the LinkedIn agent.

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
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests

# Base endpoint for Telegram Bot API calls
API = "https://api.telegram.org/bot{token}/{method}"

# Persistent state file tracking each draft's review lifecycle (pending, approved, rejected, expired, posted, failed)
STATE = Path(__file__).parent / "state" / "drafts.json"


# ------------------------------------------------------------- draft state machine
def _load() -> dict:
    """Load persisted draft states from disk."""
    return json.loads(STATE.read_text()) if STATE.exists() else {}


def _save(data: dict):
    """Save draft states to disk atomically."""
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def get_status(draft_id: str) -> str | None:
    """Retrieve the current lifecycle status of a draft."""
    return _load().get(draft_id, {}).get("status")


def set_status(draft_id: str, status: str, **extra):
    """Transition a draft to a new lifecycle state with a timestamp and optional metadata."""
    data = _load()
    data.setdefault(draft_id, {}).update({"status": status, "updated": int(time.time()), **extra})
    _save(data)


# ------------------------------------------------------------- Telegram Bot Client
REMINDER_STATE_FILE = Path(__file__).parent / "state" / "cron_reminder.json"


def get_last_human_commit_days(repo_dir: Path | None = None) -> int | None:
    """Returns the number of days since the last non-bot commit to the repository."""
    target_dir = repo_dir or Path(__file__).parent
    bot_names = {"linkedin-agent", "github-actions", "github-actions[bot]", "actions-user"}
    bot_emails = {"agent@users.noreply.github.com", "actions@github.com"}
    try:
        res = subprocess.run(
            ["git", "-C", str(target_dir), "log", "-n", "60", "--format=%ct|%an|%ae"],
            capture_output=True, text=True, check=True
        )
        for line in res.stdout.strip().splitlines():
            parts = line.split("|")
            if len(parts) >= 3:
                ts, author, email = parts[0].strip(), parts[1].strip().lower(), parts[2].strip().lower()
                if author in bot_names or email in bot_emails or "actions" in email or ("noreply" in email and "bot" in author):
                    continue
                dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
                return max(0, (datetime.now(timezone.utc) - dt).days)
        # Fallback to the latest commit if all were filtered
        fallback = subprocess.run(
            ["git", "-C", str(target_dir), "log", "-1", "--format=%ct"],
            capture_output=True, text=True, check=True
        )
        out = fallback.stdout.strip()
        if out:
            dt = datetime.fromtimestamp(int(out), tz=timezone.utc)
            return max(0, (datetime.now(timezone.utc) - dt).days)
    except Exception as e:
        print(f"[Commit Reminder] Could not query git commit history: {e}")
    return None


def check_commit_reminder(repo_dir: Path | None = None, force: bool = False) -> dict:
    """Checks whether a GitHub Actions inactivity warning should be delivered.
    Rules:
      - Remind every 20 days (e.g. day 20, 40)
      - Remind EVERY DAY after day 52 (day 52, 53, 54, ..., 60)
      GitHub automatically disables scheduled Actions workflows after 60 days of inactivity.
    """
    days = get_last_human_commit_days(repo_dir)
    if days is None:
        return {"should_remind": False, "days": None, "is_urgent": False, "alert_message": "", "header_banner": ""}

    cfg = {}
    cfg_file = (repo_dir or Path(__file__).parent) / "config.yaml"
    if cfg_file.exists():
        try:
            import yaml
            cfg = yaml.safe_load(cfg_file.read_text()) or {}
        except Exception:
            pass
    inactivity_cfg = cfg.get("telegram", {}).get("commit_inactivity", {})
    interval_days = inactivity_cfg.get("interval_days", 20)
    urgent_after_days = inactivity_cfg.get("urgent_after_days", 52)
    cutoff_days = inactivity_cfg.get("github_limit_days", 60)

    is_urgent = days >= urgent_after_days
    # Trigger: every interval_days (e.g. 20, 40) OR every day from day 52 onwards
    is_due = is_urgent or (days > 0 and days % interval_days == 0)

    # Avoid duplicate alert delivery on the same calendar day unless forced
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    state = {}
    if REMINDER_STATE_FILE.exists():
        try:
            state = json.loads(REMINDER_STATE_FILE.read_text())
        except Exception:
            pass

    last_notified_date = state.get("last_notified_date")
    last_notified_days = state.get("last_notified_days")

    if not force and is_due and last_notified_date == today_str and last_notified_days == days:
        is_due = False

    days_left = max(0, cutoff_days - days)

    if is_urgent:
        header_banner = f"🚨 URGENT: It has been {days} days since your last commit! GitHub Actions cron disables at 60 days ({days_left}d left). Push a commit today!"
        alert_message = (
            f"🚨 **URGENT: GitHub Actions Cron Inactivity Alert**\n\n"
            f"⚠️ It has been **{days} days** since your last repository commit!\n\n"
            f"GitHub automatically disables scheduled Actions workflows after **{cutoff_days} days** of inactivity. "
            f"You have **{days_left} day{'s' if days_left != 1 else ''}** remaining before the daily research & post pipeline is stopped.\n\n"
            f"👉 **Action required:** Please make and push any commit to your repository to keep the automated post generator running."
        )
    else:
        header_banner = f"🔔 Maintenance Reminder: {days} days since last commit (GitHub disables Actions cron at 60 days). Push a commit to keep cron active."
        alert_message = (
            f"🔔 **GitHub Actions Maintenance Reminder**\n\n"
            f"It has been **{days} days** since your last repository commit!\n\n"
            f"GitHub automatically disables scheduled Actions workflows after **{cutoff_days} days** of inactivity. "
            f"You have **{days_left} days** remaining before the daily research & post pipeline is paused.\n\n"
            f"💡 **Tip:** Push a small commit or update to your repository to reset GitHub's 60-day inactivity timer."
        )

    return {
        "should_remind": is_due or force,
        "days": days,
        "is_urgent": is_urgent,
        "alert_message": alert_message,
        "header_banner": header_banner
    }


def record_commit_reminder_sent(days: int):
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        REMINDER_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        REMINDER_STATE_FILE.write_text(json.dumps({
            "last_notified_date": today_str,
            "last_notified_days": days,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }, indent=2))
    except Exception as e:
        print(f"[Commit Reminder] Could not persist reminder state: {e}")


class TelegramReviewer:
    """Client for managing human editorial reviews and conversational bot interactions via Telegram."""
    
    def __init__(self, token: str, chat_id: str, timeout_s: int = 3 * 3600,
                 remind_every_s: int = 20 * 60):
        self.token = token
        self.chat_id = str(chat_id)
        self.timeout_s = timeout_s          # Max seconds to wait for owner approval (default 3 hours)
        self.remind_every_s = remind_every_s  # Reminder frequency (default 20 minutes)
        self.offset = None                  # Telegram update_id offset for long polling

    def _call(self, method: str, files=None, **params):
        """Execute a raw HTTP request to Telegram's Bot API with error handling."""
        url = API.format(token=self.token, method=method)
        if files:
            # Multipart form-data for media file uploads (photos, animations)
            r = requests.post(url, data=params, files=files, timeout=70)
        else:
            # Standard JSON payload for text messages and inline markup
            r = requests.post(url, json=params, timeout=70)
        body = r.json()
        if not body.get("ok"):
            raise RuntimeError(f"Telegram {method} failed: {body}")
        return body["result"]

    @staticmethod
    def _buttons(*rows):
        """Construct a Telegram InlineKeyboardMarkup structure from rows of (label, callback_data) tuples."""
        return {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in row] for row in rows]}

    def _set_button(self, message_id: int, text: str, draft_id: str):
        """Replace active buttons with an inert 'noop' button to prevent duplicate clicks."""
        try:
            self._call("editMessageReplyMarkup", chat_id=self.chat_id, message_id=message_id,
                       reply_markup=self._buttons([(text, f"noop:{draft_id}")]))
        except Exception:
            pass

    def _answer_cq(self, cq_id: str, text: str):
        """Acknowledge a Telegram callback query with a toast notification to dismiss loading spinners."""
        try:
            self._call("answerCallbackQuery", callback_query_id=cq_id, text=text)
        except Exception:
            pass

    def _skip_old_updates(self):
        """Advance polling offset to ignore messages and button taps sent before the current action."""
        ups = self._call("getUpdates", offset=-1, timeout=0)
        self.offset = ups[-1]["update_id"] + 1 if ups else None

    # ---------------------------------------------------------- public API
    def download_photo(self, photo_list: list, dest_path: Path) -> Path:
        """Download the highest resolution image attachment from a Telegram message to disk."""
        if not photo_list:
            raise ValueError("No photo found in message.")
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        # Telegram lists photo resolutions in ascending order; [-1] is always highest quality
        file_id = photo_list[-1]["file_id"]
        res = self._call("getFile", file_id=file_id)
        file_path = res["file_path"]
        download_url = f"https://api.telegram.org/file/bot{self.token}/{file_path}"
        r = requests.get(download_url, timeout=60)
        r.raise_for_status()
        dest_path.write_bytes(r.content)
        return dest_path

    def send_progress_tracker(self, title: str) -> int:
        """Send an in-place progress tracker message that will be updated throughout pipeline execution."""
        msg = self._call("sendMessage", chat_id=self.chat_id, text=f"⏳ **{title}**\n\n🔄 Starting pipeline...")
        return msg["message_id"]

    def update_progress(self, message_id: int, step_text: str):
        """Update the existing progress tracker message text in real time."""
        try:
            self._call("editMessageText", chat_id=self.chat_id, message_id=message_id,
                       text=step_text)
        except Exception:
            pass

    def _send_review_text(self, text: str, draft_id: str) -> int:
        """Send draft text, splitting into 4000-character chunks to adhere to Telegram's 4096 limit.
        
        Places the interactive [✅ Approve & Post] and [❌ Reject] buttons on the final message chunk.
        """
        chunks = [text[i:i + 4000] for i in range(0, len(text), 4000)] or [""]
        for chunk in chunks[:-1]:
            self._call("sendMessage", chat_id=self.chat_id, text=chunk)
        msg = self._call(
            "sendMessage", chat_id=self.chat_id, text=chunks[-1],
            reply_markup=self._buttons([("✅ Approve & Post", f"approve:{draft_id}"),
                                        ("❌ Reject", f"reject:{draft_id}")]))
        return msg["message_id"]

    def _notify_commit_inactivity_if_due(self) -> str | None:
        """Sends an inactivity warning message if due and returns a header banner string (or None)."""
        info = check_commit_reminder()
        if info.get("should_remind") and info.get("alert_message"):
            try:
                self._call("sendMessage", chat_id=self.chat_id, text=info["alert_message"])
                if info.get("days") is not None:
                    record_commit_reminder_sent(info["days"])
            except Exception as e:
                print(f"[Commit Reminder] Could not send Telegram alert: {e}")
            return info.get("header_banner")
        return None

    def send_draft(self, draft_id: str, topic: str, post: str, image_path: Path) -> int:
        """Deliver full draft package to Telegram: media infographic + full text with review buttons."""
        self._skip_old_updates()
        banner = self._notify_commit_inactivity_if_due()
        is_gif = image_path.suffix.lower() == ".gif"
        caption = f"✨ Animated Infographic for review\n🆔 {draft_id}" if is_gif else f"🖼️ Infographic for today's draft\n🆔 {draft_id}"
        with open(image_path, "rb") as f:
            if is_gif:
                self._call("sendAnimation", chat_id=self.chat_id,
                           caption=caption,
                           files={"animation": f})
            else:
                self._call("sendPhoto", chat_id=self.chat_id,
                           caption=caption,
                           files={"photo": f})
                           
        # Send full post text with review buttons attached
        header = f"{banner}\n\n" if banner else ""
        text = (f"{header}📝 New LinkedIn draft for review\n📌 Topic: {topic}\n"
                f"📏 {len(post)} characters\n🆔 {draft_id}\n\n{post}")
        message_id = self._send_review_text(text, draft_id)
        set_status(draft_id, "pending", topic=topic, message_id=message_id)
        return message_id

    def send_text_draft(self, draft_id: str, topic: str, post: str) -> int:
        """Deliver a text-only draft to Telegram with review buttons attached."""
        self._skip_old_updates()
        banner = self._notify_commit_inactivity_if_due()
        header = f"{banner}\n\n" if banner else ""
        text = (f"{header}📝 LinkedIn Direct Draft (Text Only)\n📌 {topic}\n"
                f"📏 {len(post)} characters\n🆔 {draft_id}\n\n{post}")
        message_id = self._send_review_text(text, draft_id)
        set_status(draft_id, "pending", topic=topic, message_id=message_id)
        return message_id

    def prompt_direct_choice(self, text: str, timeout_s: int = 300) -> str:
        """Prompt user whether to auto-design an infographic or publish text-only for direct posts."""
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
                # Verify sender authorization
                if (str(cq.get("from", {}).get("id")) != self.chat_id
                        or str(cq.get("message", {}).get("chat", {}).get("id")) != self.chat_id):
                    self._answer_cq(cq["id"], text="Not authorised.")
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
        """Poll Telegram for the user's decision on a pending draft.
        
        Returns one of:
        - {'action': 'approved'}
        - {'action': 'revise', 'feedback': '...'}
        - {'action': 'suggest_topics'}
        - {'action': 'new_topic', 'topic': '...', 'source': '...'}
        - {'action': 'rejected'}
        - {'action': 'expired'}
        """
        start = time.time()
        next_ping = start + self.remind_every_s
        awaiting_feedback = False

        while True:
            now = time.time()
            # 1. Check expiration
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

            # 2. Check periodic reminder interval
            if now >= next_ping and not awaiting_feedback:
                left = int((self.timeout_s - (now - start)) // 60)
                try:
                    self._call("sendMessage", chat_id=self.chat_id, reply_to_message_id=message_id,
                               text=f"⏰ Reminder: today's LinkedIn draft is waiting for you. "
                                    f"Tap Approve or Reject above ({left} min left).")
                except Exception:
                    pass
                next_ping += self.remind_every_s

            # 3. Poll Telegram for incoming actions or messages
            wait = int(max(1, min(40, next_ping - time.time(), self.timeout_s - (time.time() - start))))
            params = {"timeout": wait, "allowed_updates": ["callback_query", "message"]}
            if self.offset is not None:
                params["offset"] = self.offset

            for up in self._call("getUpdates", **params):
                self.offset = up["update_id"] + 1

                # Handle text messages (corrections, feedback, or /topic switches)
                msg = up.get("message")
                if msg:
                    sender = str(msg.get("from", {}).get("id"))
                    chat = str(msg.get("chat", {}).get("id"))
                    text = (msg.get("text") or "").strip()

                    if sender == self.chat_id and chat == self.chat_id:
                        if text.startswith(("/topic ", "/post ")):
                            custom_topic = text.split(" ", 1)[1].strip()
                            self._call("sendMessage", chat_id=self.chat_id,
                                       text=f"🎯 Understood! Switched to topic:\n'{custom_topic}'\nRegenerating draft...")
                            return {"action": "new_topic", "topic": custom_topic, "source": None}

                        if awaiting_feedback and text:
                            self._call("sendMessage", chat_id=self.chat_id, reply_to_message_id=msg["message_id"],
                                       text=f"✍️ Feedback received:\n\"{text}\"\n\nRegenerating post & infographic...")
                            return {"action": "revise", "feedback": text}

                # Handle inline button callbacks
                cq = up.get("callback_query")
                if not cq:
                    continue

                if (str(cq.get("from", {}).get("id")) != self.chat_id
                        or str(cq.get("message", {}).get("chat", {}).get("id")) != self.chat_id):
                    self._answer_cq(cq["id"], text="Not authorised.")
                    continue

                data = cq.get("data", "")
                action, _, cb_draft = data.partition(":")

                # Inert button clicked
                if action == "noop":
                    self._answer_cq(cq["id"], text="This action is complete.")
                    continue

                # Approved: proceed to publish to Wall and Groups
                if action == "approve" and cb_draft == draft_id:
                    set_status(draft_id, "approved")
                    self._answer_cq(cq["id"], text="🚀 Posting to LinkedIn & groups…")
                    self._set_button(message_id, "⏳ Posting…", draft_id)
                    return {"action": "approved"}

                # Rejected: provide secondary options (Revise, Suggest Topics, Skip)
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
        """Present candidate topic suggestions with interactive buttons and await user selection."""
        if not topic_options:
            return {"action": "none"}

        rows = []
        summary_lines = ["💡 **Pick a topic from allowed domains:**\n"]
        for idx, opt in enumerate(topic_options, 1):
            t = opt.get("topic", "Topic")
            s = opt.get("source", "")
            angle = opt.get("angle", "")
            takeaway = opt.get("technical_takeaway", "")
            evidence_url = opt.get("source_url", "")
            summary_lines.append(
                f"{idx}. {t} ({opt.get('topic_kind', 'topic')})\n"
                f"Angle: {angle[:180]}\n"
                f"Try or check: {takeaway[:220]}\n"
                f"Source: {evidence_url or s}"
            )
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

                # Handle custom topic reply as text
                msg_obj = up.get("message")
                if msg_obj:
                    sender = str(msg_obj.get("from", {}).get("id"))
                    text = (msg_obj.get("text") or "").strip()
                    chat = str(msg_obj.get("chat", {}).get("id"))
                    if sender == self.chat_id and chat == self.chat_id and text:
                        if text.startswith(("/topic ", "/post ")):
                            text = text.split(" ", 1)[1].strip()
                        self._call("sendMessage", chat_id=self.chat_id,
                                   text=f"🎯 Understood! Drafting on:\n'{text}'")
                        return {"action": "new_topic", "topic": text, "source": None}

                # Handle button selections
                cq = up.get("callback_query")
                if not cq:
                    continue

                if (str(cq.get("from", {}).get("id")) != self.chat_id
                        or str(cq.get("message", {}).get("chat", {}).get("id")) != self.chat_id):
                    self._answer_cq(cq["id"], text="Not authorised.")
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

    @staticmethod
    def _main_menu_keyboard():
        """Render a persistent reply keyboard below the chat input for immediate action access."""
        return {
            "keyboard": [
                [{"text": "✍️ Post from Topic"}, {"text": "📝 Direct Post"}],
                [{"text": "💡 Suggest Topics"}, {"text": "🚀 Run Daily Post"}],
                [{"text": "📊 Status & History"}, {"text": "❓ Help & Commands"}]
            ],
            "resize_keyboard": True,
            "is_persistent": True
        }

    def set_bot_commands(self):
        """Register native Telegram bot slash commands so they appear in Telegram's menu button."""
        commands = [
            {"command": "topic", "description": "Research & draft post on a topic"},
            {"command": "direct", "description": "Provide post text directly to publish"},
            {"command": "suggest", "description": "Get 3 fresh topic ideas from allowed sources"},
            {"command": "daily", "description": "Run today's automated post discovery"},
            {"command": "status", "description": "Check recent posts and draft status"},
            {"command": "help", "description": "Show interactive action guide"}
        ]
        try:
            self._call("setMyCommands", commands=commands)
            self._call("setMyCommands", commands=commands, scope={"type": "all_private_chats"})
            if self.chat_id:
                try:
                    self._call("setMyCommands", commands=commands, scope={"type": "chat", "chat_id": int(self.chat_id)})
                except Exception:
                    pass
            return True
        except Exception as e:
            print(f"Warning: could not register setMyCommands: {e}")
            return None

    def listen_for_commands(
        self,
        on_topic_callback,
        on_direct_callback,
        on_daily_callback=None,
        on_suggest_callback=None,
        on_status_callback=None,
        poll_interval_s: int = 5,
    ):
        """Daemon long-polling loop handling incoming Telegram commands, quick buttons, and photos."""
        try:
            self._call("deleteWebhook", drop_pending_updates=False)
        except Exception:
            pass
        self.set_bot_commands()
        print(f"🤖 Listening on Telegram for actions & commands from chat {self.chat_id}...")

        help_text = (
            "🤖 **LinkedIn Agent Action Center**\n\n"
            "Use the quick action buttons below or type commands:\n\n"
            "• **✍️ Post from Topic** (`/topic <topic>`)\n"
            "  Researches topic, writes post, generates infographic, asks for your consent -> posts to Wall & all groups.\n\n"
            "• **📝 Direct Post** (`/direct <text>`)\n"
            "  Provide your own post text. Choose auto-infographic or text-only -> posts to Wall & all groups.\n\n"
            "• **💡 Suggest Topics** (`/suggest`)\n"
            "  Discovers 3 trending topics from allowed domains for you to pick from.\n\n"
            "• **🚀 Run Daily Post** (`/daily`)\n"
            "  Runs today's automatic topic discovery from allowed_domains.\n\n"
            "• **📸 Send Photo with Caption**\n"
            "  Attach any image with a caption to publish both directly.\n\n"
            "• **📊 Status & History** (`/status`)\n"
            "  Inspect recent posts and configuration."
        )
        self._call("sendMessage", chat_id=self.chat_id, text=help_text, reply_markup=self._main_menu_keyboard())

        user_state = None  # Tracks conversation mode: None | "waiting_for_topic" | "waiting_for_direct"

        while True:
            params = {"timeout": 30, "allowed_updates": ["message", "callback_query"]}
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
                cq = up.get("callback_query")
                if cq:
                    print(f"[Telegram] Received callback query: {cq.get('data')}")
                    self._answer_cq(cq["id"], text="Received.")
                    continue
                if not msg:
                    continue

                # Ensure only authorized chat/sender can trigger actions
                sender = str(msg.get("from", {}).get("id"))
                chat = str(msg.get("chat", {}).get("id"))
                if sender != self.chat_id or chat != self.chat_id:
                    print(f"[Telegram] Ignoring message from unauthorized chat: {chat} (sender: {sender})")
                    continue

                text = (msg.get("text") or msg.get("caption") or "").strip()
                photos = msg.get("photo")
                print(f"[Telegram] Received message: '{text}' (photos: {bool(photos)}) | state: {user_state}")

                # 1. Help & Start
                if text in ("/start", "/help", "❓ Help & Commands"):
                    user_state = None
                    self._call("sendMessage", chat_id=self.chat_id, text=help_text, reply_markup=self._main_menu_keyboard())
                    continue

                # 2. Status & History
                if text in ("/status", "📊 Status & History"):
                    user_state = None
                    status_report = on_status_callback() if on_status_callback else "Agent is active and ready."
                    self._call("sendMessage", chat_id=self.chat_id, text=status_report, reply_markup=self._main_menu_keyboard())
                    continue

                # 3. Suggest Topics
                if text in ("/suggest", "💡 Suggest Topics"):
                    user_state = None
                    self._call("sendMessage", chat_id=self.chat_id, text="🔍 Scanning allowed domains for 3 fresh topic ideas...")
                    if on_suggest_callback:
                        try:
                            on_suggest_callback()
                        except Exception as e:
                            self._call("sendMessage", chat_id=self.chat_id, text=f"⚠️ Error: {str(e)[:1000]}")
                    continue

                # 4. Run Daily Discovery Pipeline
                if text in ("/daily", "🚀 Run Daily Post"):
                    user_state = None
                    self._call("sendMessage", chat_id=self.chat_id, text="🚀 Triggering today's automated post discovery from allowed_domains...")
                    if on_daily_callback:
                        try:
                            on_daily_callback()
                        except Exception as e:
                            self._call("sendMessage", chat_id=self.chat_id, text=f"⚠️ Error: {str(e)[:1000]}")
                    continue

                # 5. Prompt for Topic
                if text in ("✍️ Post from Topic", "/topic"):
                    user_state = "waiting_for_topic"
                    self._call("sendMessage", chat_id=self.chat_id,
                               text="✍️ **Post from Topic**\n\nPlease send the topic title, concept, or article link you'd like to post about:")
                    continue

                # 6. Prompt for Direct Post
                if text in ("📝 Direct Post", "/direct", "/publish"):
                    user_state = "waiting_for_direct"
                    self._call("sendMessage", chat_id=self.chat_id,
                               text="📝 **Direct Post**\n\nPlease send your post text (or send a photo with a caption) to publish to your Wall and all groups:")
                    continue

                # 7. Direct Photo Upload with Caption
                if photos:
                    user_state = None
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

                # 8. Handling conversational prompt states
                if user_state == "waiting_for_topic":
                    user_state = None
                    self._call("sendMessage", chat_id=self.chat_id,
                               text=f"🎯 Researching & drafting on topic:\n'{text}'\nI will send the draft + infographic for your approval.")
                    try:
                        on_topic_callback(text)
                    except Exception as e:
                        self._call("sendMessage", chat_id=self.chat_id, text=f"⚠️ Error: {str(e)[:1000]}")
                    continue

                if user_state == "waiting_for_direct":
                    user_state = None
                    choice = self.prompt_direct_choice(text)
                    if choice == "infographic":
                        on_direct_callback(text, custom_image_path=None, generate_infographic=True)
                    elif choice == "text_only":
                        on_direct_callback(text, custom_image_path=None, generate_infographic=False)
                    continue

                # 9. Slash command syntax: /topic <topic text>
                if text.startswith(("/topic ", "/idea ", "/draft ")):
                    topic = text.split(" ", 1)[1].strip()
                    self._call("sendMessage", chat_id=self.chat_id,
                               text=f"🎯 Researching & drafting on topic:\n'{topic}'\nI will send the draft + infographic for your approval.")
                    try:
                        on_topic_callback(topic)
                    except Exception as e:
                        self._call("sendMessage", chat_id=self.chat_id, text=f"⚠️ Error: {str(e)[:1000]}")
                    continue

                # 10. Slash command syntax: /direct <post text>
                if text.startswith(("/direct ", "/publish ")):
                    direct_text = text.split(" ", 1)[1].strip()
                    choice = self.prompt_direct_choice(direct_text)
                    if choice == "infographic":
                        on_direct_callback(direct_text, custom_image_path=None, generate_infographic=True)
                    elif choice == "text_only":
                        on_direct_callback(direct_text, custom_image_path=None, generate_infographic=False)
                    continue

                # 11. Free-form text input heuristic
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
        """Mark draft as successfully published to LinkedIn and update the button to '✅ Posted'."""
        set_status(draft_id, "posted", post_urn=post_urn)
        self._set_button(message_id, "✅ Posted", draft_id)
        link = f"https://www.linkedin.com/feed/update/{post_urn}/" if post_urn else ""
        self._call("sendMessage", chat_id=self.chat_id, reply_to_message_id=message_id,
                   text=f"🎉 Posted to LinkedIn! {link}")

    def mark_failed(self, draft_id: str, message_id: int, error: str):
        """Mark draft as failed and update the button to '⚠️ Post failed'."""
        set_status(draft_id, "failed", error=error[:500])
        self._set_button(message_id, "⚠️ Post failed", draft_id)
        self._call("sendMessage", chat_id=self.chat_id, reply_to_message_id=message_id,
                   text=f"⚠️ Posting failed, nothing went out:\n{error[:3500]}")


# ------------------------------------------------------------- helper CLI
if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
    token = os.environ["TELEGRAM_BOT_TOKEN"]

    # CLI option: Discover Chat ID by reading recent messages
    if "--find-chat-id" in sys.argv:
        ups = requests.get(API.format(token=token, method="getUpdates"), timeout=30).json()["result"]
        chats = {(u.get("message") or {}).get("chat", {}).get("id") for u in ups} - {None}
        print("Chat id(s):", chats or "none yet — send any message to your bot, then run again")
        
    # CLI option: Verify Telegram bot connection with a test ping
    elif "--test" in sys.argv or "--ping" in sys.argv:
        chat_id = os.environ["TELEGRAM_CHAT_ID"]
        reviewer = TelegramReviewer(token, chat_id)
        msg = reviewer._call("sendMessage", chat_id=chat_id, text="🤖 Test ping from LinkedIn Agent bot! Connection verified.")
        print(f"Ping delivered successfully to chat {chat_id}! Message ID: {msg.get('message_id')}")
    elif "--check-commit-reminder" in sys.argv:
        info = check_commit_reminder(force=True)
        print("Commit Inactivity Reminder Check:")
        print(f"  Days since last human commit: {info['days']}")
        print(f"  Should remind: {info['should_remind']}")
        print(f"  Is urgent (>= 52 days): {info['is_urgent']}")
        print(f"  Header banner:\n    {info['header_banner']}")
        print(f"  Alert message:\n{info['alert_message']}")
    elif "--test-reminder" in sys.argv:
        chat_id = os.environ["TELEGRAM_CHAT_ID"]
        reviewer = TelegramReviewer(token, chat_id)
        info = check_commit_reminder(force=True)
        if info.get("alert_message"):
            msg = reviewer._call("sendMessage", chat_id=chat_id, text=f"[TEST SIMULATION]\n\n{info['alert_message']}")
            print(f"Test reminder sent to chat {chat_id}! Message ID: {msg.get('message_id')}")
        else:
            print("No commit history found to simulate reminder.")
