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
import ast
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
import anthropic
from anthropic import Anthropic
from openai import OpenAI
from dotenv import load_dotenv

from infographic import extract_svg, render_svg, render_svg_to_gif, svg_checks
from linkedin import LinkedInClient
from linkedin_groups import post_to_groups
from telegram_review import TelegramReviewer, get_status

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")
CFG = yaml.safe_load((ROOT / "config.yaml").read_text())
RS = CFG["research"]

# Primary LLM (Claude)
anthropic_client = Anthropic()

# Fallback LLM (OpenAI - supports both OPENAI_API_KEY and OPEN_AI_API_KEY)
openai_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("OPEN_AI_API_KEY")
if openai_key and not os.environ.get("OPENAI_API_KEY"):
    os.environ["OPENAI_API_KEY"] = openai_key
openai_client = OpenAI(api_key=openai_key) if openai_key else None

ACTIVE_LLM_PROVIDER = "anthropic"  # "anthropic" | "openai"

EMOJI_RE = re.compile(r"[☀-➿\U0001F300-\U0001FAFF]")

# Clean sources list: retain subpaths from config.yaml (e.g. react.dev/blog)
SOURCES = [
    d.split("#")[0].strip().removeprefix("https://").removeprefix("http://").rstrip("/")
    for d in RS["allowed_domains"]
    if d.split("#")[0].strip()
]


def domain_for_source(s: str) -> str:
    """Extract clean domain name without paths for Anthropic web_search tool."""
    return s.split("/")[0].lower().removeprefix("www.")


ALLOWED = sorted({domain_for_source(s) for s in SOURCES})


def domain_allowed(url: str) -> bool:
    host = urlparse(url).netloc.lower().removeprefix("www.")
    for d in ALLOWED:
        if host == d or host.endswith("." + d) or d.endswith("." + host):
            return True
    return False


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
    recent_domains = {domain_for_source(s) for s in recent if s}
    options = [
        s for s in SOURCES
        if s not in recent
        and domain_for_source(s) not in recent_domains
        and s not in exclude
    ]
    return random.choice(options) if options else None


def posted_urls(log: list) -> set[str]:
    return {s.get("url") for p in log for s in p.get("sources", [])}


# ---------------------------------------------------------------- model calls
def web_tools(domains: list[str], max_uses: int = 5) -> list:
    return [{"type": RS.get("search_tool", "web_search_20250305"), "name": "web_search",
             "max_uses": max_uses, "allowed_domains": domains}]


def is_claude_limit_error(e: Exception) -> bool:
    """Returns True if the error indicates Claude rate limit, credit exhaustion, or service overload."""
    if isinstance(e, (anthropic.RateLimitError, anthropic.APIStatusError)):
        return True
    err_str = str(e).lower()
    limit_signatures = [
        "rate_limit", "rate limit", "ratelimit", "overloaded",
        "credit balance", "insufficient credits", "exceeded your current quota",
        "exceeded", "quota", "too many requests", "429", "529", "capacity"
    ]
    if any(sig in err_str for sig in limit_signatures):
        return True
    if hasattr(e, "status_code") and getattr(e, "status_code") in (429, 529):
        return True
    return False


def extract_json_object(text: str) -> dict:
    """Robust JSON extractor supporting markdown code fences, embedded JSON objects, and single-quoted dictionaries."""
    def try_parse(s: str) -> dict | None:
        s = s.strip()
        try:
            return json.loads(s)
        except Exception:
            pass
        try:
            # Handle Python dict syntax (single quotes, True/False/None)
            clean_py = s.replace("true", "True").replace("false", "False").replace("null", "None")
            res = ast.literal_eval(clean_py)
            if isinstance(res, dict):
                return res
        except Exception:
            pass
        return None

    # 1. Code blocks ```json ... ```
    for m in re.finditer(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S):
        parsed = try_parse(m.group(1))
        if parsed is not None:
            return parsed

    # 2. Balanced braces extraction
    start = text.find("{")
    while start != -1:
        depth = 0
        in_string = False
        quote_char = None
        escape = False
        for i in range(start, len(text)):
            c = text[i]
            if escape:
                escape = False
                continue
            if c == "\\":
                escape = True
                continue
            if c in ('"', "'"):
                if not in_string:
                    in_string = True
                    quote_char = c
                elif quote_char == c:
                    in_string = False
                    quote_char = None
                continue
            if not in_string:
                if c == '{':
                    depth += 1
                elif c == '}':
                    depth -= 1
                    if depth == 0:
                        parsed = try_parse(text[start:i+1])
                        if parsed is not None:
                            return parsed
                        break
        start = text.find("{", start + 1)

    # 3. Fallback to greedy regex
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        parsed = try_parse(m.group(0))
        if parsed is not None:
            return parsed

    raise ValueError(f"Could not parse valid JSON from model output:\n{text}")


def call_anthropic_json(system: str, content, tools: list | None = None, max_tokens: int = 4000) -> dict:
    """Ask Claude for JSON. Resumes automatically if a server-side web search pauses the turn."""
    messages = [{"role": "user", "content": content}]
    for _ in range(6):
        kwargs = {"model": CFG["model"], "max_tokens": max_tokens,
                  "system": system, "messages": messages}
        if tools:
            kwargs["tools"] = tools
        resp = anthropic_client.messages.create(**kwargs)
        if resp.stop_reason == "max_tokens":
            raise ValueError("Model output was cut off. Increase max_tokens.")
        if resp.stop_reason == "pause_turn":
            messages.append({"role": "assistant", "content": resp.content})
            continue
        text = "".join(b.text for b in resp.content if b.type == "text")
        return extract_json_object(text)
    raise ValueError("Research did not finish after several search rounds.")


