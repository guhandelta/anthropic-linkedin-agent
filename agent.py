"""
LinkedIn Post Agent
-------------------
Daily pipeline:
  1. Pick a random theme from topics.txt (skipping themes posted recently)
  2. RESEARCH + WRITE: Claude searches the allowed sources for one fresh item and drafts
     the post, the infographic spec and the sources it relied on
  3. CHECK (code): length, emojis, garbled text, allowed domains, source dates, not already posted
  4. RENDER: Pillow draws the infographic PNG from the spec
  5. REVIEW: several independent editorial/visual reviews plus one fact-check against the
     sources. All must pass, otherwise the writer retries with the reviewers' notes
  6. TELEGRAM: you approve or reject. Approve -> post once to LinkedIn, sources as first comment

Run:  python agent.py                  (full run, asks you on Telegram, posts if approved)
      python agent.py --dry-run        (research, write and review; saves to output/, sends nothing)
      python agent.py --topic "..."    (use this theme instead of picking one)
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import random
import re
import sys
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

import yaml
from anthropic import Anthropic
from dotenv import load_dotenv

from infographic import render_infographic
from linkedin import LinkedInClient
from telegram_review import TelegramReviewer, get_status

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")
CFG = yaml.safe_load((ROOT / "config.yaml").read_text())
RS = CFG["research"]
client = Anthropic()

EMOJI_RE = re.compile(r"[☀-➿\U0001F300-\U0001FAFF]")

# Clean allowlist: drop inline "# comments" and URL paths, remove duplicates
ALLOWED = sorted({
    d.split("#")[0].strip().split("/")[0].lower()
    for d in RS["allowed_domains"]
    if d.split("#")[0].strip()
})


def domain_allowed(url: str) -> bool:
    host = urlparse(url).netloc.lower().removeprefix("www.")
    return any(host == d or host.endswith("." + d) for d in ALLOWED)


# ---------------------------------------------------------------- themes + log
def load_themes() -> list[str]:
    return [t.strip() for t in (ROOT / "topics.txt").read_text().splitlines()
            if t.strip() and not t.strip().startswith("#")]


def load_log() -> list:
    p = ROOT / "posted.json"
    return json.loads(p.read_text()) if p.exists() else []


def append_log(entry: dict):
    log = load_log()
    log.append(entry)
    (ROOT / "posted.json").write_text(json.dumps(log, indent=2, ensure_ascii=False))


def pick_theme(log: list) -> str | None:
    cutoff = date.today() - timedelta(days=RS["skip_recent_days"])
    recent = {p.get("theme") for p in log if date.fromisoformat(p["date"][:10]) >= cutoff}
    options = [t for t in load_themes() if t not in recent]
    return random.choice(options) if options else None


def posted_urls(log: list) -> set[str]:
    return {s.get("url") for p in log for s in p.get("sources", [])}


# ---------------------------------------------------------------- model calls
def web_tools(max_uses: int = 5) -> list:
    return [{"type": RS.get("search_tool", "web_search_20250305"), "name": "web_search",
             "max_uses": max_uses, "allowed_domains": ALLOWED}]


def call_json(system: str, content, tools: list | None = None, max_tokens: int = 4000) -> dict:
    """Ask Claude for JSON. Resumes automatically if a server-side web search pauses the turn."""
    messages = [{"role": "user", "content": content}]
    for _ in range(6):
        kwargs = {"model": CFG["model"], "max_tokens": max_tokens,
                  "system": system, "messages": messages}
        if tools:
            kwargs["tools"] = tools
        resp = client.messages.create(**kwargs)
        if resp.stop_reason == "max_tokens":
            raise ValueError("Model output was cut off. Increase max_tokens.")
        if resp.stop_reason == "pause_turn":
            messages.append({"role": "assistant", "content": resp.content})
            continue
        text = "".join(b.text for b in resp.content if b.type == "text")
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            raise ValueError(f"Model did not return JSON:\n{text}")
        return json.loads(match.group(0))
    raise ValueError("Research did not finish after several search rounds.")


# ---------------------------------------------------------------- writer (research + write)
WRITER_SYSTEM = """You are a LinkedIn ghostwriter for {author}, {author_role}.
Voice: {voice}

