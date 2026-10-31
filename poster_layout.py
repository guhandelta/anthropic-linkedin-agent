"""Predictable, readable SVG poster layout for an LLM-authored content blueprint.

The model chooses the facts and sections; this module owns positions, wrapping,
contrast, and the reading order. It never invents technical claims.
"""

from __future__ import annotations

import json
from html import escape


MARKER = "CONTENT BLUEPRINT (draw exactly this content; every fact comes from the post):"


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


def _text(x: int, y: int, value: object, *, size: int = 22, fill: str = "#132238",
          weight: str = "normal", family: str = "Arial, DejaVu Sans, sans-serif") -> str:
    return (f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" '
            f'font-family="{family}" fill="{fill}">{escape(_clean(value))}</text>')


def _lines(x: int, y: int, value: object, width: int, *, size: int = 22,
           max_lines: int = 2, step: int = 28, fill: str = "#42536B",
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
    parts.append(_rect(x, y, w, h, "#F2F6FC", stroke="#DCE6F3", radius=15)
                 .replace("<rect ", f'<rect data-motion-step="{number}" ', 1))
    parts.append(_rect(x, y, 6, h, accent, radius=3))
    parts.append(_icon(node.get("icon"), x + 20, y + 18, accent, 1.6))
    parts.append(_text(x + 68, y + 39, str(number), size=22, fill=accent, weight="bold"))
    label = _wrap(node.get("label"), w - 40, 25, 2)
    for j, line in enumerate(label or ["Step"]):
        parts.append(_text(x + 20, y + 85 + j * 29, line, size=25,
                           fill="#132238", weight="bold"))
    detail_y = y + (144 if len(label) > 1 else 119)
    parts.extend(_lines(x + 20, detail_y, node.get("detail"), w - 40,
                        size=22, max_lines=1 if len(label) > 1 else 2, step=29))


def _module(parts: list[str], module: dict, x: int, y: int, w: int, h: int,
            number: int, accent: str) -> None:
    kind = _clean(module.get("kind")).lower()
    code = kind == "code"
    bg = "#15253D" if code else "#FFFFFF"
    ink = "#FFFFFF" if code else "#132238"
    muted = "#DCE8F7" if code else "#42536B"
    parts.append(_rect(x, y, w, h, bg, stroke="#DCE6F3" if not code else "#15253D"))
    parts.append(_rect(x, y, w, 7, accent, radius=3))
    parts.append(_icon(module.get("icon"), x + 20, y + 22, "#9FC5FF" if code else accent, 1.5))
    heading = _fit_words(module.get("heading"), w - 100, 25)
    parts.append(_text(x + 68, y + 52, f"{number}. {heading or 'Key point'}",
                       size=25, fill=ink, weight="bold"))
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
        wrapped = (_wrap_code if code else _wrap)(raw, w - 60, 22, 2)
        group = [("• " if j == 0 and not code else "  " if not code else "") + line
                 for j, line in enumerate(wrapped)]
        if len(content) + len(group) > 4:
            break  # Drop whole overflow items instead of cutting text mid-sentence
        content.extend(group)
    for i, line in enumerate(content[:4]):
        parts.append(_text(x + 24, y + 84 + i * 28, line, size=22,
                           fill=muted, family="Menlo, Courier New, monospace" if code else
                           "Arial, DejaVu Sans, sans-serif"))


def poster_from_brief(brief: str, headline: str, footer: str) -> str | None:
    """Render a complete poster from the blueprint embedded by plan_infographic."""
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

    parts = ['<svg viewBox="0 0 1080 1350" data-layout="structured" xmlns="http://www.w3.org/2000/svg">',
             _rect(0, 0, 1080, 1350, "#F7F9FC", radius=0),
             '<defs><marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" '
             'markerWidth="6" markerHeight="6" orient="auto"><path d="M 0 1 L 9 5 L 0 9 Z" '
             'fill="#3768B7" stroke-dasharray="none"/></marker></defs>']
    parts.append(_rect(40, 35, 1000, 185, "#E9F0FD", stroke="#D5E3F8"))
    parts.append(_icon("sparkle", 65, 55, "#3768B7", 1.4))
    parts.append(_text(110, 83, "TECHNICAL FIELD GUIDE", size=22, fill="#3768B7", weight="bold"))
    title = _wrap(plan.get("title") or headline, 940, 46, 2)
    for i, line in enumerate(title):
        parts.append(_text(65, 132 + i * 51, line, size=46, fill="#132238", weight="bold"))
    subtitle_y = 193 if len(title) == 1 else 211
    parts.extend(_lines(65, subtitle_y, plan.get("subtitle"), 940, size=22, max_lines=1))

    parts.append(_rect(40, 242, 1000, 388, "#FFFFFF", stroke="#DCE6F3"))
    parts.append(_text(65, 280, "HOW IT WORKS", size=26, fill="#3768B7", weight="bold"))
    parts.extend(_lines(65, 313, hero.get("caption"), 930, size=22, max_lines=1))
    nodes = hero["nodes"]
    accent = ["#3768B7", "#7A4CC2", "#1D9369", "#C66B2E", "#2F7F9B"]
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
            parts.append(_rect(x, y, width, height, "#F2F6FC", stroke="#DCE6F3", radius=15)
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
                                   fill="#42536B"))
        else:
            _node(parts, node, x, y, width, height, i, accent[i - 1])
    if len(nodes) == 3:
        for x in (376, 707):
            parts.append(f'<line x1="{x}" y1="440" x2="{x + 18}" y2="440" '
                         'stroke="#3768B7" stroke-width="3" stroke-dasharray="10 10" '
                         'marker-end="url(#arrow)"/>')
        tagline = _clean(plan.get("tagline"))
        if tagline:
            parts.append(_rect(65, 550, 950, 51, "#E9F0FD", radius=10))
            parts.append(_icon("bulb", 82, 559, "#3768B7", 1.3))
            parts.extend(_lines(123, 584, tagline, 850, size=22, max_lines=1,
                                fill="#315DA5", weight="bold"))
    else:
        for x in (376, 707):
            parts.append(f'<line x1="{x}" y1="403" x2="{x + 18}" y2="403" '
                         'stroke="#3768B7" stroke-width="3" stroke-dasharray="10 10" '
                         'marker-end="url(#arrow)"/>')
        if len(nodes) == 4:
            parts.append('<path d="M 880 465 C 880 472 750 465 700 485" fill="none" '
                         'stroke="#3768B7" stroke-width="3" stroke-dasharray="10 10" '
                         'marker-end="url(#arrow)"/>')
        else:
            parts.append('<path d="M 880 465 C 880 472 850 468 780 485" fill="none" '
                         'stroke="#3768B7" stroke-width="3" stroke-dasharray="10 10" '
                         'marker-end="url(#arrow)"/>')

    parts.append(_text(45, 678, "THE PRACTICAL DETAILS", size=26,
                       fill="#132238", weight="bold"))
    for i, module in enumerate(modules):
        x = 40 if i % 2 == 0 else 550
        y = 698 if i < 2 else 900
        _module(parts, module, x, y, 490, 187, i + 1, accent[i % len(accent)])
    if len(modules) == 3:
        parts.append(_rect(550, 900, 490, 187, "#EEF4FD", stroke="#DCE6F3"))
        parts.append(_icon("target", 575, 925, "#3768B7", 1.5))
        parts.append(_text(620, 952, "APPLICATION", size=25, fill="#132238", weight="bold"))
        parts.extend(_lines(575, 995, plan.get("tagline") or plan.get("takeaway"), 430,
                            size=22, max_lines=3, step=29))

    gotcha = plan["gotcha"]
    parts.append(_rect(40, 1105, 1000, 74, "#FFF3DD", stroke="#E5B967"))
    parts.append(_icon("warning", 60, 1120, "#B46A16", 1.5))
    parts.append(_text(110, 1139, _wrap(gotcha.get("heading") or "Watch out", 250, 24, 1)[0],
                       size=24, fill="#8A4C0B", weight="bold"))
    parts.extend(_lines(110, 1165, gotcha.get("text"), 900, size=22, max_lines=1,
                        fill="#5B421E"))

    parts.append(_rect(40, 1192, 1000, 72, "#315DA5"))
    parts.append(_icon("bulb", 60, 1208, "#FFFFFF", 1.5))
    parts.extend(_lines(110, 1235, plan["takeaway"], 900, size=25, max_lines=1,
                        fill="#FFFFFF", weight="bold"))
    parts.append('<line x1="60" y1="1285" x2="1020" y2="1285" stroke="#CBD5E1" '
                 'stroke-width="2" stroke-dasharray="none"/>')
    parts.append(_text(60, 1321, footer, size=22, fill="#5B6B83"))
    parts.append("</svg>")
    return "".join(parts)