def call_openai_json(system: str, content, tools: list | None = None, max_tokens: int = 4000) -> dict:
    """Ask OpenAI (fallback) for JSON. Uses responses API when web search is requested; chat.completions otherwise."""
    if not openai_client:
        raise RuntimeError("Claude limit reached and OpenAI API key is not configured in .env.")
    model_name = CFG.get("openai_fallback_model", "gpt-4o")

    if tools:
        domains = []
        for t in tools:
            if isinstance(t, dict) and "allowed_domains" in t:
                domains.extend(t["allowed_domains"])
        domain_instruction = f"\nAllowed research sources: {', '.join(domains)}. Ground your findings and facts strictly in these sources." if domains else ""
        resp = openai_client.responses.create(
            model=model_name,
            instructions=system + domain_instruction,
            input=content if isinstance(content, str) else json.dumps(content, ensure_ascii=False),
            tools=[{"type": "web_search_preview"}],
        )
        text = resp.output_text
    else:
        messages = [{"role": "system", "content": system}]
        if isinstance(content, list):
            user_parts = []
            for item in content:
                if item.get("type") == "text":
                    user_parts.append({"type": "text", "text": item["text"]})
                elif item.get("type") == "image":
                    b64 = item["source"]["data"]
                    media_type = item["source"].get("media_type", "image/png")
                    user_parts.append({"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{b64}"}})
            messages.append({"role": "user", "content": user_parts})
        else:
            messages.append({"role": "user", "content": str(content)})

        resp = openai_client.chat.completions.create(
            model=model_name,
            messages=messages,
            response_format={"type": "json_object"},
            max_tokens=max_tokens,
        )
        text = resp.choices[0].message.content or ""

    try:
        return extract_json_object(text)
    except Exception:
        # Self-healing fallback: ask model to format output into requested JSON schema
        fmt_resp = openai_client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": "You are a JSON formatting assistant. Convert the text into valid JSON adhering strictly to these instructions:\n" + system},
                {"role": "user", "content": text}
            ],
            response_format={"type": "json_object"},
            max_tokens=max_tokens,
        )
        return extract_json_object(fmt_resp.choices[0].message.content or "")


def call_openai_svg(system: str, msg: str, max_tokens: int = 8000) -> str:
    """Ask OpenAI (fallback) to generate an SVG infographic."""
    if not openai_client:
        raise RuntimeError("Claude limit reached and OpenAI API key is not configured in .env.")
    model_name = CFG.get("openai_fallback_model", "gpt-4o")
    resp = openai_client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": system + "\nCRITICAL SVG RULES:\n- Absolutely NO emoji characters inside SVG text.\n- Do NOT combine lines in one <text> element. Use separate <text y='...'> elements for each line.\n- Keep every <text> element under 65 characters total.\n- Do NOT use HTML entities like &#8211; use plain hyphens or ASCII.\n- Escape raw & as &amp;."},
            {"role": "user", "content": msg}
        ],
        max_tokens=max_tokens,
    )
    text = resp.choices[0].message.content or ""
    return EMOJI_RE.sub("", extract_svg(text))


def call_json(system: str, content, tools: list | None = None, max_tokens: int = 4000) -> dict:
    """Routes JSON generation to Claude, automatically falling back to OpenAI if Claude limit is reached."""
    global ACTIVE_LLM_PROVIDER
    if ACTIVE_LLM_PROVIDER == "anthropic":
        try:
            return call_anthropic_json(system, content, tools=tools, max_tokens=max_tokens)
        except Exception as e:
            if openai_client and is_claude_limit_error(e):
                print(f"\n⚠️ [LLM Fallback] Claude limit reached ({e}). Switching to OpenAI ({CFG.get('openai_fallback_model', 'gpt-4o')})...\n")
                ACTIVE_LLM_PROVIDER = "openai"
            else:
                raise

    return call_openai_json(system, content, tools=tools, max_tokens=max_tokens)


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
- Plain text only: do NOT use markdown bold (**) or italics (*). LinkedIn does not support markdown asterisks.

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


def write_draft(source: str, feedback: str | None, posted: set[str], topic: str | None = None) -> dict:
    a = CFG["author"]
    search_domain = domain_for_source(source)
    if topic:
        system = f"""You are a LinkedIn ghostwriter for {a['name']}, {a['role']}.
Voice: {a['voice']}

Goal: Write an insightful, practical, publication-grade LinkedIn post on the user-requested topic: "{topic}".
Synthesize practical advice, real-world development tips, and best practices for modern developers.
Do NOT return {{"no_item": true}} — produce a high-value post on this topic.

Post rules:
- Between {CFG['post']['min_chars']} and {CFG['post']['max_chars']} characters total, including hashtags.
- Hook in the first line: a sharp question, surprising insight, or vivid analogy. Never open with "Excited to share".
- Concrete technical points: explain why it matters to developers, provide 2-3 key takeaways or design/code principles.
- Sound like a practitioner: clean, concise paragraphs.
- End with a question that invites discussion, then {CFG['post']['hashtags']} relevant hashtags.
- Use {CFG['post']['min_emojis']} to {CFG['post']['max_emojis']} meaningful emojis, well spread out (NEVER place two emojis adjacent to each other).
- Plain text only: do NOT use markdown bold (**) or italics (*).

Infographic idea:
Describe a clean, modern visual layout (such as a comparison, a workflow, or a bento-box design) in "infographic_idea" (2-3 sentences).

Return ONLY JSON:
{{"post": "...",
  "headline": "{topic[:60]}",
  "sources": [{{"url": "https://developer.mozilla.org/en-US/docs/Web", "published": "2024-01-01", "claim": "Industry best practices and guidelines"}}],
  "infographic_idea": "..."}}"""
        msg = f"Research and write the post on '{topic}'."
        tool_domains = [search_domain, "web.dev", "developer.mozilla.org", "react.dev", "nextjs.org", "builder.io"]
    else:
        system = WRITER_SYSTEM.format(
            author=a["name"], author_role=a["role"], voice=a["voice"], source=source,
            max_age=RS["max_age_days"], posted=", ".join(sorted(posted)) or "none",
            min_chars=CFG["post"]["min_chars"], max_chars=CFG["post"]["max_chars"],
            hashtag_count=CFG["post"]["hashtags"],
            min_emoji=CFG["post"]["min_emojis"], max_emoji=CFG["post"]["max_emojis"],
        )
        msg = f"Browse {source} and write the post."
        tool_domains = [search_domain]

    if feedback:
        msg += ("\n\nYour previous draft was REJECTED. Fix these issues. You may research again "
                f"or keep the same item:\n{feedback}")
    return call_json(system, msg, tools=web_tools(list(dict.fromkeys(tool_domains))), max_tokens=8000)


