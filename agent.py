"""
LinkedIn Post Agent
-------------------
Daily pipeline:
  1. Pick one allowed source at random (skipping sources used in the last few days)
  2. RESEARCH + WRITE: Claude browses ONLY that source for one fresh item and drafts the post,
     an infographic idea and the sources it relied on
  3. CHECK (code): length, emojis, garbled text, allowed domains, source dates, not already
     posted. If the source has nothing fresh, the next source is tried
  4. DESIGN + RENDER: a designer call draws the infographic as SVG (any metaphor or scene);
     code checks it for safety and legibility, then renders it to PNG
  5. REVIEW: several independent editorial/visual reviews plus one fact-check against the
     sources. All must pass, otherwise the writer retries with the reviewers' notes
  6. TELEGRAM: you approve or reject. Approve -> post once to LinkedIn, sources as first comment

Run:  python agent.py                  (full run, asks you on Telegram, posts if approved)
      python agent.py --dry-run        (research, write and review; saves to output/, sends nothing)
      python agent.py --source react.dev   (browse this source instead of picking one)
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

from infographic import extract_svg, render_svg, svg_checks
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


# ---------------------------------------------------------------- sources + log
def load_log() -> list:
    p = ROOT / "posted.json"
    return json.loads(p.read_text()) if p.exists() else []


def append_log(entry: dict):
    log = load_log()
    log.append(entry)
    (ROOT / "posted.json").write_text(json.dumps(log, indent=2, ensure_ascii=False))


def pick_source(log: list, exclude: set[str]) -> str | None:
    """A random allowed source, not used for a post in the last few days, not yet tried today."""
    cutoff = date.today() - timedelta(days=RS["skip_recent_days"])
    recent = {p.get("source_domain") for p in log
              if date.fromisoformat(p["date"][:10]) >= cutoff}
    options = [s for s in ALLOWED if s not in recent and s not in exclude]
    return random.choice(options) if options else None


def posted_urls(log: list) -> set[str]:
    return {s.get("url") for p in log for s in p.get("sources", [])}


# ---------------------------------------------------------------- model calls
def web_tools(domains: list[str], max_uses: int = 5) -> list:
    return [{"type": RS.get("search_tool", "web_search_20250305"), "name": "web_search",
             "max_uses": max_uses, "allowed_domains": domains}]


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

Step 1 - BROWSE: use the web_search tool, which is limited to the source {source}, to find ONE
item published in the last {max_age} days: a release, a changelog entry, a bug fix, a security
advisory, a breaking change or a practical guide. Prefer something a working developer would
miss in the headlines. Do NOT use these already-posted URLs: {posted}.
If the source has no fresh, credible item, return {{"no_item": true, "reason": "..."}}.

Step 2 - WRITE the post, using ONLY facts stated in the sources you read.

Post rules:
- Between {min_chars} and {max_chars} characters total, including hashtags.
- Hook in the first line: a surprising fact, a sharp question or a vivid analogy. Never open
  with "Excited to share" or "Big news".
- Explain the item in plain words: what changed, why it matters to a working developer, and one
  concrete example taken from the source (a before/after, a command, a version number).
- If the source gives a watch-out (a breaking change, a known bug, a gotcha), include it.
- Sound like a practitioner: short sentences and, where it fits, a first-person take such as
  "I would check this before upgrading". Label opinions as opinions.
- Short paragraphs. No filler, no buzzwords, no invented statistics or quotes.
- End with a question that invites discussion, then {hashtag_count} relevant hashtags.
- Use {min_emoji} to {max_emoji} meaningful emojis, spread out (never two together, at most one
  per paragraph). Each must fit its sentence. Never decorative filler.

Infographic idea: a creative picture that makes the post easy to understand and remember.
Choose any visual form that fits: a metaphor or scene (a subway map for a pipeline, a kitchen for
a workflow, a bento box for the parts of a system), a timeline, a map, a comparison, a character
or object, a process, a chart. Describe it in "infographic_idea" in 2 to 4 sentences: the central
metaphor or scene, the 3 to 6 points it shows and where each sits in the picture, and the one-line
takeaway. The picture must illustrate the post's points, not decorate them. Everything in it must
come from the post and its sources.

Return ONLY JSON:
{{"post": "...",
  "headline": "short name of the item",
  "sources": [{{"url": "...", "published": "YYYY-MM-DD", "claim": "the fact from this source the post relies on"}}],
  "infographic_idea": "..."}}"""


