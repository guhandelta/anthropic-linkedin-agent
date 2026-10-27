# LinkedIn Post Agent 🤖

Every day it writes a LinkedIn post with a matching infographic, checks the quality itself, asks **you** on Telegram, and posts only after you tap Approve.

```
topics.txt → ✍️ Writer (Claude) → 🧪 code checks → 🖼️ infographic (Pillow)
          → 🔍 AI reviewer (reads text + looks at image) ──rejected──→ rewrite (max 3)
          → 📲 Telegram: [✅ Approve & Post] [❌ Reject]
               ⏰ reminder every 20 min · ⌛ expires after 3 h (nothing posted)
          → ✅ Approve → post to LinkedIn once → button changes to "✅ Posted"
```

**A post goes out only when both gates pass:** the AI reviewer AND your approval.

## Quality gates
- **Code checks:** character range, LinkedIn's 3,000 limit, 3–7 emojis (none side by side), repeated words, garbled characters, markdown leftovers.
- **AI reviewer (each ≥ 4/5):** meaningful, accurate, on-topic, image text legible, image matches post, professional (emojis must fit their sentence).
- **Infographic** is drawn from points written alongside the post, with an emoji icon per point, so the text is always spelled right and matches.

## Approval behaviour
- Each draft has one fixed **draft ID** used by every message, reminder and button, so it is never posted twice.
- On Approve the button becomes **⏳ Posting…**, then **✅ Posted** (inert; extra taps just say "already handled").
- Reject → **❌ Rejected — not posted**. No answer in 3 h → **⌛ Expired — not posted**.
- Only taps from your `TELEGRAM_CHAT_ID` are accepted.
- Draft status is stored in `state/drafts.json`.

## Setup
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### 1. Anthropic
Paste your key into `ANTHROPIC_API_KEY`.

### 2. Telegram
1. Open **@BotFather** → your bot → **API Token**. It looks like `1234567890:AAH…` (number, colon, secret). Put the whole thing in `TELEGRAM_BOT_TOKEN`.
2. Send any message to your bot, then run `python telegram_review.py --find-chat-id` and put the number in `TELEGRAM_CHAT_ID`.

### 3. LinkedIn
1. Create an app at https://www.linkedin.com/developers/apps (it asks for a LinkedIn Page; any page you admin works).
2. **Products** tab: add **Sign In with LinkedIn using OpenID Connect** and **Share on LinkedIn**.
3. **Auth** tab: add redirect URL `http://localhost:8765/callback`; copy Client ID and Client Secret into `.env`.
4. Run `python linkedin_auth.py`, sign in, click **Allow**. The token is saved to `.env`.
5. Tokens last ~60 days; rerun step 4 to renew.

### 4. Try it
```bash
python agent.py --dry-run      # writes + reviews, saves to output/, sends nothing
python agent.py                # full run: Telegram approval, then LinkedIn
python agent.py --topic "..."  # one-off topic
```

## Run daily
**GitHub Actions (recommended):** push to a **private** repo, add secrets `ANTHROPIC_API_KEY`, `LINKEDIN_ACCESS_TOKEN`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`. The workflow runs at 9:17 AM ET and can wait the full 3 hours.

**Or on your Mac:** `crontab -e` → `17 9 * * * cd "/Users/guhaprasaanth/Projects/Anthropic LinkedIn Agent" && .venv/bin/python agent.py >> agent.log 2>&1` (the Mac must be awake).

## Files
| File | Purpose |
| --- | --- |
| `agent.py` | Pipeline: topic → write → check → render → review → Telegram → post |
| `infographic.py` | Draws the 1080×1350 infographic |
| `telegram_review.py` | Approval buttons, reminders, timeout, draft state |
| `linkedin.py` | Image upload + post via LinkedIn REST API |
| `linkedin_auth.py` | One-time LinkedIn login → token in `.env` |
| `config.yaml` | Voice, character/emoji limits, review thresholds, timings, colours |
| `topics.txt` | Your topic queue, one per line |