DESIGNER_SYSTEM = """You are an elite visual designer specializing in publication-grade technical infographics for LinkedIn.
You turn complex software engineering concepts and LinkedIn posts into a multi-module, highly informative Bento Grid technical infographic drawn as pure SVG.
The graphic must look sophisticated, dense with genuine technical value, beautifully balanced, and crystal clear on both mobile and desktop screens. It MUST NOT be a trivial, oversimplified icon-and-arrow diagram.

SPATIAL LAYOUT & VERTICAL BUDGETING (Strict Bounding Zones - NO OVERLAPPING):
Total Canvas: viewBox="0 0 1080 1350" (portrait). Keep 60px outer padding (x: 60 to 1020).
You MUST organize the visual content into 5 distinct vertical sections with explicit non-overlapping y-coordinates:

1. ZONE 1: HERO HEADER (y: 40 to 230, height: 190)
   - Category Pill Badge at top: <rect x="60" y="45" width="220" height="36" rx="18" fill="#EFF6FF" stroke="#BFDBFE"/> with text at x="170" y="69" text-anchor="middle" font-size="22" font-weight="bold" fill="#1D4ED8" (e.g. "ARCHITECTURE DEEP DIVE", "SYSTEM DESIGN", "TECH RADAR").
   - Main Title: 2 lines maximum, font-size 46-52, font-weight: bold, fill: #0F172A. First line at y="125", second line at y="175". Maximum 32 characters per line.
   - Descriptive Subtitle: font-size 24, fill: #475569 at y="220". Explains the architectural impact or bottom line in plain English (max 55 characters).

2. ZONE 2: HIGH-DENSITY COMPARATIVE ARCHITECTURE GRID (y: 250 to 670, height: 420)
   - Render TWO structured comparison cards side-by-side:
     * LEFT CARD ("Traditional / Anti-Pattern" or "Before"): x="60", y="250", width="460", height="420", rx="24", fill="#FFFFFF", stroke="#E2E8F0".
       - Header badge: <rect x="85" y="275" width="190" height="36" rx="18" fill="#FEF2F2" stroke="#FECACA"/> with text at x="180" y="300" text-anchor="middle" font-size="22" font-weight="bold" fill="#DC2626" (e.g. "LEGACY PATTERN").
       - Card title at x="85" y="350", font-size="28", font-weight="bold", fill="#0F172A".
       - 3-4 structured bullet items or architectural specs with explicit vertical spacing (y: 395, 450, 505, 560).
       - Metric highlight card at bottom of card (y: 590 to 650) highlighting the bottleneck (e.g., "Latency: 450ms | Memory: High").
     * RIGHT CARD ("Modern Solution / Architecture" or "After"): x="560", y="250", width="460", height="420", rx="24", fill="#FFFFFF", stroke="#BFDBFE" stroke-width="2".
       - Header badge: <rect x="585" y="275" width="210" height="36" rx="18" fill="#ECFDF5" stroke="#A7F3D0"/> with text at x="690" y="300" text-anchor="middle" font-size="22" font-weight="bold" fill="#059669" (e.g. "OPTIMIZED PATTERN").
       - Card title at x="585" y="350", font-size="28", font-weight="bold", fill="#0F172A".
       - 3-4 structured bullet items or specs with explicit vertical spacing (y: 395, 450, 505, 560).
       - Metric highlight card at bottom (y: 590 to 650) highlighting the win (e.g., "Latency: 28ms (-93%) | Zero GC").

3. ZONE 3: EXECUTION PIPELINE / INTERACTIVE DATA FLOW (y: 690 to 1050, height: 360)
   - A full-width technical flow card: x="60", y="690", width="960", height="360", rx="24", fill="#FFFFFF", stroke="#E2E8F0".
   - Section Title at x="90", y="735", font-size="26", font-weight="bold", fill="#0F172A" (e.g. "DATA FLOW & EXECUTION PIPELINE").
   - 3 interconnected pipeline stages placed horizontally:
     * Stage 1 Box: x="90", y="770", width="250", height="240", rx="18", fill="#F8FAFC", stroke="#CBD5E1".
       - Number badge: <circle cx="125" cy="805" r="18" fill="#1E293B"/> with text "1" in white.
       - Title at x="155" y="813" (font-size 22, bold). 3 concise description lines (y: 860, 895, 930).
     * Stage 2 Box (Active Processing): x="415", y="770", width="250", height="240", rx="18", fill="#EFF6FF", stroke="#93C5FD".
       - Number badge: <circle cx="450" cy="805" r="18" fill="#2563EB"/> with text "2" in white.
       - Pulsing Radar Ring: <circle cx="450" cy="805" r="{pulse_r}" fill="none" stroke="#3B82F6" stroke-width="2" opacity="{pulse_op}"/>
       - Title at x="480" y="813" (font-size 22, bold). 3 concise description lines (y: 860, 895, 930).
     * Stage 3 Box: x="740", y="770", width="250", height="240", rx="18", fill="#F8FAFC", stroke="#CBD5E1".
       - Number badge: <circle cx="775" cy="805" r="18" fill="#059669"/> with text "3" in white.
       - Title at x="805" y="813" (font-size 22, bold). 3 concise description lines (y: 860, 895, 930).
   - Animated Motion Connectors (Flow Streams):
     * Connector between Stage 1 and Stage 2: <line x1="340" y1="890" x2="415" y2="890" stroke="#3B82F6" stroke-width="4" stroke-dasharray="10 10"/>
     * Connector between Stage 2 and Stage 3: <line x1="665" y1="890" x2="740" y2="890" stroke="#3B82F6" stroke-width="4" stroke-dasharray="10 10"/>
     * Note: Connector lines with stroke-dasharray="10 10" are AUTOMATICALLY CONVERTED INTO ANIMATED FLOWING STREAMS in the animated GIF!

4. ZONE 4: ARCHITECTURAL PRO-TIP & KEY TAKEAWAY (y: 1070 to 1240, height: 170)
   - Highlight Card: x="60", y="1070", width="960", height="170", rx="24", fill="#FEFCE8", stroke="#FEF08A".
   - Left Accent Bar: <rect x="60" y="1070" width="8" height="170" rx="4" fill="#EAB308"/>.
   - Badge at x="95" y="1110": <rect x="95" y="1090" width="160" height="30" rx="15" fill="#FEF08A"/> with text "PRO-TIP // ADVICE" in #854D0E font-size 22 font-weight bold.
   - 2 impactful takeaway lines at x="95", y="1155" and y="1195" (font-size: 24, font-weight: 500, fill: #713F12, max 65 chars per line).

5. ZONE 5: FOOTER (y: 1260 to 1310)
   - Divider line: <line x1="60" y1="1265" x2="1020" y2="1265" stroke="#E2E8F0" stroke-width="1.5"/>
   - Signature text: <text x="60" y="1298" font-size="22" fill="#64748B">FOOTER_TEXT</text>

CRITICAL SPACING & COLLISION RULES (Never Violate):
- NO TEXT OVERLAPS: Never place two <text> tags at the same or adjacent y-coordinates without separated x bounds.
- LINE LENGTH LIMITS:
  * Half-width cards (width 460): max 34 characters per line.
  * Pipeline boxes (width 250): max 20 characters per line.
  * Full-width cards (width 960): max 65 characters per line.
- LINE SPACING: Always leave at least 32-38px vertical spacing between consecutive text lines.
- CARD PADDING: Keep text at least 25px away from card borders.
- VALID SVG & SAFE TAGS:
  * Only one <svg> root with viewBox="0 0 1080 1350".
  * Supported tags: rect, circle, ellipse, path, line, polyline, polygon, g, text, tspan, defs, linearGradient, radialGradient, clipPath, filter, feDropShadow.
  * NO <script>, <foreignObject>, <img>, or <animate> tags. (Motion is composited via frame generation).
  * NO emoji characters. Draw icons and indicators with shapes or clean paths.
  * Text font-family="Helvetica, Arial, DejaVu Sans, sans-serif". Minimum font-size 22 for all text.
  * Escape & as &amp; and < as &lt;.
- Ground every claim, term, and metric strictly in the provided post content.

Return ONLY the SVG, starting with <svg and ending with </svg>. No markdown explanation, no wrapping code fences."""