def write_draft(source: str, feedback: str | None, posted: set[str]) -> dict:
    a = CFG["author"]
    system = WRITER_SYSTEM.format(
        author=a["name"], author_role=a["role"], voice=a["voice"], source=source,
        max_age=RS["max_age_days"], posted=", ".join(sorted(posted)) or "none",
        min_chars=CFG["post"]["min_chars"], max_chars=CFG["post"]["max_chars"],
        hashtag_count=CFG["post"]["hashtags"],
        min_emoji=CFG["post"]["min_emojis"], max_emoji=CFG["post"]["max_emojis"],
    )
    msg = f"Browse {source} and write the post."
    if feedback:
        msg += ("\n\nYour previous draft was REJECTED. Fix these issues. You may research again "
                f"or keep the same item:\n{feedback}")
    return call_json(system, msg, tools=web_tools([source]), max_tokens=8000)


DESIGNER_SYSTEM = """You are an elite visual designer specializing in publication-grade technical infographics for LinkedIn.
You turn a LinkedIn post into a clean, modern, high-contrast infographic drawn as pure SVG. It must look stunning, professional, and visually engaging at a glance on both mobile and desktop feeds.

Visual Style & Aesthetic Principles:
- Premium Elevation: Do not draw plain flat lines or raw unstyled shapes. Use cards with rounded corners (rx="20" to rx="28"), crisp subtle borders (stroke="#E2E8F0" stroke-width="1.5"), and soft drop shadows (<filter id="cardShadow"><feDropShadow dx="0" dy="6" stdDeviation="12" flood-color="#0F172A" flood-opacity="0.06"/></filter>).
- Background: A modern, subtle gradient background (e.g. #F8FAFC to #EEF2F6) rather than stark white.
- Header Hierarchy:
  1. Category pill badge at top (e.g. <rect rx="16" fill="#EFF6FF" stroke="#BFDBFE"/> with bold text #1D4ED8 "DEV RADAR" or "RELEASE BREAKDOWN").
  2. Compelling Main Title (font-size: 52 to 58, font-weight: bold, fill: #0F172A).
  3. Descriptive Subtitle (font-size: 24 to 28, fill: #475569) explaining the core takeaway in plain words.
- Structured Content Architecture:
  * Divide the visual body into clear sections using styled cards (e.g., side-by-side Before vs. After cards, a 3-step pipeline flow, or a feature architecture layout).
  * Draw micro-illustrations using vector shapes: browser window header bars with 3 colored dots (red/amber/green), syntax-styled code cards with dark slate backgrounds (#0F172A), flow arrows with chevron heads, circular status badges with clean checkmarks or alert triangles.
  * Use deliberate semantic accents: Emerald/Green (#10B981 / #059669) for new/improved/safe, Coral/Red (#EF4444 / #DC2626) for old/deprecated/risky, LinkedIn/Electric Blue (#0A66C2 / #2563EB) for active features, Amber (#F59E0B / #D97706) for watch-outs/caveats.
- Callout / Pro-Tip Section:
  * A dedicated bottom card (e.g. with an amber/blue accent bar on the left border) highlighting the practical developer takeaway or watch-out.
- Signature Footer:
  * A neat divider line (#E2E8F0) and footer text "FOOTER_TEXT" in #64748B at the very bottom.

Technical rules (strict):
- One <svg> root with xmlns="http://www.w3.org/2000/svg" and viewBox="0 0 1080 1350" (portrait).
- Supported tags: rect, circle, ellipse, path, line, polyline, polygon, g, text, tspan, defs, linearGradient, radialGradient, clipPath, filter, feDropShadow. No script, foreignObject, image or external links.
- No emoji characters. Draw icons with shapes/paths (e.g. checkmark: <path d="M..."/>).
- Text: font-family="Helvetica, Arial, DejaVu Sans, sans-serif". Minimum font-size 22 for all labels/captions/subtitles, 24-32 for card titles, 52-58 for main title. Never set any font-size below 22.
- Spacing & Padding: Keep at least 60px canvas margin. Ensure text lines have at least 32-36px vertical spacing. Leave at least 30px bottom padding inside cards below the last text line so text never touches or crowds card borders.
- Escape & as &amp; and < as &lt;. Split multi-line text into separate <text> elements with explicit y coordinates.
- Keep the SVG clean, well-structured, and concise (under 400 lines of SVG code) so it generates completely without truncation.
- Every label, metric, and claim must be grounded in the post and its sources.

Return ONLY the SVG, starting with <svg and ending with </svg>. No explanation."""


