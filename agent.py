"""
LinkedIn Post Agent
-------------------
Daily pipeline:
  1. Pick the next unused topic from topics.txt
  2. WRITER  : Claude drafts the post (within the character limit) + an infographic spec (JSON)
  3. RENDER  : Pillow draws the infographic PNG from the spec (crisp, no garbled AI text)
  4. REVIEWER: a separate Claude call checks the post text AND looks at the rendered image
               -> meaningful? accurate? no gibberish? image matches the post?
  5. If rejected: feed the reviewer's notes back to the writer and retry (max N times)
  6. If approved: upload the image + publish the post on LinkedIn, log it in posted.json

Run:  python agent.py              (full run, posts to LinkedIn)
      python agent.py --dry-run    (generates + reviews, saves to output/, does NOT post)
      python agent.py --topic "..."  (override the topic queue)
"""
import argparse
import base64
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import yaml

EMOJI_RE = re.compile(r"[\u2600-\u27BF\U0001F300-\U0001FAFF]")
from anthropic import Anthropic
from dotenv import load_dotenv

from infographic import render_infographic
from linkedin import LinkedInClient

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")
CFG = yaml.safe_load((ROOT / "config.yaml").read_text())
client = Anthropic()


# ---------------------------------------------------------------- topics
def next_topic() -> str | None:
    topics = [t.strip() for t in (ROOT / "topics.txt").read_text().splitlines()
              if t.strip() and not t.startswith("#")]
    posted = load_log()
    done = {p["topic"] for p in posted}
    for t in topics:
        if t not in done:
            return t
    return None


def load_log() -> list:
    p = ROOT / "posted.json"
    return json.loads(p.read_text()) if p.exists() else []


def append_log(entry: dict):
    log = load_log()
    log.append(entry)
    (ROOT / "posted.json").write_text(json.dumps(log, indent=2, ensure_ascii=False))


# ---------------------------------------------------------------- helpers
def ask_json(system: str, content, max_tokens=2000) -> dict:
    resp = client.messages.create(
        model=CFG["model"], max_tokens=max_tokens, system=system,
        messages=[{"role": "user", "content": content}],
    )
    text = "".join(b.text for b in resp.content if b.type == "text")
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ValueError(f"Model did not return JSON:\n{text}")
    return json.loads(match.group(0))


# ---------------------------------------------------------------- writer
WRITER_SYSTEM = """You are a LinkedIn ghostwriter for {author}, {author_role}.
Voice: {voice}

Write ONE LinkedIn post about the given topic and design a matching infographic.

Post rules:
- Between {min_chars} and {max_chars} characters total (count carefully, including hashtags).
- Strong first line hook (it shows before "...see more").
- Short paragraphs, concrete facts and practical takeaways. No filler, no buzzword soup,
  no invented statistics, quotes or sources. If you are not sure a fact is true, leave it out.
- End with a question or call to discussion, then {hashtag_count} relevant hashtags.
- Use {min_emoji} to {max_emoji} meaningful emojis, sprinkled sporadically (never two in a row,
  at most one per paragraph). Each must fit its sentence, e.g. 🚀 hook, 💡 insight, ⚙️ how-to,
  ✅ takeaway, ⚠️ pitfall, 👉 call to action, 🤔 question. Never decorative filler.

Infographic rules:
- It must summarise the SAME key points the post makes, in the same order.
- title <= 60 chars, subtitle <= 90 chars, 3 to 5 points.
- Each point: heading <= 32 chars, detail <= 90 chars. Plain words, no markdown.
- takeaway <= 80 chars.
- Each point gets one "icon": a single emoji that matches that point.

Return ONLY JSON:
{{"post": "...",
  "infographic": {{"title": "...", "subtitle": "...",
                  "points": [{{"icon": "💡", "heading": "...", "detail": "..."}}],
                  "takeaway": "..."}}}}"""


def write_draft(topic: str, feedback: str | None) -> dict:
    a = CFG["author"]
    system = WRITER_SYSTEM.format(
        author=a["name"], author_role=a["role"], voice=a["voice"],
        min_chars=CFG["post"]["min_chars"], max_chars=CFG["post"]["max_chars"],
        hashtag_count=CFG["post"]["hashtags"],
        min_emoji=CFG["post"]["min_emojis"], max_emoji=CFG["post"]["max_emojis"],
    )
    msg = f"Topic: {topic}"
    if feedback:
        msg += f"\n\nYour previous draft was REJECTED by the editor. Fix these issues:\n{feedback}"
    return ask_json(system, msg)


