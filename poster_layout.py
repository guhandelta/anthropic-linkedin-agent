"""Predictable, readable SVG poster layout for an LLM-authored content blueprint.

The model chooses the facts and sections; this module owns positions, wrapping,
contrast, and the reading order. It never invents technical claims.
"""

from __future__ import annotations

import json
import re
from html import escape


MARKER = "CONTENT BLUEPRINT (draw exactly this content; every fact comes from the post):"

# Every colour in a poster is a token such as @ink@; _apply_theme swaps the tokens for one palette.
# Each palette keeps body text at WCAG AA contrast on its cards and banners.
_AMBER = {"warn_bg": "#FFF3DD", "warn_stroke": "#E5B967", "warn_icon": "#B46A16",
          "warn_head": "#8A4C0B", "warn_text": "#5B421E"}
THEMES: dict[str, dict[str, str]] = {
    "ocean": {"bg": "#F7F9FC", "soft_ink": "#315DA5", "card": "#FFFFFF", "card_stroke": "#DCE6F3", "node": "#F2F6FC",
              "soft": "#E9F0FD", "soft2": "#EEF4FD", "soft_stroke": "#D5E3F8", "strong": "#315DA5",
              "on_strong": "#FFFFFF", "ink": "#132238", "muted": "#42536B", "primary": "#3768B7",
              "a1": "#3768B7", "a2": "#7A4CC2", "a3": "#1D9369", "a4": "#C66B2E", "a5": "#2F7F9B",
              "good": "#1D9369", "bad": "#C66B2E", "good_soft": "#EAF6F0", "bad_soft": "#FCF0E8",
              "code_bg": "#15253D", "code_ink": "#FFFFFF", "code_muted": "#DCE8F7",
              "code_icon": "#9FC5FF", **_AMBER, "rule": "#CBD5E1", "footer": "#5B6B83"},
    "forest": {"bg": "#F4F8F4", "soft_ink": "#1F6B45", "card": "#FFFFFF", "card_stroke": "#D3E4D6", "node": "#EFF6F0",
               "soft": "#E3F1E6", "soft2": "#EAF4EC", "soft_stroke": "#C7E0CD", "strong": "#1F6B45",
               "on_strong": "#FFFFFF", "ink": "#14261B", "muted": "#3F5546", "primary": "#23784E",
               "a1": "#23784E", "a2": "#2F6F8F", "a3": "#8A6A12", "a4": "#B5502F", "a5": "#5E6AAE",
               "good": "#23784E", "bad": "#B5502F", "good_soft": "#E8F4EC", "bad_soft": "#FBEEE9",
               "code_bg": "#13261C", "code_ink": "#FFFFFF", "code_muted": "#D4EADB",
               "code_icon": "#8FD6AA", **_AMBER, "rule": "#C3D6C8", "footer": "#52675A"},
    "sunset": {"bg": "#FFF8F3", "soft_ink": "#A33E24", "card": "#FFFFFF", "card_stroke": "#F3DCCD", "node": "#FFF3EA",
               "soft": "#FDE8DA", "soft2": "#FEF0E6", "soft_stroke": "#F6CFB6", "strong": "#B7472A",
               "on_strong": "#FFFFFF", "ink": "#2B1610", "muted": "#5E4238", "primary": "#C2502F",
               "a1": "#C2502F", "a2": "#A8366E", "a3": "#2F7D6B", "a4": "#7A55B8", "a5": "#9A6A0E",
               "good": "#2F7D6B", "bad": "#B7472A", "good_soft": "#EAF5F1", "bad_soft": "#FCEBE4",
               "code_bg": "#2A1712", "code_ink": "#FFFFFF", "code_muted": "#F3DCD2",
               "code_icon": "#FFB59A", "warn_bg": "#FFF6D8", "warn_stroke": "#E2C060",
               "warn_icon": "#A67A0A", "warn_head": "#7A5600", "warn_text": "#5A4518",
               "rule": "#E8CFC2", "footer": "#7A5A4E"},
    "grape": {"bg": "#F8F6FD", "soft_ink": "#5B3BA8", "card": "#FFFFFF", "card_stroke": "#E2DBF3", "node": "#F3F0FC",
              "soft": "#ECE6FB", "soft2": "#F1EDFC", "soft_stroke": "#D7CCF4", "strong": "#5B3BA8",
              "on_strong": "#FFFFFF", "ink": "#1E1633", "muted": "#4A4063", "primary": "#6A47C2",
              "a1": "#6A47C2", "a2": "#2E6FB7", "a3": "#B03C83", "a4": "#1D8A73", "a5": "#B0601A",
              "good": "#1D8A73", "bad": "#B03C55", "good_soft": "#E8F5F2", "bad_soft": "#FBECEF",
              "code_bg": "#1D1533", "code_ink": "#FFFFFF", "code_muted": "#E1D9F7",
              "code_icon": "#C4B2FF", **_AMBER, "rule": "#D6CDEB", "footer": "#645A7E"},
    "midnight": {"bg": "#0E1726", "soft_ink": "#A9CBFF", "card": "#16233A", "card_stroke": "#2A3B58", "node": "#1B2B45",
                 "soft": "#1A2C4A", "soft2": "#1A2A44", "soft_stroke": "#33507D", "strong": "#2563EB",
                 "on_strong": "#FFFFFF", "ink": "#F1F5FB", "muted": "#B4C2D8", "primary": "#7FB2FF",
                 "a1": "#7FB2FF", "a2": "#C4A2FF", "a3": "#5FD3A5", "a4": "#FFA36B", "a5": "#67D3E6",
                 "good": "#5FD3A5", "bad": "#FF8A6B", "good_soft": "#14302C", "bad_soft": "#33221F",
                 "code_bg": "#08101C", "code_ink": "#FFFFFF", "code_muted": "#CFE0F7",
                 "code_icon": "#7FB2FF", "warn_bg": "#3A2A10", "warn_stroke": "#8A6A2A",
                 "warn_icon": "#FFC56B", "warn_head": "#FFD58F", "warn_text": "#F3E2C2",
                 "rule": "#2A3B58", "footer": "#9AA9C2"},
    "ember": {"bg": "#FBF6F4", "soft_ink": "#9F2D20", "card": "#FFFFFF", "card_stroke": "#EBD9D3", "node": "#F8EFEC",
              "soft": "#F6E3DD", "soft2": "#F9ECE8", "soft_stroke": "#E9C8BE", "strong": "#9F2D20",
              "on_strong": "#FFFFFF", "ink": "#2A1512", "muted": "#573F3A", "primary": "#B33A2A",
              "a1": "#B33A2A", "a2": "#2E6F8E", "a3": "#8B5A12", "a4": "#6B4FA8", "a5": "#2F7D5B",
              "good": "#2F7D5B", "bad": "#B33A2A", "good_soft": "#EAF4EE", "bad_soft": "#FAEAE6",
              "code_bg": "#241311", "code_ink": "#FFFFFF", "code_muted": "#F0DCD6",
              "code_icon": "#FFA08F", **_AMBER, "rule": "#E3CFC8", "footer": "#75605A"},
}
# What each palette suits; the planner sees this list and suggests one.
THEME_HINTS = {
    "ocean": "general explainers and how-tos",
    "forest": "performance, efficiency, cost or growth",
    "sunset": "launches, releases and new features",
    "grape": "AI, ML and LLM topics",
    "midnight": "infrastructure, security, systems and low-level internals",
    "ember": "bugs, breaking changes, incidents and pitfalls",
}
ACCENTS = ("@a1@", "@a2@", "@a3@", "@a4@", "@a5@")
STYLES = ("guide", "timeline", "spotlight", "comparison", "dashboard", "code_focus", "incident",
          "stack", "sidebar")


