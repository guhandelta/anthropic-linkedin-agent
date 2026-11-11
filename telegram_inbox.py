"""
Telegram inbox check for a bot that has no server.

A scheduled GitHub Actions workflow (inbox-check.yml) runs this every 15 minutes. It reads the
messages sent to the bot since the last check, answers the quick ones (help, status) itself and
starts the posting workflow for a topic, topic suggestions or a pasted post. Nothing has to stay
online between checks, so commands are answered within about 15-30 minutes instead of at once.

The reading and routing are kept separate from the LinkedIn specifics so the same inbox can
serve another Telegram project: give TelegramInbox a token and chat id, and write your own
`plan_*` function that turns updates into replies and one action.

Rules that keep it safe next to a running posting job:
- It never reads Telegram while the posting workflow is running or queued, because that job is
  waiting for your taps (two readers also make Telegram answer 409 Conflict).
- Updates are confirmed (marked read) only after they were handled, and only those it read.
- Messages older than MAX_AGE_S are dropped, so an old message is never acted on by surprise.
- Only the owner's chat (TELEGRAM_CHAT_ID) is obeyed.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import requests

API = "https://api.telegram.org/bot{token}/{method}"
GITHUB_API = "https://api.github.com"
MAX_AGE_S = 3 * 3600          # ignore anything older than this when it is finally read
DIRECT_MIN_CHARS = 80         # plain text at least this long is a pasted post, shorter is a topic
ROOT = Path(__file__).parent

HELP_TEXT = (
    "🤖 LinkedIn Agent (running on GitHub Actions)\n\n"
    "I check this chat every 15 minutes on paper, but GitHub often runs the check hours late, "
    "so a reply can take a while. Once a run starts, I answer at once until it ends.\n\n"
    "• /topic <topic>: research and write a post on your topic\n"
    "• /suggest (or 💡 Suggest Topics, 🚀 Run Daily Post): I offer 3 fresh topics to pick from\n"
    "• /direct <post text>, or paste a post of 80+ characters: publish your own text\n"
    "• /status: recent posts\n\n"
    "Each run asks you to approve the text, then the infographic, before anything is posted."
)
SUGGEST_TEXTS = {"/suggest", "💡 Suggest Topics", "/daily", "🚀 Run Daily Post"}
HELP_TEXTS = {"/start", "/help", "❓ Help & Commands"}
STATUS_TEXTS = {"/status", "📊 Status & History"}
TOPIC_PROMPTS = {"/topic", "✍️ Post from Topic"}
DIRECT_PROMPTS = {"/direct", "/publish", "📝 Direct Post"}


class TelegramInbox:
    """Reads, answers and confirms a bot's pending Telegram updates in one short call."""

    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = str(chat_id)

    def _call(self, method: str, **params):
        r = requests.post(API.format(token=self.token, method=method), json=params, timeout=(5, 30))
        body = r.json()
        if not body.get("ok"):
            raise RuntimeError(f"Telegram {method} failed: {body.get('description')}")
        return body["result"]

    def fetch(self) -> list[dict]:
        """Pending updates, without waiting and without marking them read."""
        return self._call("getUpdates", timeout=0, allowed_updates=["message", "callback_query"])

    def confirm(self, updates: list[dict]) -> None:
        """Mark the given updates read, so neither this check nor a posting run sees them again."""
        if updates:
            self._call("getUpdates", offset=max(u["update_id"] for u in updates) + 1, timeout=0)

    def reply(self, text: str) -> None:
        self._call("sendMessage", chat_id=self.chat_id, text=text)

    def answer_callback(self, callback_id: str, text: str) -> None:
        try:
            self._call("answerCallbackQuery", callback_query_id=callback_id, text=text)
        except Exception:  # noqa: BLE001 - an old button's spinner is not worth failing over
            pass

    def from_owner(self, update: dict) -> bool:
        item = update.get("message") or update.get("callback_query") or {}
        chat = (item.get("chat") or (item.get("message") or {}).get("chat") or {}).get("id")
        return str(item.get("from", {}).get("id")) == self.chat_id and str(chat) == self.chat_id