# ---------------------------------------------------------------- reviewer
REVIEWER_SYSTEM = """You are a strict senior editor and fact-checker for LinkedIn content.
You receive a post and the rendered infographic image meant to accompany it.

Check ALL of these and be strict:
1. meaningful   - every sentence says something real and useful; no gibberish, filler,
                  repetition, broken grammar, or nonsense words.
2. accurate     - no false, invented or unverifiable claims, statistics, or quotes.
3. on_topic     - the post is clearly about the given topic.
4. image_text   - all text in the image is legible, correctly spelled, not cut off or overlapping.
5. image_match  - the infographic summarises the SAME points as the post (no unrelated content).
6. professional - appropriate for a professional audience; every emoji/icon fits its
                  sentence or point (no random or excessive emojis).

Score each 1-5. Approve only if every score >= {min_score}.
Return ONLY JSON:
{{"scores": {{"meaningful": n, "accurate": n, "on_topic": n,
             "image_text": n, "image_match": n, "professional": n}},
  "approved": true/false,
  "issues": ["specific, actionable problem", ...]}}"""


def review(topic: str, post: str, image_path: Path) -> dict:
    img_b64 = base64.standard_b64encode(image_path.read_bytes()).decode()
    content = [
        {"type": "text", "text": f"Topic: {topic}\n\nPOST:\n{post}\n\nThe infographic image follows."},
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": img_b64}},
    ]
    result = ask_json(REVIEWER_SYSTEM.format(min_score=CFG["review"]["min_score"]), content)
    # Never trust the model's own "approved" alone: enforce the threshold in code
    min_score = CFG["review"]["min_score"]
    result["approved"] = bool(result.get("approved")) and all(
        int(v) >= min_score for v in result["scores"].values())
    return result


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
    if re.search(r"[\u2600-\u27BF\U0001F300-\U0001FAFF]\uFE0F?\s*[\u2600-\u27BF\U0001F300-\U0001FAFF]", post):
        issues.append("Do not put emojis next to each other; spread them out.")
    if re.search(r"[^\x00-\x7F\u00C0-\u024F\u2010-\u2027\u2190-\u21FF\u2600-\u27BF\uFE0F\u200D\U0001F300-\U0001FAFF]{4,}", post):
        issues.append("Unexpected character sequences (possible garbled text).")
    if "{" in post or "}" in post or "**" in post:
        issues.append("Remove JSON/markdown artifacts from the post.")
    return issues


# ---------------------------------------------------------------- main
def run(topic: str | None, dry_run: bool):
    topic = topic or next_topic()
    if not topic:
        print("No unused topics left in topics.txt. Add more topics.")
        sys.exit(0)
    print(f"Topic: {topic}")

    out_dir = ROOT / "output" / datetime.now().strftime("%Y-%m-%d_%H%M")
    out_dir.mkdir(parents=True, exist_ok=True)

    feedback = None
    for attempt in range(1, CFG["review"]["max_attempts"] + 1):
        print(f"\n--- Attempt {attempt} ---")
        draft = write_draft(topic, feedback)
        post, spec = draft["post"].strip(), draft["infographic"]

        issues = hard_checks(post)
        if issues:
            print("Hard checks failed:", issues)
            feedback = "\n".join(issues)
            continue

        image_path = out_dir / f"infographic_{attempt}.png"
        render_infographic(spec, image_path, CFG["infographic"])

        verdict = review(topic, post, image_path)
        print("Scores:", verdict["scores"])
        if verdict["approved"]:
            (out_dir / "post.txt").write_text(post)
            (out_dir / "review.json").write_text(json.dumps(verdict, indent=2))
            print(f"\nAPPROVED ({len(post)} chars). Saved to {out_dir}")
            if dry_run:
                print("Dry run: not posting.\n\n" + post)
                return
            li = LinkedInClient(os.environ["LINKEDIN_ACCESS_TOKEN"], CFG["linkedin"]["api_version"])
            post_urn = li.post_with_image(post, image_path, alt_text=spec["title"])
            print("Posted:", post_urn)
            append_log({"date": datetime.now().isoformat(timespec="seconds"),
                        "topic": topic, "post_urn": post_urn, "chars": len(post)})
            return
        feedback = "\n".join(verdict.get("issues", [])) or "Improve quality and image match."
        print("Rejected:", feedback)

    print("\nAll attempts rejected. Nothing was posted (quality gate held).")
    sys.exit(1)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    run(args.topic, args.dry_run)