def design_svg(post: str, idea: str, headline: str, feedback: str | None, footer: str) -> str:
    global ACTIVE_LLM_PROVIDER
    msg = f"Headline: {headline}\n\nPOST:\n{post}\n\nINFOGRAPHIC IDEA:\n{idea}"
    if feedback:
        msg += f"\n\nYour previous drawing was REJECTED. Fix these issues and redraw it:\n{feedback}"
    sys_prompt = DESIGNER_SYSTEM.replace("FOOTER_TEXT", footer)

    if ACTIVE_LLM_PROVIDER == "anthropic":
        try:
            resp = anthropic_client.messages.create(
                model=CFG["model"], max_tokens=12000,
                system=sys_prompt,
                messages=[{"role": "user", "content": msg}],
            )
            if resp.stop_reason == "max_tokens":
                raise ValueError("The drawing was cut off; it must be simpler.")
            text = "".join(b.text for b in resp.content if b.type == "text")
            return extract_svg(text)
        except Exception as e:
            if openai_client and is_claude_limit_error(e):
                print(f"\n⚠️ [LLM Fallback] Claude limit reached during SVG design ({e}). Switching to OpenAI ({CFG.get('openai_fallback_model', 'gpt-4o')})...\n")
                ACTIVE_LLM_PROVIDER = "openai"
            else:
                raise

    return call_openai_svg(sys_prompt, msg, max_tokens=8000)