def _clean(value: object) -> str:
    return " ".join(str(value or "").split())


def _wrap(value: object, width: int, font_size: int, max_lines: int) -> list[str]:
    """Conservatively wrap SVG text, which has no native line wrapping."""
    text = _clean(value)
    limit = max(7, int(width / (font_size * 0.61)))
    words = text.split()
    lines: list[str] = []
    line = ""
    for word in words:
        if len(word) > limit:
            word = word[:limit - 1] + "…"
        candidate = f"{line} {word}".strip()
        if len(candidate) > limit and line:
            lines.append(line)
            line = word
        else:
            line = candidate
    if line:
        lines.append(line)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(" .,;:")
    return lines


def _fit_words(value: object, width: int, font_size: int) -> str:
    """Keep as many leading words as fit on one line (no ellipsis, so nothing looks cut off)."""
    limit = max(7, int(width / (font_size * 0.61)))
    out = ""
    for word in _clean(value).split():
        candidate = f"{out} {word}".strip()
        if len(candidate) > limit:
            break
        out = candidate
    return out or _clean(value)[:limit]


def _wrap_code(value: object, width: int, font_size: int, max_lines: int) -> list[str]:
    """Wrap a code line at punctuation (code rarely has spaces), indenting continuations."""
    text = _clean(value)
    if text.endswith(('...', '…')):
        text = text.rstrip('.… ') + ' /* more */'
    limit = max(7, int(width / (font_size * 0.61)))
    lines: list[str] = []
    while len(text) > limit and len(lines) < max_lines - 1:
        cut = max((text.rfind(ch, 0, limit) for ch in ".(,=:{ "), default=-1)
        cut = limit if cut < limit // 3 else cut + 1
        lines.append(text[:cut].rstrip())
        text = "  " + text[cut:].lstrip()
    if len(text) > limit:
        text = text[:limit - 1] + "…"
    lines.append(text)
    return lines


def _text(x: int, y: int, value: object, *, size: int = 22, fill: str = "@ink@",
          weight: str = "normal", family: str = "Arial, DejaVu Sans, sans-serif") -> str:
    return (f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" '
            f'font-family="{family}" fill="{fill}">{escape(_clean(value))}</text>')


def _lines(x: int, y: int, value: object, width: int, *, size: int = 22,
           max_lines: int = 2, step: int = 28, fill: str = "@muted@",
           weight: str = "normal") -> list[str]:
    return [_text(x, y + i * step, line, size=size, fill=fill, weight=weight)
            for i, line in enumerate(_wrap(value, width, size, max_lines))]


def _rect(x: int, y: int, w: int, h: int, fill: str, *, stroke: str = "none",
          radius: int = 18) -> str:
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="2"/>')


def _icon(name: object, x: int, y: int, color: str, scale: float = 1.8) -> str:
    from infographic import ICONS

    icon = str(name or "sparkle").lower()
    if icon not in ICONS:
        icon = "sparkle"
    return (f'<use href="#icon-{icon}" transform="translate({x},{y}) scale({scale})" '
            f'color="{color}"/>')


def _node(parts: list[str], node: dict, x: int, y: int, w: int, h: int,
          number: int, accent: str) -> None:
    parts.append(_rect(x, y, w, h, "@node@", stroke="@card_stroke@", radius=15)
                 .replace("<rect ", f'<rect data-motion-step="{number}" ', 1))
    parts.append(_rect(x, y, 6, h, accent, radius=3))
    parts.append(_icon(node.get("icon"), x + 20, y + 18, accent, 1.6))
    parts.append(_text(x + 68, y + 39, str(number), size=22, fill=accent, weight="bold"))
    label = _wrap(node.get("label"), w - 40, 25, 2)
    for j, line in enumerate(label or ["Step"]):
        parts.append(_text(x + 20, y + 85 + j * 29, line, size=25,
                           fill="@ink@", weight="bold"))
    detail_y = y + (144 if len(label) > 1 else 119)
    parts.extend(_lines(x + 20, detail_y, node.get("detail"), w - 40,
                        size=22, max_lines=1 if len(label) > 1 else 2, step=29))


def _module(parts: list[str], module: dict, x: int, y: int, w: int, h: int,
            number: int, accent: str) -> None:
    kind = _clean(module.get("kind")).lower()
    code = kind == "code"
    bg = "@code_bg@" if code else "@card@"
    ink = "@code_ink@" if code else "@ink@"
    muted = "@code_muted@" if code else "@muted@"
    parts.append(_rect(x, y, w, h, bg, stroke="@card_stroke@" if not code else "@code_bg@"))
    parts.append(_rect(x, y, w, 7, accent, radius=3))
    parts.append(_icon(module.get("icon"), x + 20, y + 22, "@code_icon@" if code else accent, 1.5))
    # Narrow cards use a smaller heading; the fit leaves room for the "N. " prefix.
    size = 25 if w >= 400 else 22
    heading = _fit_words(module.get("heading"), int(w - 88 - 3 * size * 0.61), size)
    parts.append(_text(x + 68, y + 52, f"{number}. {heading or 'Key point'}",
                       size=size, fill=ink, weight="bold"))
    raw_lines = module.get("lines")
    if not isinstance(raw_lines, list):
        raw_lines = []
    content: list[str] = []
    if kind == "stats" and any("|" in str(r) for r in raw_lines):
        for i, raw in enumerate(raw_lines[:4]):
            value, _, caption = str(raw).partition("|")
            value = _fit_words(value, 175, 26)
            parts.append(_text(x + 24, y + 86 + i * 28, value, size=26, fill=accent, weight="bold"))
            caption = _fit_words(caption, w - 60 - 175, 22)
            parts.append(_text(x + 24 + 175, y + 86 + i * 28, caption, size=22, fill=muted))
        return
    for raw in raw_lines:
        # An item wraps onto up to three lines. Anything longer, or past the four-line budget,
        # is dropped whole rather than cut mid-sentence.
        wrapped = (_wrap_code if code else _wrap)(raw, w - 60, 22, 10)
        if len(wrapped) > 3:
            continue
        group = [("• " if j == 0 and not code else "  " if not code else "") + line
                 for j, line in enumerate(wrapped)]
        if len(content) + len(group) > 4:
            break
        content.extend(group)
    for i, line in enumerate(content[:4]):
        parts.append(_text(x + 24, y + 84 + i * 28, line, size=22,
                           fill=muted, family="Menlo, Courier New, monospace" if code else
                           "Arial, DejaVu Sans, sans-serif"))