def design_svg(post: str, idea: str, headline: str, feedback: str | None, footer: str) -> str:
    msg = f"Headline: {headline}\n\nPOST:\n{post}\n\nINFOGRAPHIC IDEA:\n{idea}"
    if feedback:
        msg += f"\n\nYour previous drawing was REJECTED. Fix these issues and redraw it:\n{feedback}"
    resp = client.messages.create(
        model=CFG["model"], max_tokens=12000,
        system=DESIGNER_SYSTEM.replace("FOOTER_TEXT", footer),
        messages=[{"role": "user", "content": msg}],
    )
    if resp.stop_reason == "max_tokens":
        raise ValueError("The drawing was cut off; it must be simpler.")
    text = "".join(b.text for b in resp.content if b.type == "text")
    return extract_svg(text)


# ---------------------------------------------------------------- reviewers
REVIEWER_SYSTEM = """You are a strict senior editor for LinkedIn content. You receive the post,
the sources it cites, and the rendered infographic image meant to accompany it.

Check ALL of these:
1. meaningful   - every sentence says something real and useful; no gibberish, filler,
                  repetition, broken grammar or nonsense words.
2. sourced      - every factual claim is supported by a listed source; nothing added beyond them.
3. on_topic     - the post is about the named item, and it is interesting to a working developer.
4. image_text   - all text in the image is legible, correctly spelled, not cut off or overlapping.
5. image_match  - the picture illustrates the post's main points accurately; its metaphor or scene
                  makes each point easy to grasp; nothing unrelated or misleading in it.
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


def editorial_review(headline: str, post: str, sources: list, image_path: Path) -> dict:
    img = base64.standard_b64encode(image_path.read_bytes()).decode()
    content = [
        {"type": "text", "text": f"Item: {headline}\n\nPOST:\n{post}\n\n"
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
    domains = sorted({urlparse(s.get("url", "")).netloc.removeprefix("www.") for s in sources} & set(ALLOWED))
    result = call_json(FACT_SYSTEM, content, tools=web_tools(domains or ALLOWED, max_uses=8),
                       max_tokens=3000)
    result["approved"] = bool(result.get("approved"))
    return result


def review_all(headline, post, sources, image_path) -> tuple[bool, list[str], dict]:
    """Several independent editorial reviews plus one fact-check. All must pass."""
    passes = CFG["review"].get("passes", 3)
    approved, issues, scores = True, [], []
    for i in range(1, passes + 1):
        r = editorial_review(headline, post, sources, image_path)
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
def publish_after_approval(headline, source, post, sources, image_path):
    """Both gates must pass: the AI reviewers (already done) AND you on Telegram."""
    draft_id = datetime.now().strftime("%Y%m%d") + "-" + uuid.uuid4().hex[:8]
    tg = TelegramReviewer(
        os.environ["TELEGRAM_BOT_TOKEN"], os.environ["TELEGRAM_CHAT_ID"],
        timeout_s=CFG["telegram"]["timeout_hours"] * 3600,
        remind_every_s=CFG["telegram"]["remind_every_minutes"] * 60,
    )
    shown = post + "\n\nSources:\n" + "\n".join(f"- {s['url']}" for s in sources)
    message_id = tg.send_draft(draft_id, headline, shown, image_path)
    print(f"Sent draft {draft_id} to Telegram; waiting for your decision...")

    decision = tg.wait_for_decision(draft_id, message_id)
    print("Decision:", decision)
    if decision != "approved" or get_status(draft_id) != "approved":
        return  # rejected or expired: nothing is posted

    try:
        li = LinkedInClient(os.environ["LINKEDIN_ACCESS_TOKEN"], CFG["linkedin"]["api_version"])
        post_urn = li.post_with_image(post, image_path, alt_text=headline)
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
                "source_domain": source, "headline": headline,
                "post_urn": post_urn, "chars": len(post), "sources": sources})


# ---------------------------------------------------------------- main
def run(source_arg: str | None, dry_run: bool):
    log = load_log()
    posted = posted_urls(log)
    out_dir = ROOT / "output" / datetime.now().strftime("%Y-%m-%d_%H%M")
    out_dir.mkdir(parents=True, exist_ok=True)

    feedback, tried = None, set()
    current_source = source_arg
    for attempt in range(1, CFG["review"]["max_attempts"] + 1):
        if not current_source or not feedback:
            current_source = source_arg or pick_source(log, exclude=tried)
            feedback = None
        if not current_source:
            print("No source available today: all were used recently or already tried.")
            sys.exit(0)
        tried.add(current_source)
        action_verb = "revising draft on" if feedback else "browsing"
        print(f"\n--- Attempt {attempt}: {action_verb} {current_source} ---")

        draft = write_draft(current_source, feedback, posted)
        if draft.get("no_item"):
            print("Nothing fresh on this source:", draft.get("reason"))
            current_source, feedback = None, None
            continue

        post, idea = draft["post"].strip(), draft.get("infographic_idea", "")
        headline = draft.get("headline", current_source)
        sources = draft.get("sources", [])
        issues = hard_checks(post) + source_checks(sources, posted)
        if not idea:
            issues.append("Describe an infographic idea.")
        if issues:
            print("Checks failed:", issues)
            feedback = "\n".join(issues)
            continue

        image_path = out_dir / f"infographic_{attempt}.png"
        design_feedback, drawn = feedback, False
        for _ in range(2):  # the designer gets two tries at a valid drawing
            try:
                svg = design_svg(post, idea, headline, design_feedback, CFG["infographic"]["footer"])
            except ValueError as e:
                design_feedback = f"{e} Make the drawing simpler with fewer lines and paths."
                print("Drawing generation failed:", e)
                continue
            svg_issues = svg_checks(svg)
            if svg_issues:
                design_feedback = "\n".join(svg_issues)
                print("Drawing checks failed:", svg_issues)
                continue
            try:
                render_svg(svg, image_path)
                (out_dir / f"infographic_{attempt}.svg").write_text(svg)
                drawn = True
                break
            except ValueError as e:
                design_feedback = str(e)
                print("Render failed:", e)
        if not drawn:
            feedback = design_feedback
            continue

        ok, issues, detail = review_all(headline, post, sources, image_path)
        if ok:
            (out_dir / "post.txt").write_text(post + "\n\nSources:\n" + "\n".join(s["url"] for s in sources))
            (out_dir / "review.json").write_text(json.dumps(detail, indent=2, ensure_ascii=False))
            print(f"\nAPPROVED ({len(post)} chars). Saved to {out_dir}")
            if dry_run:
                print("Dry run: not sending to Telegram or LinkedIn.\n\n" + post)
                print("\nSources:\n" + "\n".join(f"- {s['url']}" for s in sources))
                return
            publish_after_approval(headline, current_source, post, sources, image_path)
            return
        feedback = "\n".join(issues) or "Improve quality and image match."
        print("Rejected:\n" + feedback)

    print("\nAll attempts rejected. Nothing was posted (quality gate held).")
    sys.exit(1)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", help="browse this allowed domain instead of picking one")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    run(args.source, args.dry_run)