# ---------------------------------------------------------------- reviewers
REVIEWER_SYSTEM = """You are a strict senior editor for LinkedIn content. You receive the post,
the sources it cites, and the rendered infographic image meant to accompany it.

Check ALL of these:
1. meaningful   - every sentence says something real and useful; no gibberish, filler,
                  repetition, broken grammar or nonsense words.
2. sourced      - {sourced_rule}
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


def editorial_review(headline: str, post: str, sources: list, image_path: Path, is_custom_topic: bool = False) -> dict:
    img = base64.standard_b64encode(image_path.read_bytes()).decode()
    content = [
        {"type": "text", "text": f"Item: {headline}\n\nPOST:\n{post}\n\n"
                                 f"SOURCES:\n{json.dumps(sources, ensure_ascii=False)}\n\n"
                                 "The infographic image follows."},
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": img}},
    ]
    min_score = CFG["review"]["min_score"]
    sourced_rule = (
        "the post aligns with recognized developer principles and guidelines without inventing fake APIs"
        if is_custom_topic
        else "every factual claim is supported by a listed source; nothing added beyond them"
    )
    result = call_json(REVIEWER_SYSTEM.format(min_score=min_score, sourced_rule=sourced_rule), content)
    # Never trust the model's own "approved" alone: enforce the threshold in code
    result["approved"] = bool(result.get("approved")) and all(
        int(v) >= min_score for v in result["scores"].values())
    return result


def fact_check(post: str, sources: list) -> dict:
    content = f"POST:\n{post}\n\nSOURCES:\n{json.dumps(sources, ensure_ascii=False)}"
    domains = sorted({urlparse(s.get("url", "")).netloc.removeprefix("www.") for s in sources} & set(ALLOWED))
    result = call_json(FACT_SYSTEM, content, tools=web_tools(domains or ALLOWED[:5], max_uses=8),
                       max_tokens=3000)
    result["approved"] = bool(result.get("approved"))
    return result


def review_all(headline, post, sources, image_path, is_custom_topic: bool = False) -> tuple[bool, list[str], dict]:
    """Several independent editorial reviews plus one fact-check. All must pass."""
    passes = 1 if is_custom_topic else CFG["review"].get("passes", 3)
    approved, issues, scores = True, [], []
    for i in range(1, passes + 1):
        r = editorial_review(headline, post, sources, image_path, is_custom_topic=is_custom_topic)
        scores.append(r["scores"])
        if not r["approved"]:
            approved = False
            issues += [f"[review {i}] {x}" for x in r.get("issues", [])]
    fc = fact_check(post, sources)
    if not fc["approved"]:
        if is_custom_topic:
            print(f"[fact-check note on topic]: {fc.get('issues')}")
        else:
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
    if re.search(r"^\s*\{.*\}\s*$", post, re.S) or '{"' in post or '"post":' in post:
        issues.append("Remove raw JSON artifacts from the post text.")
    return issues


def clamp_emojis(post: str, min_e: int = 3, max_e: int = 6) -> str:
    """Ensures emoji count is within LinkedIn guidelines and prevents adjacent emojis."""
    adj_pattern = re.compile(r"[☀-➿\U0001F300-\U0001FAFF]️?\s*[☀-➿\U0001F300-\U0001FAFF]")
    for _ in range(10):
        if not adj_pattern.search(post):
            break
        post = re.sub(r"([☀-➿\U0001F300-\U0001FAFF]️?)\s*[☀-➿\U0001F300-\U0001FAFF]", r"\1", post)

    emojis = list(EMOJI_RE.finditer(post))
    if len(emojis) > max_e:
        chars = list(post)
        for m in emojis[max_e:]:
            for i in range(m.start(), m.end()):
                chars[i] = ""
        post = "".join(chars)
    elif len(emojis) < min_e:
        paragraphs = [p for p in post.split("\n\n") if p.strip()]
        if not paragraphs:
            paragraphs = [post]
        default_emojis = ["💡", "🚀", "📌", "✨", "🎯"]
        needed = min_e - len(emojis)
        for i in range(needed):
            idx = i % len(paragraphs)
            paragraphs[idx] = f"{paragraphs[idx]} {default_emojis[i % len(default_emojis)]}"
        post = "\n\n".join(paragraphs)

    return post


def source_checks(sources: list, posted: set[str], is_custom_topic: bool = False) -> list[str]:
    issues = []
    if not sources:
        issues.append("No sources listed. Every fact must cite a source you actually read.")
    cutoff = date.today() - timedelta(days=RS["max_age_days"])
    for s in sources:
        url = s.get("url", "")
        if not is_custom_topic and not domain_allowed(url):
            issues.append(f"Source is not on the allowed list: {url}")
        if not is_custom_topic and url in posted:
            issues.append(f"Already posted before: {url}")
        if not is_custom_topic:
            try:
                if date.fromisoformat(s.get("published", "")) < cutoff:
                    issues.append(f"Source is older than {RS['max_age_days']} days: {url}")
            except ValueError:
                issues.append(f"Missing or invalid published date (YYYY-MM-DD) for: {url}")
    return issues


# ---------------------------------------------------------------- suggestions & approval
def suggest_topics(count: int = 3) -> list[dict]:
    """Sample candidate topics from random allowed domains for user selection."""
    sampled = random.sample(SOURCES, min(count * 2, len(SOURCES)))
    suggestions = []
    for s in sampled:
        dom = domain_for_source(s)
        try:
            res = call_json(
                system="You are a tech scout. Browse the given source for one recent (past 7 days) release, update, or developer headline.",
                content=f"Find 1 fresh update or headline from {s}. Return JSON: {{\"topic\": \"Concise headline or feature name\", \"source\": \"{s}\"}}",
                tools=web_tools([dom], max_uses=2),
                max_tokens=1000,
            )
            if res.get("topic") and not res.get("no_item"):
                suggestions.append({"topic": res["topic"], "source": s})
                if len(suggestions) >= count:
                    break
        except Exception:
            continue
    return suggestions


def publish_to_linkedin_and_groups(
    post: str,
    image_path: Path | None,
    headline: str,
    sources: list | None = None,
    draft_id: str | None = None,
    message_id: int | None = None,
    tg: TelegramReviewer | None = None,
) -> str:
    """Publishes a post (with or without image) to the LinkedIn personal feed and all configured groups."""
    li = LinkedInClient(os.environ["LINKEDIN_ACCESS_TOKEN"], CFG["linkedin"]["api_version"])
    try:
        if image_path and Path(image_path).exists():
            post_urn = li.post_with_image(post, Path(image_path), alt_text=headline)
        else:
            post_urn = li.post_text(post)
    except Exception as e:
        if tg and draft_id and message_id:
            tg.mark_failed(draft_id, message_id, str(e))
        raise

    if sources:
        try:
            li.comment(post_urn, "Sources:\n" + "\n".join(f"- {s.get('claim', 'Source')}: {s.get('url', '')}" for s in sources))
        except Exception as e:
            print("Post is live, but the source comment failed:", e)

    if tg and draft_id and message_id:
        tg.mark_posted(draft_id, message_id, post_urn)
    print("Posted to personal feed:", post_urn)

    target_groups = CFG.get("linkedin", {}).get("target_groups", [])
    if target_groups:
        delay = CFG.get("linkedin", {}).get("group_delay_seconds", 12)
        print(f"\nPublishing to {len(target_groups)} LinkedIn groups...")

        grp_tracker_id = None
        if tg:
            try:
                grp_tracker_id = tg.send_progress_tracker(f"Publishing to {len(target_groups)} LinkedIn Groups")
            except Exception:
                pass

        def on_group_progress(msg: str):
            if tg and grp_tracker_id:
                tg.update_progress(grp_tracker_id, msg)

        try:
            group_res = post_to_groups(
                target_groups,
                post,
                Path(image_path) if image_path else None,
                delay_seconds=delay,
                progress_callback=on_group_progress
            )
            success_count = len(group_res.get("success", []))
            summary_msg = f"🎉 Successfully published to personal wall + {success_count}/{len(target_groups)} LinkedIn groups!"
            if tg and grp_tracker_id:
                tg.update_progress(grp_tracker_id, summary_msg)
            elif tg and success_count > 0 and message_id:
                try:
                    tg._call("sendMessage", chat_id=tg.chat_id, reply_to_message_id=message_id, text=summary_msg)
                except Exception:
                    pass
        except Exception as e:
            print("Group posting encountered an error:", e)
            if tg and grp_tracker_id:
                tg.update_progress(grp_tracker_id, f"⚠️ Group posting encountered an issue: {e}")

    return post_urn


def handle_direct_post(post_text: str, custom_image_path: Path | None = None, generate_infographic: bool = True,
                       tg: TelegramReviewer | None = None, tracker_id: int | None = None):
    """Processes a user-provided direct post: optionally creates infographic, asks consent on Telegram, and publishes."""
    draft_id = datetime.now().strftime("%Y%m%d") + "-direct-" + uuid.uuid4().hex[:6]
    out_dir = ROOT / "output" / datetime.now().strftime("%Y-%m-%d_%H%M")
    out_dir.mkdir(parents=True, exist_ok=True)
    if not tg:
        tg = TelegramReviewer(
            os.environ["TELEGRAM_BOT_TOKEN"], os.environ["TELEGRAM_CHAT_ID"],
            timeout_s=CFG["telegram"]["timeout_hours"] * 3600,
            remind_every_s=CFG["telegram"]["remind_every_minutes"] * 60,
        )

    media_path = custom_image_path
    headline = "Direct Submission"

    if generate_infographic and not media_path:
        print("\n[Direct Post] Extracting visual idea & designing infographic...")
        if tg and tracker_id:
            tg.update_progress(tracker_id, f"🎨 [1/2] Auto-designing infographic layout for direct post ({len(post_text)} chars)...")
        try:
            res = call_json(
                system="You are an expert graphic design assistant. Given a LinkedIn post, return JSON: {\"headline\": \"short title 3-5 words\", \"infographic_idea\": \"2-3 sentences describing a visual layout or metaphor explaining the key points\"}",
                content=f"POST:\n{post_text}",
                max_tokens=1000
            )
            headline = res.get("headline", "Tech Insights")
            idea = res.get("infographic_idea", "Visual breakdown of the key takeaways.")
            svg = design_svg(post_text, idea, headline, None, CFG["infographic"]["footer"])
            image_path = out_dir / "direct_infographic.png"
            render_svg(svg, image_path)
            (out_dir / "direct_infographic.svg").write_text(svg)
            gif_path = out_dir / "direct_infographic.gif"
            try:
                render_svg_to_gif(svg, gif_path)
                media_path = gif_path
            except Exception as e:
                print(f"Animated GIF generation failed ({e}), using static PNG.")
                media_path = image_path
        except Exception as e:
            print(f"Infographic design for direct post failed: {e}. Falling back to text-only.")
            media_path = None

    if tg and tracker_id:
        tg.update_progress(tracker_id, "✅ [2/2] Post prepared! Delivering draft below for your consent...")

    if media_path and Path(media_path).exists():
        message_id = tg.send_draft(draft_id, headline, post_text, Path(media_path))
    else:
        message_id = tg.send_text_draft(draft_id, headline, post_text)

    print(f"Sent direct draft {draft_id} to Telegram; waiting for your decision...")
    decision = tg.wait_for_decision(draft_id, message_id)
    print("Decision:", decision)

    action = decision if isinstance(decision, str) else decision.get("action")
    if action == "approved":
        publish_to_linkedin_and_groups(
            post=post_text,
            image_path=media_path,
            headline=headline,
            sources=[],
            draft_id=draft_id,
            message_id=message_id,
            tg=tg,
        )
        append_log({
            "date": datetime.now().isoformat(timespec="seconds"),
            "draft_id": draft_id,
            "source_domain": "Direct Post",
            "headline": headline,
            "post_urn": "direct",
            "chars": len(post_text),
            "sources": []
        })
        print("Direct post successfully published to Wall and Groups.")
    elif action == "revise":
        feedback = decision.get("feedback")
        tg._call("sendMessage", chat_id=tg.chat_id,
                 text=f"✍️ Notes received:\n\"{feedback}\"\nRe-drafting with Claude...")
        run(source_arg=None, dry_run=False, topic_arg=f"Revising post based on: {feedback}\nOriginal:\n{post_text}", tg=tg)
    else:
        print("Direct post was cancelled or rejected.")


def publish_after_approval(headline, source, post, sources, image_path, tg: TelegramReviewer | None = None) -> dict:
    """Both gates must pass: the AI reviewers (already done) AND you on Telegram."""
    draft_id = datetime.now().strftime("%Y%m%d") + "-" + uuid.uuid4().hex[:8]
    if not tg:
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

    action = decision if isinstance(decision, str) else decision.get("action")

    if action == "approved" and get_status(draft_id) == "approved":
        post_urn = publish_to_linkedin_and_groups(
            post=post,
            image_path=image_path,
            headline=headline,
            sources=sources,
            draft_id=draft_id,
            message_id=message_id,
            tg=tg,
        )
        append_log({"date": datetime.now().isoformat(timespec="seconds"), "draft_id": draft_id,
                    "source_domain": source, "headline": headline,
                    "post_urn": post_urn, "chars": len(post), "sources": sources})
        return {"status": "posted"}

    elif action == "revise":
        return {"status": "revise", "feedback": decision.get("feedback")}

    elif action == "suggest_topics":
        suggestions = suggest_topics(count=3)
        choice = tg.choose_topic(draft_id, suggestions)
        if choice.get("action") == "new_topic":
            return {"status": "new_topic", "topic": choice.get("topic"), "source": choice.get("source")}
        return {"status": "rejected"}

    elif action == "new_topic":
        return {"status": "new_topic", "topic": decision.get("topic"), "source": decision.get("source")}

    return {"status": "rejected"}


# ---------------------------------------------------------------- main
def run(source_arg: str | None = None, dry_run: bool = False, topic_arg: str | None = None,
        tg: TelegramReviewer | None = None, tracker_id: int | None = None):
    log = load_log()
    posted = posted_urls(log)
    out_dir = ROOT / "output" / datetime.now().strftime("%Y-%m-%d_%H%M")
    out_dir.mkdir(parents=True, exist_ok=True)

    feedback, tried = None, set()
    current_source = source_arg
    current_topic = topic_arg

    for attempt in range(1, CFG["review"]["max_attempts"] + 1):
        if not current_source or not feedback:
            if current_topic and not current_source:
                current_source = source_arg or pick_source(log, exclude=tried) or SOURCES[0]
            else:
                current_source = source_arg or pick_source(log, exclude=tried)
            feedback = None

        if not current_source:
            print("No source available today: all were used recently or already tried.")
            if tg and tracker_id:
                tg.update_progress(tracker_id, "⚠️ All sources were used recently or tried. Please try a different topic.")
            sys.exit(0)

        tried.add(current_source)
        action_verb = "revising draft on" if feedback else "browsing"
        topic_info = f" (Topic: {current_topic})" if current_topic else ""
        print(f"\n--- Attempt {attempt}: {action_verb} {current_source}{topic_info} ---")
        if tg and tracker_id:
            tg.update_progress(tracker_id, f"🔍 [1/4] Researching fresh items on `{current_source}`{topic_info}...")

        draft = write_draft(current_source, feedback, posted, topic=current_topic)
        if draft.get("no_item"):
            print("Nothing fresh on this source:", draft.get("reason"))
            if tg and tracker_id:
                tg.update_progress(tracker_id, f"ℹ️ Nothing fresh on `{current_source}`. Checking next source...")
            current_source, feedback = None, None
            continue

        post = clamp_emojis(draft["post"].strip().replace("**", "").replace("__", ""))
        idea = draft.get("infographic_idea", "")
        headline = draft.get("headline", current_topic or current_source)
        sources = draft.get("sources", [])
        issues = hard_checks(post) + source_checks(sources, posted, is_custom_topic=bool(current_topic))
        if not idea:
            issues.append("Describe an infographic idea.")
        if issues:
            print("Checks failed:", issues)
            if tg and tracker_id:
                tg.update_progress(tracker_id, f"⚠️ [Attempt {attempt}/{CFG['review']['max_attempts']}] Refining draft: {issues[0][:60]}...")
            feedback = "\n".join(issues)
            continue

        if tg and tracker_id:
            tg.update_progress(tracker_id, f"✍️ [2/4] Drafted post ({len(post)} chars). Designing visual infographic...")

        image_path = out_dir / f"infographic_{attempt}.png"
        media_path = image_path
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
                gif_path = image_path.with_suffix(".gif")
                try:
                    render_svg_to_gif(svg, gif_path)
                    media_path = gif_path
                except Exception as e:
                    print(f"Animated GIF generation failed ({e}), using static PNG.")
                    media_path = image_path
                drawn = True
                break
            except ValueError as e:
                design_feedback = str(e)
                print("Render failed:", e)
        if not drawn:
            feedback = design_feedback
            if tg and tracker_id:
                tg.update_progress(tracker_id, f"⚠️ [Attempt {attempt}/{CFG['review']['max_attempts']}] Refining visual design: {design_feedback[:60]}...")
            continue

        if tg and tracker_id:
            tg.update_progress(tracker_id, f"🧐 [3/4] Infographic rendered. Running 3 editorial reviews & fact-check...")

        ok, issues, detail = review_all(headline, post, sources, image_path, is_custom_topic=bool(current_topic))
        if ok:
            (out_dir / "post.txt").write_text(post + "\n\nSources:\n" + "\n".join(s["url"] for s in sources))
            (out_dir / "review.json").write_text(json.dumps(detail, indent=2, ensure_ascii=False))
            print(f"\nAPPROVED ({len(post)} chars). Saved to {out_dir}")
            if tg and tracker_id:
                tg.update_progress(tracker_id, f"✅ [4/4] Editorial approval passed! Delivering draft below for your review...")
            if dry_run:
                print("Dry run: not sending to Telegram or LinkedIn.\n\n" + post)
                print("\nSources:\n" + "\n".join(f"- {s['url']}" for s in sources))
                return

            res = publish_after_approval(headline, current_source, post, sources, media_path, tg=tg)
            status = res.get("status")
            if status == "posted":
                return
            elif status == "revise":
                feedback = res.get("feedback")
                print(f"\n[Telegram Feedback] User requested revisions: {feedback}")
                if tg and tracker_id:
                    tg.update_progress(tracker_id, f"🔄 Redrafting based on notes: \"{feedback[:50]}...\"")
                continue
            elif status == "new_topic":
                current_topic = res.get("topic")
                current_source = res.get("source") or current_source
                feedback = None
                print(f"\n[Telegram Topic Switch] User requested: {current_topic} (Source: {current_source})")
                if tg and tracker_id:
                    tg.update_progress(tracker_id, f"🔄 Switching topic to: {current_topic[:50]}...")
                continue
            else:
                print("User declined or skipped post.")
                return

        feedback = "\n".join(issues) or "Improve quality and image match."
        print("Rejected:\n" + feedback)
        if tg and tracker_id:
            tg.update_progress(tracker_id, f"⚠️ [Attempt {attempt}/{CFG['review']['max_attempts']}] Editorial reviewer requested changes: {feedback[:60]}...")

    print("\nAll attempts completed.")
    if tg and tracker_id:
        tg.update_progress(
            tracker_id,
            f"❌ Could not produce an approved draft for '{current_topic or current_source}' after {CFG['review']['max_attempts']} attempts.\n\n"
            f"Last issue: {feedback[:150] if feedback else 'Checks could not be satisfied.'}\n\n"
            "💡 Tip: Tap ✍️ Post from Topic to try another prompt or 📝 Direct Post to provide your own text directly."
        )



def get_agent_status_text() -> str:
    log = load_log()
    lines = ["📊 **LinkedIn Agent Status & History**\n"]
    if not log:
        lines.append("No posts recorded in posted.json yet.")
    else:
        lines.append(f"Total posts published: **{len(log)}**")
        lines.append("\n**Recent Posts:**")
        for item in reversed(log[-3:]):
            dt = item.get("date", "")[:10]
            hl = item.get("headline", "Post")
            src = item.get("source_domain", "")
            lines.append(f"• **{dt}**: {hl} ({src})")
    target_groups = CFG.get("linkedin", {}).get("target_groups", [])
    lines.append(f"\nTarget LinkedIn Groups: **{len(target_groups)}**")
    lines.append(f"Allowed Source URLs: **{len(SOURCES)}**")

    openai_status = f"Ready ({CFG.get('openai_fallback_model', 'gpt-4o')})" if openai_client else "Not configured"
    active_str = "OpenAI" if ACTIVE_LLM_PROVIDER == "openai" else "Claude"
    lines.append(f"\n🧠 Primary LLM: **Claude ({CFG['model']})**")
    lines.append(f"🔄 Fallback LLM: **OpenAI ({openai_status})**")
    lines.append(f"⚡ Currently Active: **{active_str}**")
    return "\n".join(lines)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", help="browse this allowed domain instead of picking one")
    ap.add_argument("--topic", help="manually provide a topic instead of picking from source")
    ap.add_argument("--direct", help="provide full post text directly to publish to wall & groups")
    ap.add_argument("--image", help="path to image to accompany direct post")
    ap.add_argument("--no-image", action="store_true", help="skip generating infographic for direct post")
    ap.add_argument("--listen", action="store_true", help="run Telegram listener for /topic, /direct, or photos")
    ap.add_argument("--setup-bot", action="store_true", help="configure Telegram bot command menu and profile")
    ap.add_argument("--openai", action="store_true", help="force using OpenAI instead of Claude")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.openai:
        if not openai_client:
            print("❌ Cannot use --openai: OPENAI_API_KEY (or OPEN_AI_API_KEY) is not set in .env")
            sys.exit(1)
        ACTIVE_LLM_PROVIDER = "openai"
        print(f"⚡ Forced active LLM provider to OpenAI ({CFG.get('openai_fallback_model', 'gpt-4o')})")

    if args.setup_bot:
        tg = TelegramReviewer(os.environ["TELEGRAM_BOT_TOKEN"], os.environ["TELEGRAM_CHAT_ID"])
        res = tg.set_bot_commands()
        print("Telegram bot menu commands configured:", res)
    elif args.listen:
        tg = TelegramReviewer(
            os.environ["TELEGRAM_BOT_TOKEN"], os.environ["TELEGRAM_CHAT_ID"],
            timeout_s=CFG["telegram"]["timeout_hours"] * 3600,
            remind_every_s=CFG["telegram"]["remind_every_minutes"] * 60,
        )
        def on_telegram_topic(t: str):
            tracker_id = tg.send_progress_tracker(f"Generating Post from Topic: {t[:40]}")
            try:
                run(source_arg=None, dry_run=False, topic_arg=t, tg=tg, tracker_id=tracker_id)
            except Exception as e:
                print("Error in on_telegram_topic:", e)
                tg.update_progress(tracker_id, f"⚠️ Error generating post: {str(e)[:250]}")

        def on_telegram_direct(text: str, custom_image_path: Path | None = None, generate_infographic: bool = True):
            tracker_id = tg.send_progress_tracker("Processing Direct Post")
            try:
                handle_direct_post(text, custom_image_path=custom_image_path, generate_infographic=generate_infographic, tg=tg, tracker_id=tracker_id)
            except Exception as e:
                print("Error in on_telegram_direct:", e)
                tg.update_progress(tracker_id, f"⚠️ Error processing direct post: {str(e)[:250]}")

        def on_telegram_daily():
            tracker_id = tg.send_progress_tracker("Daily LinkedIn Post Pipeline")
            try:
                run(source_arg=None, dry_run=False, tg=tg, tracker_id=tracker_id)
            except Exception as e:
                print("Error in on_telegram_daily:", e)
                tg.update_progress(tracker_id, f"⚠️ Error in daily post: {str(e)[:250]}")

        def on_telegram_suggest():
            try:
                suggestions = suggest_topics(count=3)
                choice = tg.choose_topic("suggest-" + uuid.uuid4().hex[:6], suggestions)
                if choice.get("action") == "new_topic":
                    topic_title = choice.get("topic") or "Suggested Topic"
                    tracker_id = tg.send_progress_tracker(f"Generating Post from Topic: {topic_title[:40]}")
                    run(source_arg=choice.get("source"), dry_run=False, topic_arg=choice.get("topic"), tg=tg, tracker_id=tracker_id)
            except Exception as e:
                print("Error in on_telegram_suggest:", e)

        tg.listen_for_commands(
            on_topic_callback=on_telegram_topic,
            on_direct_callback=on_telegram_direct,
            on_daily_callback=on_telegram_daily,
            on_suggest_callback=on_telegram_suggest,
            on_status_callback=get_agent_status_text,
        )
    elif args.direct:
        img = Path(args.image) if args.image else None
        handle_direct_post(args.direct, custom_image_path=img, generate_infographic=not args.no_image)
    else:
        run(args.source, args.dry_run, topic_arg=args.topic)