def _sent_at(update: dict) -> int:
    item = update.get("message") or (update.get("callback_query") or {}).get("message") or {}
    return int(item.get("date") or 0)


def plan_linkedin(updates: list[dict], inbox: TelegramInbox, now: float | None = None) -> dict:
    """Turn the owner's pending updates into replies, callback answers and at most one run.

    Returns {"replies": [...], "callbacks": [(id, text)], "run": None | {"mode": ..., ...}}.
    A run is {"mode": "suggest"}, {"mode": "topic", "topic": ...} or {"mode": "direct", "text": ...}.
    When several messages ask for a run, the latest one wins and the owner is told.
    """
    now = time.time() if now is None else now
    plan = {"replies": [], "callbacks": [], "run": None}
    requests_seen = 0
    awaiting = None  # a "Post from Topic" or "Direct Post" tap waits for the next text
    stale = []       # the owner's messages too old to act on; they get one notice, not silence

    def start(run: dict) -> None:
        nonlocal requests_seen
        requests_seen += 1
        plan["run"] = run

    for up in updates:
        cq = up.get("callback_query")
        if cq and not inbox.from_owner(up):
            plan["callbacks"].append((cq["id"], "Not authorised."))
            continue
        if not inbox.from_owner(up):
            continue
        if cq:
            if cq.get("data") == "retry_last":
                plan["callbacks"].append((cq["id"], "Starting a new run..."))
                start({"mode": "suggest"})
            else:
                plan["callbacks"].append((cq["id"], "That run has ended. Send /help to start a new one."))
            continue
        if now - _sent_at(up) > MAX_AGE_S:
            if up.get("message"):
                stale.append(up["message"])
            continue
        msg = up["message"]
        text = (msg.get("text") or msg.get("caption") or "").strip()
        if msg.get("photo"):
            plan["replies"].append("📸 Photo posts need the Mac bot for now. Paste the post text "
                                   "instead and I'll design an infographic for it.")
            awaiting = None
            continue
        if not text:
            continue
        command, _, rest = text.partition(" ")
        rest = rest.strip()
        if text in HELP_TEXTS:
            plan["replies"].append(HELP_TEXT)
        elif text in STATUS_TEXTS:
            plan["replies"].append(status_text())
        elif text in SUGGEST_TEXTS:
            start({"mode": "suggest"})
        elif text in TOPIC_PROMPTS:
            awaiting = "topic"
            plan["replies"].append("✍️ Send the topic, concept or article link for the post.")
            continue
        elif text in DIRECT_PROMPTS:
            awaiting = "direct"
            plan["replies"].append("📝 Paste the post text you want to publish.")
            continue
        elif command in ("/topic", "/idea", "/draft", "/post") and rest:
            start({"mode": "topic", "topic": rest})
        elif command in ("/direct", "/publish") and rest:
            start({"mode": "direct", "text": rest})
        elif text.startswith("/"):
            plan["replies"].append(f"I don't know {command}. Send /help to see what I can do.")
        elif awaiting == "direct" or (awaiting != "topic" and len(text) >= DIRECT_MIN_CHARS):
            start({"mode": "direct", "text": text})
        else:
            start({"mode": "topic", "topic": text})
        awaiting = None

    if stale:
        plan["replies"].insert(0, stale_notice(stale, now))
    if requests_seen > 1:
        plan["replies"].append("ℹ️ You sent several requests. One run at a time, so I'm starting "
                               "only the latest one.")
    return plan