def _hero_flow(parts: list[str], plan: dict, nodes: list, accent: list[str]) -> None:
    """The default hero: a row of 3 steps, or two rows of 3 and 4-5 steps, with arrows."""
    if len(nodes) == 3:
        width, gap, positions = 307, 24, [(65 + i * 331, 345) for i in range(3)]
        height = 190
    else:
        lower_start = 386 if len(nodes) == 4 else 230
        width, gap, positions = 307, 24, ([(65 + i * 331, 335) for i in range(3)] +
                                           [(lower_start + i * 331, 485) for i in range(len(nodes) - 3)])
        height = 135
    for i, (node, (x, y)) in enumerate(zip(nodes, positions), 1):
        if len(nodes) > 3:
            # Compact nodes: up to two label lines, then one detail line (no ellipsis anywhere).
            parts.append(_rect(x, y, width, height, "@node@", stroke="@card_stroke@", radius=15)
                         .replace("<rect ", f'<rect data-motion-step="{i}" ', 1))
            parts.append(_rect(x, y, 6, height, accent[i - 1], radius=3))
            parts.append(_icon(node.get("icon"), x + 18, y + 16, accent[i - 1], 1.4))
            parts.append(_text(x + 64, y + 37, str(i), size=22, fill=accent[i - 1], weight="bold"))
            label = _wrap(node.get("label"), width - 40, 22, 2) or ["Step"]
            for j, line in enumerate(label):
                parts.append(_text(x + 18, y + 72 + j * 25, line, size=22, weight="bold"))
            detail = _fit_words(node.get("detail"), width - 40, 22)
            if detail:
                parts.append(_text(x + 18, y + 72 + len(label) * 25 + 1, detail, size=22,
                                   fill="@muted@"))
        else:
            _node(parts, node, x, y, width, height, i, accent[i - 1])
    if len(nodes) == 3:
        for x in (376, 707):
            parts.append(f'<line x1="{x}" y1="440" x2="{x + 18}" y2="440" '
                         'stroke="@primary@" stroke-width="3" stroke-dasharray="10 10" '
                         'marker-end="url(#arrow)"/>')
        tagline = _clean(plan.get("tagline"))
        if tagline:
            parts.append(_rect(65, 550, 950, 51, "@soft@", radius=10))
            parts.append(_icon("bulb", 82, 559, "@primary@", 1.3))
            parts.extend(_lines(123, 584, tagline, 850, size=22, max_lines=1,
                                fill="@soft_ink@", weight="bold"))
    else:
        for x in (376, 707):
            parts.append(f'<line x1="{x}" y1="403" x2="{x + 18}" y2="403" '
                         'stroke="@primary@" stroke-width="3" stroke-dasharray="10 10" '
                         'marker-end="url(#arrow)"/>')
        if len(nodes) == 4:
            parts.append('<path d="M 880 465 C 880 472 750 465 700 485" fill="none" '
                         'stroke="@primary@" stroke-width="3" stroke-dasharray="10 10" '
                         'marker-end="url(#arrow)"/>')
        else:
            parts.append('<path d="M 880 465 C 880 472 850 468 780 485" fill="none" '
                         'stroke="@primary@" stroke-width="3" stroke-dasharray="10 10" '
                         'marker-end="url(#arrow)"/>')


def _hero_before_after(parts: list[str], hero: dict, nodes: list, accent: list[str]) -> None:
    """Two columns: the old way on the left, the new way on the right, two steps each."""
    columns = [(65, "@bad@", hero.get("left_label") or "Before", nodes[:2]),
               (580, "@good@", hero.get("right_label") or "After", nodes[2:])]
    for x, colour, heading, column in columns:
        parts.append(_text(x, 352, _fit_words(heading, 435, 26), size=26, fill=colour, weight="bold"))
        for n, node in enumerate(column):
            y = 380 + n * 118
            number = nodes.index(node) + 1
            parts.append(_rect(x, y, 435, 108, "@node@", stroke="@card_stroke@", radius=15)
                         .replace("<rect ", f'<rect data-motion-step="{number}" ', 1))
            parts.append(_rect(x, y, 6, 108, colour, radius=3))
            parts.append(_icon(node.get("icon"), x + 18, y + 14, colour, 1.3))
            label = _fit_words(node.get("label"), 435 - 80, 24) or "Step"
            parts.append(_text(x + 60, y + 38, label, size=24, fill="@ink@", weight="bold"))
            parts.extend(_lines(x + 60, y + 72, node.get("detail"), 435 - 80, size=21, max_lines=1))
    parts.append('<line x1="505" y1="434" x2="575" y2="434" stroke="@primary@" stroke-width="3" '
                 'stroke-dasharray="10 10" marker-end="url(#arrow)"/>')


def _hero_layers(parts: list[str], nodes: list, accent: list[str]) -> None:
    """A stack of bands from the first step (top) to the last, one step per band."""
    for i, node in enumerate(nodes):
        y = 352 + i * 70
        colour = accent[i % len(accent)]
        parts.append(_rect(65, y, 950, 60, "@node@", stroke="@card_stroke@", radius=12)
                     .replace("<rect ", f'<rect data-motion-step="{i + 1}" ', 1))
        parts.append(_rect(65, y, 6, 60, colour, radius=3))
        parts.append(_icon(node.get("icon"), 88, y + 16, colour, 1.2))
        parts.append(_text(128, y + 38, str(i + 1), size=22, fill=colour, weight="bold"))
        parts.append(_text(162, y + 38, _fit_words(node.get("label"), 300, 24) or "Step",
                           size=24, fill="@ink@", weight="bold"))
        parts.append(_text(470, y + 38, _fit_words(node.get("detail"), 520, 21), size=21, fill="@muted@"))