Step 1 - RESEARCH: use the web_search tool to find ONE item on the given theme that was
published in the last {max_age} days. Search only allowed sources. Prefer credible, less-covered
items (release notes, changelogs, security advisories, engineering posts, papers) over headlines.
Do NOT use any of these already-posted URLs: {posted}.
If you cannot find a fresh, credible item, return {{"no_item": true, "reason": "..."}}.

Step 2 - WRITE the post, using ONLY facts stated in the sources you read.

Post rules:
- Between {min_chars} and {max_chars} characters total (count carefully, including hashtags).
- Strong first line hook (it shows before "...see more").
- Name the item and say when it was released, for example "React 19.2 shipped on <date>".
- Short paragraphs, concrete facts and practical takeaways. No filler, no buzzword soup.
- No invented statistics, quotes or claims. If a fact is not in a source, leave it out.
- End with a question or call to discussion, then {hashtag_count} relevant hashtags.
- Use {min_emoji} to {max_emoji} meaningful emojis, sprinkled sporadically (never two in a row,
  at most one per paragraph). Each must fit its sentence, e.g. rocket for hook, bulb for insight,
  check for takeaway, warning for pitfall, pointing hand for call to action, thinking face for question.
  Never decorative filler.

Infographic rules:
- It must summarise the SAME key points the post makes, in the same order.
- title <= 60 chars, subtitle <= 90 chars, 3 to 5 points.
- Each point: icon (one emoji matching the point), heading <= 32 chars, detail <= 90 chars.
- Plain words, no markdown, no emojis in heading or detail.
- takeaway <= 80 chars.

Return ONLY JSON:
{{"post": "...",
  "headline": "short name of the item",
  "sources": [{{"url": "...", "published": "YYYY-MM-DD", "claim": "the fact from this source the post relies on"}}],
  "infographic": {{"title": "...", "subtitle": "...",
                  "points": [{{"icon": "💡", "heading": "...", "detail": "..."}}],
                  "takeaway": "..."}}}}"""


def write_draft(theme: str, feedback: str | None, posted: set[str]) -> dict:
    a = CFG["author"]
    system = WRITER_SYSTEM.format(
        author=a["name"], author_role=a["role"], voice=a["voice"],
        max_age=RS["max_age_days"], posted=", ".join(sorted(posted)) or "none",
        min_chars=CFG["post"]["min_chars"], max_chars=CFG["post"]["max_chars"],
        hashtag_count=CFG["post"]["hashtags"],
        min_emoji=CFG["post"]["min_emojis"], max_emoji=CFG["post"]["max_emojis"],
    )
    msg = f"Theme: {theme}"
    if feedback:
        msg += ("\n\nYour previous draft was REJECTED. Fix these issues. You may research again "
                f"or keep the same item:\n{feedback}")
    return call_json(system, msg, tools=web_tools(), max_tokens=4000)


# ---------------------------------------------------------------- reviewers
REVIEWER_SYSTEM = """You are a strict senior editor for LinkedIn content. You receive the post,
the sources it cites, and the rendered infographic image meant to accompany it.

Check ALL of these:
1. meaningful   - every sentence says something real and useful; no gibberish, filler,
                  repetition, broken grammar or nonsense words.
2. sourced      - every factual claim is supported by a listed source; nothing added beyond them.
3. on_topic     - the post is about the theme and the named item.
4. image_text   - all text in the image is legible, correctly spelled, not cut off or overlapping.
5. image_match  - the infographic summarises the SAME points as the post, nothing unrelated.
6. professional - appropriate for a professional audience; every emoji fits its sentence or point.