def _ago(seconds: float) -> str:
    hours = int(seconds // 3600)
    if hours >= 1:
        return f"{hours} hour{'s' if hours != 1 else ''}"
    minutes = max(1, int(seconds // 60))
    return f"{minutes} minute{'s' if minutes != 1 else ''}"


def stale_notice(messages: list[dict], now: float) -> str:
    """One reply for the owner's messages that waited too long, so a late check is never silent."""
    oldest = min(int(m.get("date", now)) for m in messages)
    texts = [(m.get("text") or m.get("caption") or "photo").strip() for m in messages]
    shown = ", ".join(f"'{t[:40]}{'...' if len(t) > 40 else ''}'" for t in texts[:3])
    if len(texts) > 3:
        shown += f" and {len(texts) - 3} more"
    count = "message" if len(texts) == 1 else f"{len(texts)} messages"
    return (f"⏰ Sorry for the silence. GitHub only ran my inbox check now, so your {count} "
            f"({shown}, sent {_ago(now - oldest)} ago) waited too long and I didn't act on "
            f"{'it' if len(texts) == 1 else 'them'}. Nothing was started. "
            "Tap or send it again if you still want it.")


def status_text(log_path: Path | None = None) -> str:
    """The last few posts from posted.json."""
    try:
        log = json.loads((log_path or ROOT / "posted.json").read_text())
    except (OSError, ValueError):
        log = []
    if not log:
        return "📊 No posts recorded yet."
    lines = [f"📊 Posts published: {len(log)}", "", "Recent posts:"]
    for item in reversed(log[-3:]):
        lines.append(f"• {str(item.get('date', ''))[:10]}: {item.get('headline', 'Post')} "
                     f"({item.get('source_domain', '')})")
    return "\n".join(lines)


def describe(run: dict) -> str:
    if run["mode"] == "suggest":
        return "🔍 Starting a run: I'll send you 3 fresh topics to pick from."
    if run["mode"] == "topic":
        return f"🎯 Starting a run on:\n'{run['topic']}'\nYou'll approve the text, then the infographic."
    return f"📝 Starting a run for your post ({len(run['text'])} characters)."


# ------------------------------------------------------------------ GitHub side
def _github(method: str, path: str, **kwargs):
    headers = {"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
               "Accept": "application/vnd.github+json"}
    r = requests.request(method, GITHUB_API + path, headers=headers, timeout=30, **kwargs)
    r.raise_for_status()
    return r.json() if r.content else {}


def posting_run_active(repo: str, workflow: str) -> bool:
    """True while the posting workflow is queued or running: its job owns the Telegram updates."""
    for status in ("in_progress", "queued", "waiting", "pending", "requested"):
        runs = _github("GET", f"/repos/{repo}/actions/workflows/{workflow}/runs",
                       params={"status": status, "per_page": 1})
        if runs.get("total_count"):
            return True
    return False


def start_posting_run(repo: str, workflow: str, ref: str, run: dict) -> None:
    inputs = {"run_mode": "publish", "topic": ""}
    if run["mode"] == "topic":
        inputs["topic"] = run["topic"][:500]
    elif run["mode"] == "direct":
        inputs.update(run_mode="direct", post_text=run["text"])
    _github("POST", f"/repos/{repo}/actions/workflows/{workflow}/dispatches",
            json={"ref": ref, "inputs": inputs})


def main() -> int:
    repo = os.environ["GITHUB_REPOSITORY"]
    workflow = os.environ.get("POSTING_WORKFLOW", "daily-post.yml")
    ref = os.environ.get("POSTING_REF", "main")
    if posting_run_active(repo, workflow):
        print("A posting run is active; it reads Telegram itself. Nothing to do.")
        return 0
    inbox = TelegramInbox(os.environ["TELEGRAM_BOT_TOKEN"], os.environ["TELEGRAM_CHAT_ID"])
    updates = inbox.fetch()
    if not updates:
        print("No new Telegram messages.")
        return 0
    plan = plan_linkedin(updates, inbox)
    for cq_id, text in plan["callbacks"]:
        inbox.answer_callback(cq_id, text)
    for text in plan["replies"]:
        inbox.reply(text)
    failed = False
    if plan["run"]:
        try:
            start_posting_run(repo, workflow, ref, plan["run"])
            inbox.reply(describe(plan["run"]))
            print("Started a posting run:", plan["run"]["mode"])
        except Exception as e:  # noqa: BLE001 - tell the owner, then mark the messages read anyway
            failed = True
            print(f"Could not start the posting run: {e}")
            inbox.reply(f"⚠️ I couldn't start the run on GitHub ({str(e)[:200]}). Please try again.")
    inbox.confirm(updates)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