def _apply_theme(svg: str, theme: str) -> str:
    """Swap every @token@ for the theme's colour."""
    palette = THEMES[theme]
    return re.sub(r"@([a-z0-9_]+)@", lambda m: palette[m.group(1)], svg)


def _start(parts: list[str], style: str, theme: str) -> None:
    parts.append(f'<svg viewBox="0 0 1080 1350" data-layout="structured" data-style="{style}" '
                 f'data-theme="{theme}" data-highlight="@primary@" '
                 'xmlns="http://www.w3.org/2000/svg">')
    parts.append(_rect(0, 0, 1080, 1350, "@bg@", radius=0))
    parts.append('<defs><marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" '
                 'markerWidth="6" markerHeight="6" orient="auto"><path d="M 0 1 L 9 5 L 0 9 Z" '
                 'fill="@primary@" stroke-dasharray="none"/></marker></defs>')


def _arrow(x1: int, y1: int, x2: int, y2: int) -> str:
    return (f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="@primary@" stroke-width="3" '
            'stroke-dasharray="10 10" marker-end="url(#arrow)"/>')


def _modules_grid(parts: list[str], plan: dict, modules: list, accent: list[str],
                  top: int, h: int, gap: int = 16, left: int = 40, width: int = 490,
                  col_gap: int = 20) -> None:
    """Two columns of modules; a third module gets an APPLICATION card beside it."""
    right = left + width + col_gap
    for i, module in enumerate(modules):
        x = left if i % 2 == 0 else right
        y = top if i < 2 else top + h + gap
        _module(parts, module, x, y, width, h, i + 1, accent[i % len(accent)])
    if len(modules) == 3:
        y = top + h + gap
        parts.append(_rect(right, y, width, h, "@soft2@", stroke="@card_stroke@"))
        parts.append(_icon("target", right + 25, y + 25, "@primary@", 1.5))
        parts.append(_text(right + 70, y + 52, "APPLICATION", size=25, fill="@ink@", weight="bold"))
        parts.extend(_lines(right + 25, y + 95, plan.get("tagline") or plan.get("takeaway"),
                            width - 60, size=22, max_lines=(h - 80) // 29, step=29))


def _bottom(parts: list[str], plan: dict, footer: str) -> None:
    """Watch-out strip, takeaway banner and footer: shared by every layout."""
    gotcha = plan["gotcha"]
    parts.append(_rect(40, 1105, 1000, 74, "@warn_bg@", stroke="@warn_stroke@"))
    parts.append(_icon("warning", 60, 1120, "@warn_icon@", 1.5))
    parts.append(_text(110, 1139, _wrap(gotcha.get("heading") or "Watch out", 250, 24, 1)[0],
                       size=24, fill="@warn_head@", weight="bold"))
    parts.extend(_lines(110, 1165, gotcha.get("text"), 900, size=22, max_lines=1,
                        fill="@warn_text@"))
    # The takeaway may wrap to two lines inside the banner, so it is not clipped with an ellipsis.
    parts.append(_rect(40, 1192, 1000, 84, "@strong@"))
    parts.append(_icon("bulb", 60, 1217, "@on_strong@", 1.5))
    parts.extend(_lines(110, 1226, plan["takeaway"], 900, size=23, max_lines=2, step=26,
                        fill="@on_strong@", weight="bold"))
    parts.append('<line x1="60" y1="1285" x2="1020" y2="1285" stroke="@rule@" '
                 'stroke-width="2" stroke-dasharray="none"/>')
    parts.append(_text(60, 1321, footer, size=22, fill="@footer@"))


def _soft_header(parts: list[str], plan: dict, headline: str, kicker: str, icon: str) -> None:
    """Tinted header card (y 35-220): kicker, title of up to two lines and a subtitle."""
    parts.append(_rect(40, 35, 1000, 185, "@soft@", stroke="@soft_stroke@"))
    parts.append(_icon(icon, 65, 55, "@primary@", 1.4))
    parts.append(_text(110, 83, kicker, size=22, fill="@primary@", weight="bold"))
    title = _wrap(plan.get("title") or headline, 940, 46, 2)
    for i, line in enumerate(title):
        parts.append(_text(65, 132 + i * 51, line, size=46, fill="@ink@", weight="bold"))
    subtitle_y = 193 if len(title) == 1 else 211
    parts.extend(_lines(65, subtitle_y, plan.get("subtitle"), 940, size=22, max_lines=1))


def _layout_guide(parts: list[str], plan: dict, headline: str, accent: list[str]) -> None:
    """Soft header card, one framed hero diagram, then a 2x2 grid of details."""
    hero, nodes = plan["hero"], plan["hero"]["nodes"]
    _soft_header(parts, plan, headline, "TECHNICAL FIELD GUIDE", "sparkle")

    parts.append(_rect(40, 242, 1000, 388, "@card@", stroke="@card_stroke@"))
    parts.append(_text(65, 280, "HOW IT WORKS", size=26, fill="@primary@", weight="bold"))
    parts.extend(_lines(65, 313, hero.get("caption"), 930, size=22, max_lines=1))
    form = _clean(hero.get("form")).lower()
    if form == "before_after" and len(nodes) == 4:
        _hero_before_after(parts, hero, nodes, accent)
    elif form == "layers" and len(nodes) in (3, 4):
        _hero_layers(parts, nodes, accent)
    else:
        _hero_flow(parts, plan, nodes, accent)
    parts.append(_text(45, 678, "THE PRACTICAL DETAILS", size=26, fill="@ink@", weight="bold"))
    _modules_grid(parts, plan, plan["modules"], accent, 698, 187)


def _band_header(parts: list[str], plan: dict, headline: str, kicker: str, icon: str) -> None:
    """Full-bleed coloured header band (y 0-250) with the title in the banner colour."""
    parts.append(_rect(0, 0, 1080, 250, "@strong@", radius=0))
    parts.append(_icon(icon, 45, 40, "@on_strong@", 1.4))
    parts.append(_text(92, 68, kicker, size=22, fill="@on_strong@", weight="bold"))
    title = _wrap(plan.get("title") or headline, 990, 46, 2)
    for i, line in enumerate(title):
        parts.append(_text(45, 128 + i * 52, line, size=46, fill="@on_strong@", weight="bold"))
    subtitle_y = 190 if len(title) == 1 else 226
    parts.extend(_lines(45, subtitle_y, plan.get("subtitle"), 990, size=22, max_lines=1,
                        fill="@on_strong@"))


def _layout_timeline(parts: list[str], plan: dict, headline: str, accent: list[str]) -> None:
    """Header band, a vertical numbered path on the left and stacked details on the right."""
    hero, nodes, modules = plan["hero"], plan["hero"]["nodes"], plan["modules"]
    _band_header(parts, plan, headline, "STEP BY STEP", "list")
    parts.append(_text(45, 296, _fit_words(hero.get("caption") or "The path", 470, 24).upper()
                       if len(_clean(hero.get("caption"))) <= 30 else "THE PATH",
                       size=24, fill="@primary@", weight="bold"))
    parts.append(_text(555, 296, "IN PRACTICE", size=24, fill="@primary@", weight="bold"))

    n = len(nodes)
    h = min(200, (770 - 14 * (n - 1)) // n)
    centres = [315 + i * (h + 14) + h // 2 for i in range(n)]
    for top, below in zip(centres, centres[1:]):
        # Spine segments stop short of each numbered circle so they never cross a number.
        parts.append(f'<line x1="70" y1="{top + 28}" x2="70" y2="{below - 28}" stroke="@primary@" '
                     'stroke-width="4" stroke-dasharray="10 10"/>')
    for i, node in enumerate(nodes):
        y, colour = 315 + i * (h + 14), accent[i % len(accent)]
        parts.append(f'<circle cx="70" cy="{centres[i]}" r="22" fill="{colour}"/>')
        parts.append(_text(64, centres[i] + 8, str(i + 1), size=22, fill="@bg@", weight="bold"))
        parts.append(_rect(110, y, 410, h, "@card@", stroke="@card_stroke@", radius=15)
                     .replace("<rect ", f'<rect data-motion-step="{i + 1}" ', 1))
        parts.append(_rect(110, y, 6, h, colour, radius=3))
        parts.append(_icon(node.get("icon"), 130, y + 16, colour, 1.4))
        parts.append(_text(176, y + 44, _fit_words(node.get("label"), 320, 24) or "Step",
                           size=24, fill="@ink@", weight="bold"))
        parts.extend(_lines(132, y + 84, node.get("detail"), 370, size=22,
                            max_lines=max(1, min(3, (h - 70) // 29)), step=29))
    end = 315 + n * (h + 14)
    tagline = _clean(plan.get("tagline"))
    if 1085 - end >= 100 and tagline:
        parts.append(_rect(40, end, 480, 1085 - end, "@soft@", stroke="@soft_stroke@"))
        parts.append(_icon("bulb", 60, end + 22, "@primary@", 1.4))
        parts.extend(_lines(106, end + 50, tagline, 390, size=22, max_lines=2, step=29,
                            fill="@soft_ink@", weight="bold"))

    m = len(modules)
    mh = (770 - 16 * (m - 1)) // m
    for i, module in enumerate(modules):
        _module(parts, module, 550, 315 + i * (mh + 16), 490, mh, i + 1, accent[i % len(accent)])


def _ribbon(parts: list[str], nodes: list, accent: list[str], top: int, h: int) -> None:
    """A row of 3-4 step cards joined by arrows (h >= 200 leaves room for every line)."""
    n, gap = len(nodes), 24
    w = (1000 - gap * (n - 1)) // n
    for i, node in enumerate(nodes):
        x, colour = 40 + i * (w + gap), accent[i % len(accent)]
        parts.append(_rect(x, top, w, h, "@card@", stroke="@card_stroke@", radius=15)
                     .replace("<rect ", f'<rect data-motion-step="{i + 1}" ', 1))
        parts.append(_rect(x, top, w, 7, colour, radius=3))
        parts.append(_icon(node.get("icon"), x + 18, top + 22, colour, 1.5))
        parts.append(_text(x + w - 44, top + 52, str(i + 1), size=26, fill=colour, weight="bold"))
        label = _wrap(node.get("label"), w - 40, 23, 2) or ["Step"]
        for j, line in enumerate(label):
            parts.append(_text(x + 18, top + 95 + j * 28, line, size=23, fill="@ink@", weight="bold"))
        parts.extend(_lines(x + 18, top + 95 + len(label) * 28 + 8, node.get("detail"), w - 40,
                            size=22, max_lines=4 - len(label), step=28))
        if i < n - 1:
            parts.append(_arrow(x + w + 3, top + 105, x + w + gap - 3, top + 105))


def _layout_spotlight(parts: list[str], plan: dict, headline: str, accent: list[str]) -> None:
    """Open title, a bold one-line spotlight, a ribbon of steps and a 2x2 detail grid."""
    hero, nodes = plan["hero"], plan["hero"]["nodes"]
    kicker = _fit_words(plan.get("badge"), 220, 22).upper() or "IN FOCUS"
    parts.append(_rect(40, 40, 300, 50, "@soft@", stroke="@soft_stroke@", radius=25))
    parts.append(_icon("sparkle", 58, 48, "@primary@", 1.3))
    parts.append(_text(100, 73, kicker, size=22, fill="@primary@", weight="bold"))
    title = _wrap(plan.get("title") or headline, 1000, 52, 2)
    for i, line in enumerate(title):
        parts.append(_text(40, 152 + i * 58, line, size=52, fill="@ink@", weight="bold"))
    bar_y = 172 + (len(title) - 1) * 58
    parts.append(_rect(40, bar_y, 120, 8, "@primary@", radius=4))
    parts.extend(_lines(40, bar_y + 40, plan.get("subtitle"), 1000, size=24, max_lines=1))

    lead = _clean(plan.get("tagline")) or _clean(hero.get("caption"))
    parts.append(_rect(40, 300, 1000, 96, "@strong@"))
    parts.append(_icon("bulb", 62, 330, "@on_strong@", 1.5))
    parts.append(_text(112, 342, _fit_words(lead, 900, 28), size=28, fill="@on_strong@",
                       weight="bold"))
    if _clean(plan.get("tagline")) and _clean(hero.get("caption")):
        parts.append(_text(112, 377, _fit_words(hero.get("caption"), 900, 22), size=22,
                           fill="@on_strong@"))

    _ribbon(parts, nodes, accent, 430, 210)
    parts.append(_text(45, 684, "IN PRACTICE", size=24, fill="@ink@", weight="bold"))
    _modules_grid(parts, plan, plan["modules"], accent, 700, 186, gap=10)


def _card_header(parts: list[str], plan: dict, headline: str, kicker: str, icon: str,
                 stripe: str = "@primary@") -> None:
    """White header card (y 35-215) with a coloured stripe on its left edge."""
    parts.append(_rect(40, 35, 1000, 180, "@card@", stroke="@card_stroke@"))
    parts.append(_rect(40, 35, 12, 180, stripe, radius=6))
    parts.append(_icon(icon, 72, 52, stripe, 1.3))
    parts.append(_text(114, 78, kicker, size=22, fill=stripe, weight="bold"))
    title = _wrap(plan.get("title") or headline, 930, 44, 2)
    for i, line in enumerate(title):
        parts.append(_text(72, 128 + i * 48, line, size=44, fill="@ink@", weight="bold"))
    parts.extend(_lines(72, 178 if len(title) == 1 else 203, plan.get("subtitle"), 930,
                        size=22, max_lines=1))


def _layout_comparison(parts: list[str], plan: dict, headline: str, accent: list[str]) -> None:
    """Old way and new way side by side in tinted panels, then a 2x2 detail grid."""
    hero, nodes = plan["hero"], plan["hero"]["nodes"]
    _card_header(parts, plan, headline, "WHAT CHANGED", "loop")

    columns = [(40, "@bad@", "@bad_soft@", "x", hero.get("left_label") or "Before", nodes[:2], 1),
               (560, "@good@", "@good_soft@", "check", hero.get("right_label") or "After", nodes[2:], 3)]
    for x, colour, tint, icon, heading, column, first in columns:
        parts.append(_rect(x, 235, 480, 410, tint, stroke=colour))
        parts.append(_icon(icon, x + 22, 256, colour, 1.5))
        parts.append(_text(x + 70, 284, _fit_words(heading, 380, 28), size=28, fill=colour,
                           weight="bold"))
        for k, node in enumerate(column):
            y = 300 + k * 165
            parts.append(_rect(x + 20, y, 440, 150, "@card@", stroke="@card_stroke@", radius=14)
                         .replace("<rect ", f'<rect data-motion-step="{first + k}" ', 1))
            parts.append(_icon(node.get("icon"), x + 38, y + 18, colour, 1.3))
            parts.append(_text(x + 80, y + 44, _fit_words(node.get("label"), 360, 24) or "Step",
                               size=24, fill="@ink@", weight="bold"))
            parts.extend(_lines(x + 40, y + 88, node.get("detail"), 400, size=22,
                                max_lines=2, step=29))
    parts.append(_arrow(524, 440, 554, 440))
    parts.append(_text(45, 684, _fit_words(hero.get("caption") or "In practice", 990, 24),
                       size=24, fill="@ink@", weight="bold"))
    _modules_grid(parts, plan, plan["modules"], accent, 700, 186, gap=10)


def _stats_module(plan: dict) -> dict | None:
    """The first stats module with at least two 'value | caption' lines."""
    for module in plan["modules"]:
        lines = module.get("lines") if isinstance(module.get("lines"), list) else []
        if (_clean(module.get("kind")).lower() == "stats"
                and sum("|" in str(line) for line in lines) >= 2):
            return module
    return None


def _code_module(plan: dict) -> dict | None:
    """The first code module that has at least one line of code."""
    for module in plan["modules"]:
        lines = module.get("lines") if isinstance(module.get("lines"), list) else []
        if _clean(module.get("kind")).lower() == "code" and any(_clean(x) for x in lines):
            return module
    return None


def _module_row(parts: list[str], modules: list, accent: list[str], top: int, h: int) -> None:
    """Two or three modules side by side."""
    k = len(modules)
    w = (1000 - 20 * (k - 1)) // k
    for i, module in enumerate(modules):
        _module(parts, module, 40 + i * (w + 20), top, w, h, i + 1, accent[i % len(accent)])


def _layout_dashboard(parts: list[str], plan: dict, headline: str, accent: list[str]) -> None:
    """Big number tiles first, then how it works, then the remaining details."""
    stats = _stats_module(plan)
    rest = [m for m in plan["modules"] if m is not stats]
    _card_header(parts, plan, headline, "BY THE NUMBERS", "chart")
    pairs = [str(line).partition("|") for line in stats["lines"] if "|" in str(line)][:4]
    k = len(pairs)
    w, size = (1000 - 16 * (k - 1)) // k, 44 if k <= 3 else 36
    for i, (value, _, caption) in enumerate(pairs):
        x, colour = 40 + i * (w + 16), accent[i % len(accent)]
        parts.append(_rect(x, 235, w, 170, "@card@", stroke="@card_stroke@"))
        parts.append(_rect(x, 235, w, 7, colour, radius=3))
        parts.append(_text(x + 22, 300, _fit_words(value, w - 44, size), size=size, fill=colour,
                           weight="bold"))
        parts.extend(_lines(x + 22, 342, caption, w - 44, size=22, max_lines=2, step=28))
    parts.append(_text(45, 445, "HOW IT WORKS", size=24, fill="@primary@", weight="bold"))
    _ribbon(parts, plan["hero"]["nodes"], accent, 460, 200)
    if len(rest) == 3:
        _modules_grid(parts, plan, rest, accent, 700, 186, gap=10)
        return
    _module_row(parts, rest, accent, 700, 186)
    lead = _clean(plan.get("tagline")) or _clean(plan["hero"].get("caption")) or plan["takeaway"]
    parts.append(_rect(40, 906, 1000, 176, "@soft@", stroke="@soft_stroke@"))
    parts.append(_icon("target", 64, 932, "@primary@", 1.5))
    parts.append(_text(114, 960, "WHY IT MATTERS", size=24, fill="@primary@", weight="bold"))
    parts.extend(_lines(64, 1010, lead, 940, size=28, max_lines=2, step=36,
                        fill="@soft_ink@", weight="bold"))


def _layout_code_focus(parts: list[str], plan: dict, headline: str, accent: list[str]) -> None:
    """The code takes centre stage in a wide panel; steps and details follow."""
    code = _code_module(plan)
    rest = [m for m in plan["modules"] if m is not code]
    _band_header(parts, plan, headline, "IN CODE", "terminal")
    parts.append(_rect(40, 275, 1000, 280, "@code_bg@", stroke="@code_bg@"))
    parts.append(_rect(40, 275, 1000, 7, "@a1@", radius=3))
    parts.append(_icon("code", 64, 298, "@code_icon@", 1.5))
    parts.append(_text(112, 327, _fit_words(code.get("heading") or "The code", 880, 25) or "The code",
                       size=25, fill="@code_ink@", weight="bold"))
    shown: list[str] = []
    for raw in code["lines"]:
        wrapped = _wrap_code(raw, 940, 22, 3)
        if len(shown) + len(wrapped) > 6:
            break
        shown.extend(wrapped)
    for i, line in enumerate(shown):
        parts.append(_text(64, 372 + i * 30, line, size=22, fill="@code_muted@",
                           family="Menlo, Courier New, monospace"))
    caption = _clean(plan["hero"].get("caption"))
    if len(shown) <= 3 and caption:
        # A short snippet leaves room to say what it is for, below a divider.
        parts.append('<line x1="64" y1="488" x2="1016" y2="488" stroke="@code_icon@" '
                     'stroke-width="1" stroke-dasharray="none"/>')
        parts.extend(_lines(64, 528, caption, 940, size=22, max_lines=1, fill="@code_ink@",
                            weight="bold"))
    parts.append(_text(45, 592, "HOW IT WORKS", size=24, fill="@primary@", weight="bold"))
    _ribbon(parts, plan["hero"]["nodes"], accent, 608, 200)
    _module_row(parts, rest, accent, 830, 255)


def _layout_incident(parts: list[str], plan: dict, headline: str, accent: list[str]) -> None:
    """Bug-fix story: what broke, how it was traced and the fix, one full-width row per step."""
    nodes = plan["hero"]["nodes"]
    _card_header(parts, plan, headline, "THE BUG AND THE FIX", "bug", stripe="@bad@")
    parts.append(_text(45, 262, "FROM SYMPTOM TO FIX", size=24, fill="@ink@", weight="bold"))
    n = len(nodes)
    h = (400 - 12 * (n - 1)) // n
    for i, node in enumerate(nodes):
        y = 280 + i * (h + 12)
        cy = y + h // 2
        colour = "@bad@" if i == 0 else "@good@" if i == n - 1 else accent[i % len(accent)]
        parts.append(_rect(40, y, 1000, h, "@card@", stroke="@card_stroke@", radius=14)
                     .replace("<rect ", f'<rect data-motion-step="{i + 1}" ', 1))
        parts.append(_rect(40, y, 8, h, colour, radius=4))
        parts.append(f'<circle cx="90" cy="{cy}" r="20" fill="{colour}"/>')
        parts.append(_text(84, cy + 8, str(i + 1), size=22, fill="@bg@", weight="bold"))
        parts.append(_icon(node.get("icon"), 126, cy - 17, colour, 1.4))
        parts.append(_text(172, cy + 8, _fit_words(node.get("label"), 280, 24) or "Step",
                           size=24, fill="@ink@", weight="bold"))
        parts.append(_text(470, cy + 8, _fit_words(node.get("detail"), 545, 22), size=22,
                           fill="@muted@"))
    _modules_grid(parts, plan, plan["modules"], accent, 700, 186, gap=10)


def _layout_stack(parts: list[str], plan: dict, headline: str, accent: list[str]) -> None:
    """A pyramid of layers, narrowest on top, then a 2x2 detail grid."""
    hero, nodes = plan["hero"], plan["hero"]["nodes"]
    layered = _clean(hero.get("form")).lower() == "layers"
    _soft_header(parts, plan, headline, "LAYER BY LAYER" if layered else "THE BIG PICTURE",
                 "layers")
    parts.append(_text(45, 266, _fit_words(hero.get("caption") or "How it fits together", 990, 24),
                       size=24, fill="@ink@", weight="bold"))
    n = len(nodes)
    h = (395 - 10 * (n - 1)) // n
    for i, node in enumerate(nodes):
        inset = (n - 1 - i) * 30
        x, y, w = 40 + inset, 285 + i * (h + 10), 1000 - 2 * inset
        cy, colour = 285 + i * (h + 10) + h // 2, accent[i % len(accent)]
        parts.append(_rect(x, y, w, h, "@card@" if i % 2 else "@soft2@", stroke="@card_stroke@",
                           radius=12).replace("<rect ", f'<rect data-motion-step="{i + 1}" ', 1))
        parts.append(_rect(x, y, 8, h, colour, radius=4))
        parts.append(_icon(node.get("icon"), x + 24, cy - 17, colour, 1.4))
        parts.append(_text(x + 70, cy + 8, str(i + 1), size=22, fill=colour, weight="bold"))
        parts.append(_text(x + 105, cy + 8, _fit_words(node.get("label"), 230, 24) or "Layer",
                           size=24, fill="@ink@", weight="bold"))
        parts.append(_text(x + 350, cy + 8, _fit_words(node.get("detail"), w - 370, 22),
                           size=22, fill="@muted@"))
    _modules_grid(parts, plan, plan["modules"], accent, 700, 186, gap=10)


_SIDEBAR_TITLE = (270, 34)  # wrap width and font size of the sidebar title


def _sidebar_fits(plan: dict, headline: str) -> bool:
    """The narrow sidebar title needs short words and at most four lines."""
    width, size = _SIDEBAR_TITLE
    limit = max(7, int(width / (size * 0.61)))
    title = _clean(plan.get("title") or headline)
    return (all(len(word) <= limit for word in title.split())
            and len(_wrap(title, width, size, 99)) <= 4)


def _layout_sidebar(parts: list[str], plan: dict, headline: str, accent: list[str]) -> None:
    """A tall coloured sidebar holds the title and hook; steps and details fill the right."""
    hero, nodes = plan["hero"], plan["hero"]["nodes"]
    parts.append(_rect(40, 35, 330, 1050, "@strong@"))
    parts.append(_icon("sparkle", 64, 62, "@on_strong@", 1.3))
    parts.append(_text(104, 86, _fit_words(plan.get("badge"), 230, 22).upper() or "EXPLAINER",
                       size=22, fill="@on_strong@", weight="bold"))
    title = _wrap(plan.get("title") or headline, *_SIDEBAR_TITLE, 4)
    for i, line in enumerate(title):
        parts.append(_text(64, 160 + i * 44, line, size=34, fill="@on_strong@", weight="bold"))
    bar = 160 + (len(title) - 1) * 44 + 26
    parts.append(_rect(64, bar, 80, 6, "@on_strong@", radius=3))
    parts.extend(_lines(64, bar + 46, plan.get("subtitle"), 280, size=22, max_lines=4, step=29,
                        fill="@on_strong@"))
    parts.append(_icon("bulb", 64, 640, "@on_strong@", 1.5))
    lead = _clean(plan.get("tagline")) or _clean(hero.get("caption")) or plan["takeaway"]
    parts.extend(_lines(64, 712, lead, 280, size=26, max_lines=4, step=34, fill="@on_strong@",
                        weight="bold"))
    if _clean(plan.get("tagline")) and _clean(hero.get("caption")):
        parts.extend(_lines(64, 900, hero.get("caption"), 280, size=22, max_lines=3, step=29,
                            fill="@on_strong@"))

    parts.append(_text(395, 72, "HOW IT WORKS", size=24, fill="@primary@", weight="bold"))
    n = len(nodes)
    h = min(180, (590 - 12 * (n - 1)) // n)
    for i, node in enumerate(nodes):
        y, colour = 90 + i * (h + 12), accent[i % len(accent)]
        parts.append(_rect(390, y, 650, h, "@card@", stroke="@card_stroke@", radius=14)
                     .replace("<rect ", f'<rect data-motion-step="{i + 1}" ', 1))
        parts.append(_rect(390, y, 6, h, colour, radius=3))
        parts.append(_icon(node.get("icon"), 412, y + 18, colour, 1.4))
        parts.append(_text(996, y + 44, str(i + 1), size=24, fill=colour, weight="bold"))
        parts.append(_text(460, y + 44, _fit_words(node.get("label"), 500, 24) or "Step",
                           size=24, fill="@ink@", weight="bold"))
        parts.extend(_lines(412, y + 82, node.get("detail"), 600, size=22,
                            max_lines=max(1, min(3, (h - 70) // 29)), step=29))
    _modules_grid(parts, plan, plan["modules"], accent, 700, 186, gap=10, left=390, width=315)


_LAYOUTS = {"guide": _layout_guide, "timeline": _layout_timeline,
            "spotlight": _layout_spotlight, "comparison": _layout_comparison,
            "dashboard": _layout_dashboard, "code_focus": _layout_code_focus,
            "incident": _layout_incident, "stack": _layout_stack, "sidebar": _layout_sidebar}
# What each layout suits; the planner sees this list and may suggest one.
LAYOUT_HINTS = {
    "comparison": "an old way contrasted with a new way (before_after hero)",
    "dashboard": "posts driven by numbers: benchmarks, metrics, version stats",
    "code_focus": "posts where a code snippet is the main point",
    "incident": "bug fixes, breaking changes, outages and their fixes",
    "stack": "architectures and layered systems",
    "timeline": "step-by-step how-tos and migrations",
    "spotlight": "releases and announcements with one big idea",
    "sidebar": "concepts and explainers",
    "guide": "general technical field guides",
}
POST_TYPES = ("release", "bug_fix", "how_to", "concept", "comparison", "benchmark", "architecture")


def _eligible(plan: dict, headline: str = "") -> list[str]:
    """Layouts that can draw this content cleanly, in a stable order."""
    hero, modules = plan["hero"], plan["modules"]
    n, form = len(hero["nodes"]), _clean(hero.get("form")).lower()
    post_type = _clean(plan.get("post_type")).lower()
    has_stats = any(_clean(m.get("kind")).lower() == "stats" for m in modules)
    ok = {
        "guide": True,
        "timeline": True,
        "spotlight": n <= 4,  # a ribbon of five is too narrow for the labels
        "comparison": form == "before_after" and n == 4,
        "dashboard": n <= 4 and _stats_module(plan) is not None,
        # The details sit in one row; a stats card there would be too narrow for its captions.
        "code_focus": (n <= 4 and _code_module(plan) is not None
                       and not (len(modules) == 4 and has_stats)),
        "incident": post_type in ("bug_fix", "breaking_change", "incident"),
        "stack": True,
        "sidebar": not has_stats and _sidebar_fits(plan, headline),
    }
    return [s for s in STYLES if ok[s]]


def _style_candidates(plan: dict, headline: str = "") -> list[str]:
    """Layouts that suit this content, best first: the planner's pick, then by content type."""
    hero, modules = plan["hero"], plan["modules"]
    n, form = len(hero["nodes"]), _clean(hero.get("form")).lower()
    post_type = _clean(plan.get("post_type")).lower()
    kinds = {_clean(m.get("kind")).lower() for m in modules}
    order = [_clean(plan.get("layout")).lower()]
    if form == "before_after":
        order.append("comparison")
    if post_type in ("bug_fix", "breaking_change", "incident"):
        order.append("incident")
    if post_type == "benchmark" or "stats" in kinds:
        order += ["dashboard", "spotlight"]
    if "code" in kinds:
        order.append("code_focus")
    if post_type == "release":
        order += ["spotlight", "dashboard"]
    if form == "layers" or post_type == "architecture":
        order += ["stack", "timeline"]
    if post_type == "how_to" or n >= 4:
        order.append("timeline")
    if post_type == "concept":
        order += ["sidebar", "stack"]
    order += ["sidebar", "spotlight", "timeline", "guide", "stack"]
    eligible = _eligible(plan, headline)
    out: list[str] = []
    for style in order:
        if style in eligible and style not in out:
            out.append(style)
    return out


def _recent(value: str | list | tuple | None) -> list[str]:
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value or ()]


def choose_style(plan: dict, recent: str | list | tuple | None = None, headline: str = "") -> str:
    """The best-suited layout not used in the last three posters (or at least not the last one)."""
    recent = _recent(recent)
    candidates = _style_candidates(plan, headline)
    fresh = [s for s in candidates if s not in recent[-3:]]
    return (fresh or [s for s in candidates if s not in recent[-1:]])[0]


def choose_theme(plan: dict, recent: str | list | tuple | None = None) -> str:
    """The planner's suggested palette, or a stable pick from the title; never one of the last two."""
    recent = _recent(recent)[-2:]
    hint = _clean(plan.get("theme")).lower()
    if hint in THEMES and hint not in recent:
        return hint
    names = [t for t in THEMES if t not in recent]
    seed = sum(ord(c) for c in _clean(plan.get("title")) + _clean(plan.get("takeaway")))
    return names[seed % len(names)]


def poster_from_brief(brief: str, headline: str, footer: str, *,
                      recent_styles: str | list | tuple | None = None,
                      recent_themes: str | list | tuple | None = None, style: str | None = None,
                      theme: str | None = None) -> str | None:
    """Render a complete poster from the blueprint embedded by plan_infographic.

    The layout and colour theme follow the content and always differ from the previous poster's
    (recent_styles, recent_themes, oldest first). style/theme force a choice, which the tests use to cover every pair.
    """
    if MARKER not in brief:
        return None
    try:
        plan = json.loads(brief.split(MARKER, 1)[1].strip())
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(plan, dict):
        return None
    hero = plan.get("hero")
    modules = plan.get("modules")
    if (not isinstance(hero, dict) or not isinstance(hero.get("nodes"), list)
            or not 3 <= len(hero["nodes"]) <= 5 or not isinstance(modules, list)
            or not 3 <= len(modules) <= 4
            or not all(isinstance(item, dict) for item in hero["nodes"] + modules)
            or not isinstance(plan.get("gotcha"), dict)
            or not _clean(plan.get("takeaway"))):
        return None

    if style not in _eligible(plan, headline):
        style = choose_style(plan, recent_styles, headline)
    if theme not in THEMES:
        theme = choose_theme(plan, recent_themes)
    parts: list[str] = []
    _start(parts, style, theme)
    _LAYOUTS[style](parts, plan, headline, list(ACCENTS))
    _bottom(parts, plan, footer)
    parts.append("</svg>")
    return _apply_theme("".join(parts), theme)