Score each 1-5. Approve only if every score >= {min_score}.
Return ONLY JSON:
{{"scores": {{"meaningful": n, "sourced": n, "on_topic": n,
             "image_text": n, "image_match": n, "professional": n}},
  "approved": true/false,
  "issues": ["specific, actionable problem", ...]}}"""

FACT_SYSTEM = """You are a fact-checker. You receive a LinkedIn post and the sources it cites.
Use the web_search tool (allowed sources only) to confirm each factual claim in the post against
the cited sources. Flag anything that is:
- not stated in, or contradicted by, its source
- a number, date, version or name that does not match the source
- a claim with no source at all
Return ONLY JSON:
{"claims_checked": n, "approved": true/false, "issues": ["the claim, and what the source actually says", ...]}"""


def editorial_review(theme: str, post: str, sources: list, image_path: Path) -> dict:
    img = base64.standard_b64encode(image_path.read_bytes()).decode()
    content = [
        {"type": "text", "text": f"Theme: {theme}\n\nPOST:\n{post}\n\n"
                                 f"SOURCES:\n{json.dumps(sources, ensure_ascii=False)}\n\n"
                                 "The infographic image follows."},
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": img}},
    ]
    min_score = CFG["review"]["min_score"]
    result = call_json(REVIEWER_SYSTEM.format(min_score=min_score), content)
    # Never trust the model's own "approved" alone: enforce the threshold in code
    result["approved"] = bool(result.get("approved")) and all(
        int(v) >= min_score for v in result["scores"].values())
    return result


def fact_check(post: str, sources: list) -> dict:
    content = f"POST:\n{post}\n\nSOURCES:\n{json.dumps(sources, ensure_ascii=False)}"
    result = call_json(FACT_SYSTEM, content, tools=web_tools(max_uses=8), max_tokens=3000)
    result["approved"] = bool(result.get("approved"))
    return result


def review_all(theme, post, sources, image_path) -> tuple[bool, list[str], dict]:
    """Several independent editorial reviews plus one fact-check. All must pass."""
    passes = CFG["review"].get("passes", 3)
    approved, issues, scores = True, [], []
    for i in range(1, passes + 1):
        r = editorial_review(theme, post, sources, image_path)
        scores.append(r["scores"])
        if not r["approved"]:
            approved = False
            issues += [f"[review {i}] {x}" for x in r.get("issues", [])]
    fc = fact_check(post, sources)
    if not fc["approved"]:
        approved = False
        issues += [f"[fact-check] {x}" for x in fc.get("issues", [])]
    return approved, issues, {"reviews": scores, "fact_check": fc}


# ---------------------------------------------------------------- code checks
def hard_checks(post: str) -> list[str]:
    """Deterministic checks the LLM can't talk its way around."""
    issues = []
    n = len(post)
    if n > CFG["post"]["max_chars"]:
        issues.append(f"Post is {n} chars; must be <= {CFG['post']['max_chars']}.")
    if n < CFG["post"]["min_chars"]:
        issues.append(f"Post is {n} chars; must be >= {CFG['post']['min_chars']}.")
    if n > 3000:
        issues.append("LinkedIn hard limit is 3000 characters.")
    if re.search(r"(\b\w+\b)(\s+\1\b){2,}", post, re.I):
        issues.append("Repeated words detected.")
    emojis = len(EMOJI_RE.findall(post))
    lo, hi = CFG["post"]["min_emojis"], CFG["post"]["max_emojis"]
    if not lo <= emojis <= hi:
        issues.append(f"Use {lo}-{hi} meaningful emojis spread across the post (found {emojis}).")
    if re.search(r"[☀-➿\U0001F300-\U0001FAFF]️?\s*[☀-➿\U0001F300-\U0001FAFF]", post):
        issues.append("Do not put emojis next to each other; spread them out.")
    if re.search(r"[^\x00-\x7FÀ-ɏ‐-‧←-⇿☀-➿️‍\U0001F300-\U0001FAFF]{4,}", post):
        issues.append("Unexpected character sequences (possible garbled text).")
    if "{" in post or "}" in post or "**" in post:
        issues.append("Remove JSON/markdown artifacts from the post.")
    return issues


def source_checks(sources: list, posted: set[str]) -> list[str]:
    issues = []
    if not sources:
        issues.append("No sources listed. Every fact must cite a source you actually read.")
    cutoff = date.today() - timedelta(days=RS["max_age_days"])
    for s in sources:
        url = s.get("url", "")
        if not domain_allowed(url):
            issues.append(f"Source is not on the allowed list: {url}")
        if url in posted:
            issues.append(f"Already posted before: {url}")
        try:
            if date.fromisoformat(s.get("published", "")) < cutoff:
                issues.append(f"Source is older than {RS['max_age_days']} days: {url}")
        except ValueError:
            issues.append(f"Missing or invalid published date (YYYY-MM-DD) for: {url}")
    return issues


# ---------------------------------------------------------------- approval + publish
def publish_after_approval(theme, post, sources, spec, image_path):
    """Both gates must pass: the AI reviewers (already done) AND you on Telegram."""
    draft_id = datetime.now().strftime("%Y%m%d") + "-" + uuid.uuid4().hex[:8]
    tg = TelegramReviewer(
        os.environ["TELEGRAM_BOT_TOKEN"], os.environ["TELEGRAM_CHAT_ID"],
        timeout_s=CFG["telegram"]["timeout_hours"] * 3600,
        remind_every_s=CFG["telegram"]["remind_every_minutes"] * 60,
    )
    shown = post + "\n\nSources:\n" + "\n".join(f"- {s['url']}" for s in sources)
    message_id = tg.send_draft(draft_id, theme, shown, image_path)
    print(f"Sent draft {draft_id} to Telegram; waiting for your decision...")

    decision = tg.wait_for_decision(draft_id, message_id)
    print("Decision:", decision)
    if decision != "approved" or get_status(draft_id) != "approved":
        return  # rejected or expired: nothing is posted

    try:
        li = LinkedInClient(os.environ["LINKEDIN_ACCESS_TOKEN"], CFG["linkedin"]["api_version"])
        post_urn = li.post_with_image(post, image_path, alt_text=spec["title"])
    except Exception as e:  # noqa: BLE001
        tg.mark_failed(draft_id, message_id, str(e))
        raise
    try:
        li.comment(post_urn, "Sources:\n" + "\n".join(f"- {s['claim']}: {s['url']}" for s in sources))
    except Exception as e:  # noqa: BLE001
        print("Post is live, but the source comment failed:", e)
    tg.mark_posted(draft_id, message_id, post_urn)
    print("Posted:", post_urn)
    append_log({"date": datetime.now().isoformat(timespec="seconds"), "draft_id": draft_id,
                "theme": theme, "topic": spec["title"], "post_urn": post_urn,
                "chars": len(post), "sources": sources})


# ---------------------------------------------------------------- main
def run(theme_arg: str | None, dry_run: bool):
    log = load_log()
    theme = theme_arg or pick_theme(log)
    if not theme:
        print("No theme available today: every theme was used within the skip window, or topics.txt is empty.")
        sys.exit(0)
    print(f"Theme: {theme}")

    out_dir = ROOT / "output" / datetime.now().strftime("%Y-%m-%d_%H%M")
    out_dir.mkdir(parents=True, exist_ok=True)
    posted = posted_urls(log)

    feedback = None
    for attempt in range(1, CFG["review"]["max_attempts"] + 1):
        print(f"\n--- Attempt {attempt} ---")
        draft = write_draft(theme, feedback, posted)
        if draft.get("no_item"):
            print("No fresh item found:", draft.get("reason"))
            feedback = f"Find a fresh item from the allowed sources published in the last {RS['max_age_days']} days."
            continue

        post, spec = draft["post"].strip(), draft["infographic"]
        sources = draft.get("sources", [])
        issues = hard_checks(post) + source_checks(sources, posted)
        if issues:
            print("Checks failed:", issues)
            feedback = "\n".join(issues)
            continue

        image_path = out_dir / f"infographic_{attempt}.png"
        render_infographic(spec, image_path, CFG["infographic"])

        ok, issues, detail = review_all(theme, post, sources, image_path)
        if ok:
            (out_dir / "post.txt").write_text(post + "\n\nSources:\n" + "\n".join(s["url"] for s in sources))
            (out_dir / "review.json").write_text(json.dumps(detail, indent=2, ensure_ascii=False))
            print(f"\nAPPROVED ({len(post)} chars). Saved to {out_dir}")
            if dry_run:
                print("Dry run: not sending to Telegram or LinkedIn.\n\n" + post)
                print("\nSources:\n" + "\n".join(f"- {s['url']}" for s in sources))
                return
            publish_after_approval(theme, post, sources, spec, image_path)
            return
        feedback = "\n".join(issues) or "Improve quality and image match."
        print("Rejected:\n" + feedback)

    print("\nAll attempts rejected. Nothing was posted (quality gate held).")
    sys.exit(1)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    run(args.topic, args.dry_run)
