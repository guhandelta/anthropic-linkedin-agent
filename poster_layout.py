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
# Twenty-nine more palettes, each built from a short brand palette (see poster_palettes.py).
from poster_palettes import EXTRA_HINTS, EXTRA_THEMES  # noqa: E402

THEMES.update(EXTRA_THEMES)
THEME_HINTS.update(EXTRA_HINTS)
ACCENTS = ("@a1@", "@a2@", "@a3@", "@a4@", "@a5@")
STYLES = ("guide", "timeline", "spotlight", "comparison", "dashboard", "code_focus", "incident",
          "stack", "sidebar", "matrix", "versus", "architecture", "progression", "hub",
          "profiles", "columns", "zigzag", "playbook", "scorecard", "swimlanes", "twin",
          "flowchart", "pipeline", "snake", "proscons", "masonry")


def _clean(value: object) -> str:
    return " ".join(str(value or "").split())


# Text that had to be shortened while drawing the current poster. poster_from_brief tries another
# layout when this is not empty, so a reader never sees a phrase cut off mid-thought.
_CUTS: list[str] = []


def _wrap(value: object, width: int, font_size: int, max_lines: int) -> list[str]:
    """Conservatively wrap SVG text, which has no native line wrapping."""
    text = _clean(value)
    limit = max(7, int(width / (font_size * 0.61)))
    words = text.split()
    lines: list[str] = []
    line = ""
    for word in words:
        if len(word) > limit:
            _CUTS.append(word)
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
        _CUTS.append(text)
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
            _CUTS.append(_clean(value))
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
        _CUTS.append(text)
        text = text[:limit - 1] + "…"
    lines.append(text)
    return lines


def _text(x: int, y: int, value: object, *, size: int = 22, fill: str = "@ink@",
          weight: str = "normal", family: str = "Arial, DejaVu Sans, sans-serif",
          anchor: str = "start") -> str:
    centred = ' text-anchor="middle"' if anchor == "middle" else ""
    return (f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}"{centred} '
            f'font-family="{family}" fill="{fill}">{escape(_clean(value))}</text>')


def _lines(x: int, y: int, value: object, width: int, *, size: int = 22,
           max_lines: int = 2, step: int = 28, fill: str = "@muted@",
           weight: str = "normal") -> list[str]:
    return [_text(x, y + i * step, line, size=size, fill=fill, weight=weight)
            for i, line in enumerate(_wrap(value, width, size, max_lines))]


def _rect(x: int, y: int, w: int, h: int, fill: str, *, stroke: str = "none",
          radius: int = 18) -> str:
    if 12 <= radius <= 20:
        # Cards follow the poster's corner style; thin strips, pills and circles keep their shape.
        radius = {"square": 4, "soft": radius + 8}.get(_VARIANT.get("corners", "round"), radius)
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


STAT_KINDS = ("stats", "chart")
_NUMBER = re.compile(r"^\s*([~≈<>]?\s*[$€£]?)\s*(\d+(?:[.,]\d+)*)\s*(.*?)\s*$")


def _number(value: object) -> tuple[float, str] | None:
    """A leading number and its unit ("45%" -> (45, "%"), "120 ms" -> (120, "ms")), or None."""
    match = _NUMBER.match(_clean(value))
    if not match or len(match.group(3)) > 8:
        return None
    digits = match.group(2)
    digits = digits.replace(",", "") if re.fullmatch(r"\d{1,3}(,\d{3})+", digits) else digits.replace(",", ".")
    try:
        number = float(digits)
    except ValueError:
        return None
    unit = (match.group(1).replace(" ", "").lstrip("~≈<>") + match.group(3)).lower()
    return number, unit


def _pairs(lines: object) -> list[tuple[str, str]]:
    """The 'value | caption' lines of a stats or chart module."""
    if not isinstance(lines, list):
        return []
    out = []
    for line in lines:
        value, bar, caption = str(line).partition("|")
        if bar and _clean(value) and _clean(caption):
            out.append((_clean(value), _clean(caption)))
    return out


def _comparable(lines: object, chart: bool = False) -> bool:
    """True when the values can share one bar chart: two or more numbers in the same unit.

    Unitless numbers (a version, a count of new hooks) only chart when the planner asked for one.
    """
    pairs = _pairs(lines)[:4]
    numbers = [_number(value) for value, _ in pairs]
    if len(pairs) < 2 or any(n is None for n in numbers):
        return False
    units = {unit for _, unit in numbers}
    return len(units) == 1 and (chart or units != {""}) and max(n for n, _ in numbers) > 0


def _bars(parts: list[str], pairs: list[tuple[str, str]], x: int, y: int, w: int, step: int,
          accent: str | list[str], muted: str) -> None:
    """A horizontal bar chart: caption, a bar scaled to the largest value, then the value."""
    numbers = [(_number(value) or (0.0, ""))[0] for value, _ in pairs]
    top = max(numbers) or 1
    caption_w = int(w * 0.42)
    value_w = max(90, int(max(len(v) for v, _ in pairs) * 22 * 0.61) + 10)
    bar_x, bar_max = x + caption_w + 12, w - caption_w - 12 - value_w - 10
    for i, ((value, caption), number) in enumerate(zip(pairs, numbers)):
        row = y + i * step
        parts.append(_text(x, row, _fit_words(caption, caption_w, 22), size=22, fill=muted))
        colour = accent[i % len(accent)] if isinstance(accent, list) else accent
        length = max(18, int(bar_max * number / top))
        parts.append(_rect(bar_x, row - 16, length, 18, colour, radius=9)
                     .replace("<rect ", '<rect data-motion-grow="1" ', 1))
        parts.append(_text(bar_x + length + 10, row, value, size=22, fill=colour, weight="bold"))


def _ring(parts: list[str], cx: int, cy: int, r: int, percent: float, colour: str) -> None:
    """A progress ring for a percentage (the arc is solid, so the GIF does not dash it)."""
    import math

    share = min(max(percent, 0.0), 100.0) / 100
    parts.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="@soft_stroke@" '
                 f'stroke-width="9"/>')
    if share >= 0.999:
        parts.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{colour}" '
                     f'stroke-width="9"/>')
        return
    if share <= 0:
        return
    angle = 2 * math.pi * share - math.pi / 2
    ex, ey = cx + r * math.cos(angle), cy + r * math.sin(angle)
    large = 1 if share > 0.5 else 0
    parts.append(f'<path d="M {cx} {cy - r} A {r} {r} 0 {large} 1 {ex:.1f} {ey:.1f}" fill="none" '
                 f'stroke="{colour}" stroke-width="9" stroke-linecap="round" '
                 f'stroke-dasharray="none"/>')


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
    if kind in STAT_KINDS and w >= 450 and _comparable(raw_lines, kind == "chart"):
        _bars(parts, _pairs(raw_lines)[:4], x + 24, y + 84, w - 48, 28, accent, muted)
        return
    if kind in STAT_KINDS and any("|" in str(r) for r in raw_lines):
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


def _counting(svg_text: str, value: object) -> str:
    """Mark a plain number (40%, ~$3.5M, 3x) so the "count" motion counts it up from zero.

    Values that are not plain numbers, such as a version like v2.1, stay as they are.
    """
    if _number(value) is None:
        return svg_text
    return svg_text.replace("<text ", '<text data-motion-count="1" ', 1)


def _half(parts: list[str], side: str | None = None) -> None:
    """Open (side "left" or "right") or close a group the "slide" motion moves in from its side."""
    parts.append(f'<g data-motion-part="{side}">' if side else "</g>")


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


# How the lower half and the bottom strip are drawn on the current poster. _render sets them, so
# the same layout can end in a 2x2 grid, full-width rows, a checklist or tall tabs, and finish with
# bars, two side-by-side cards or a quote card.
DETAILS = ("grid", "rows", "checklist", "tabs")
FINISHES = ("bars", "split", "quote")
# The header treatment and card corners vary too: "classic" is each header's original look, "bold"
# adds a filled kicker tab or decoration, "minimal" drops the box for an accent bar and a rule.
HEADERS = ("classic", "bold", "minimal")
CORNERS = ("round", "square", "soft")
_VARIANT = {"details": "grid", "finish": "bars", "header": "classic", "corners": "round",
            "origin": (540, 130)}
# Each layout's own header look when nothing else is chosen, so layouts that share a header helper
# still open differently.
HEADER_DEFAULTS = {
    "timeline": "classic", "code_focus": "bold", "architecture": "minimal", "playbook": "bold",
    "snake": "minimal", "proscons": "classic", "guide": "classic", "comparison": "bold",
    "dashboard": "minimal", "incident": "classic", "stack": "minimal", "progression": "bold",
    "hub": "classic", "swimlanes": "bold", "pipeline": "minimal", "matrix": "classic",
    "versus": "bold", "profiles": "minimal", "columns": "classic", "zigzag": "bold",
    "scorecard": "minimal", "twin": "classic", "flowchart": "bold", "masonry": "minimal",
}


def details_options(plan: dict) -> list[str]:
    """Detail styles that suit these modules."""
    modules = plan["modules"]
    has_code = any(_clean(m.get("kind")).lower() == "code" for m in modules)
    out = ["grid", "rows"]
    if not has_code:
        out.append("checklist")  # code reads badly as a checklist line
    if len(modules) == 3 and not has_code:
        out.append("tabs")  # a code line rarely fits a third of the page
    return out


def _limit(width: int, size: int) -> int:
    return max(7, int(width / (size * 0.61)))


def _fits(text: str, width: int, size: int, max_lines: int) -> bool:
    """True when the text wraps into max_lines without shortening any word (records nothing)."""
    limit, lines, line = _limit(width, size), 0, ""
    for word in _clean(text).split():
        if len(word) > limit:
            return False
        candidate = f"{line} {word}".strip()
        if len(candidate) > limit and line:
            lines, line = lines + 1, word
        else:
            line = candidate
    return lines + (1 if line else 0) <= max_lines


def _module_items(module: dict) -> tuple[list[str], bool]:
    """A module's lines as display items, and whether they are code."""
    kind = _clean(module.get("kind")).lower()
    raw = module.get("lines") if isinstance(module.get("lines"), list) else []
    if kind == "code":
        return [str(x).rstrip() for x in raw if _clean(x)], True
    if kind in STAT_KINDS:
        return [" ".join(_clean(part) for part in str(x).split("|", 1)) for x in raw if _clean(x)], False
    return [_clean(x) for x in raw if _clean(x)], False


def _joined(items: list[str], width: int, size: int, max_lines: int) -> str:
    """As many whole items as fit, joined with a middle dot; an item never gets cut."""
    out: list[str] = []
    for item in items:
        if _fits(" · ".join(out + [item]), width, size, max_lines):
            out.append(item)
    return " · ".join(out)


def _code_lines(items: list[str], width: int, max_lines: int) -> list[str]:
    """Whole code lines that fit on one line each (verbatim, never wrapped or cut)."""
    limit = int(width / (22 * 0.61))
    return [line for line in items if len(line) <= limit][:max_lines]


def _details_rows(parts: list[str], plan: dict, modules: list, accent: list[str], top: int) -> None:
    """One full-width row per module: a coloured number block, the heading and its points."""
    n = len(modules)
    h = (1085 - top - 10 * (n - 1)) // n
    budget = max(1, (h - 52) // 27)
    for i, module in enumerate(modules):
        y, colour = top + i * (h + 10), accent[i % len(accent)]
        items, code = _module_items(module)
        parts.append(_rect(40, y, 1000, h, "@code_bg@" if code else "@card@",
                           stroke="@code_bg@" if code else "@card_stroke@", radius=14))
        parts.append(_rect(40, y, 64, h, colour, radius=14))
        parts.append(_text(72, y + h // 2 + 9, str(i + 1), size=26, fill="@bg@", weight="bold",
                           anchor="middle"))
        parts.append(_icon(module.get("icon"), 122, y + 14, "@code_icon@" if code else colour, 1.3))
        parts.append(_text(162, y + 38, _fit_words(module.get("heading") or "Key point", 840, 24),
                           size=24, fill="@code_ink@" if code else "@ink@", weight="bold"))
        if code:
            for j, line in enumerate(_code_lines(items, 900, budget)):
                parts.append(_text(124, y + 70 + j * 27, line, size=22, fill="@code_muted@",
                                   family="Menlo, Courier New, monospace"))
        else:
            parts.extend(_lines(124, y + 70, _joined(items, 890, 22, budget), 890, size=22,
                                max_lines=budget, step=27))


def _details_checklist(parts: list[str], plan: dict, modules: list, accent: list[str],
                       top: int) -> None:
    """One tinted card holding every module as a ticked item, split by thin dividers."""
    n = len(modules)
    parts.append(_rect(40, top, 1000, 1085 - top, "@soft2@", stroke="@soft_stroke@"))
    h = (1085 - top - 20) // n
    budget = max(1, (h - 50) // 27)
    for i, module in enumerate(modules):
        y, colour = top + 10 + i * h, accent[i % len(accent)]
        items, _ = _module_items(module)
        if i:
            parts.append(f'<line x1="70" y1="{y}" x2="1010" y2="{y}" stroke="@soft_stroke@" '
                         'stroke-width="1.5" stroke-dasharray="none"/>')
        parts.append(f'<circle cx="86" cy="{y + 32}" r="20" fill="{colour}"/>')
        parts.append(_icon("check", 74, y + 20, "@bg@", 1.0))
        parts.append(_text(126, y + 41, _fit_words(module.get("heading") or "Key point", 860, 24),
                           size=24, fill="@ink@", weight="bold"))
        parts.extend(_lines(126, y + 72, _joined(items, 870, 22, budget), 870, size=22,
                            max_lines=budget, step=27))


def _details_tabs(parts: list[str], plan: dict, modules: list, accent: list[str], top: int) -> None:
    """Three tall cards side by side, each under a coloured tab with its heading."""
    w, h = 320, 1085 - top
    for i, module in enumerate(modules):
        x, colour = 40 + i * (w + 20), accent[i % len(accent)]
        items, code = _module_items(module)
        parts.append(_rect(x, top, w, h, "@code_bg@" if code else "@card@",
                           stroke="@code_bg@" if code else "@card_stroke@"))
        parts.append(_rect(x, top, w, 92, colour))
        parts.append(_icon(module.get("icon"), x + 18, top + 14, "@bg@", 1.2))
        parts.append(_text(x + 56, top + 36, f"{i + 1}.", size=22, fill="@bg@", weight="bold"))
        parts.extend(_lines(x + 18, top + 72, module.get("heading") or "Key point", w - 36,
                            size=22, max_lines=1, fill="@bg@", weight="bold"))
        y = top + 132
        for item in items:
            if code:
                if len(item) > int((w - 36) / (22 * 0.61)):
                    continue
                if y > top + h - 20:
                    break
                parts.append(_text(x + 18, y, item, size=22, fill="@code_muted@",
                                   family="Menlo, Courier New, monospace"))
                y += 30
                continue
            rows = (top + h - 16 - y) // 28 + 1
            if rows < 1:
                break
            if not _fits(item, w - 60, 22, min(3, rows)):
                continue
            parts.append(f'<circle cx="{x + 24}" cy="{y - 7}" r="5" fill="{colour}"/>')
            wrapped = _wrap(item, w - 60, 22, 3)
            parts.extend(_text(x + 40, y + j * 28, line, size=22, fill="@muted@")
                         for j, line in enumerate(wrapped))
            y += len(wrapped) * 28 + 12


def _modules_grid(parts: list[str], plan: dict, modules: list, accent: list[str],
                  top: int, h: int, gap: int = 16, left: int = 40, width: int = 490,
                  col_gap: int = 20) -> None:
    """Two columns of modules; a third module gets an APPLICATION card beside it.

    A full-width grid is swapped for the poster's chosen detail style (rows, checklist or tabs).
    """
    style = _VARIANT["details"]
    if left == 40 and width >= 490 and style in details_options({"modules": modules}):
        if style == "rows":
            return _details_rows(parts, plan, modules, accent, top)
        if style == "checklist":
            return _details_checklist(parts, plan, modules, accent, top)
        if style == "tabs":
            return _details_tabs(parts, plan, modules, accent, top)
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
    """Watch-out, takeaway and footer, drawn in the poster's chosen finish (y 1098-1340).

    bars: two full-width strips. split: two cards side by side. quote: the takeaway as a large
    quote card with the watch-out as a slim strip under it. Text always gets room for every word.
    """
    finish = _VARIANT["finish"]
    gotcha = plan["gotcha"]
    heading = gotcha.get("heading") or "Watch out"
    if finish == "split":
        parts.append(_rect(40, 1098, 490, 182, "@warn_bg@", stroke="@warn_stroke@"))
        parts.append(_icon("warning", 60, 1114, "@warn_icon@", 1.4))
        parts.append(_text(104, 1140, _fit_words(heading, 400, 24), size=24, fill="@warn_head@",
                           weight="bold"))
        parts.extend(_lines(60, 1176, gotcha.get("text"), 445, size=22, max_lines=4, step=26,
                            fill="@warn_text@"))
        parts.append(_rect(550, 1098, 490, 182, "@strong@"))
        parts.append(_icon("bulb", 570, 1114, "@on_strong@", 1.4))
        parts.append(_text(614, 1140, "KEY TAKEAWAY", size=22, fill="@on_strong@", weight="bold"))
        parts.extend(_lines(570, 1178, plan["takeaway"], 445, size=23, max_lines=4, step=27,
                            fill="@on_strong@", weight="bold"))
    elif finish == "quote":
        parts.append(_rect(40, 1098, 1000, 104, "@soft@", stroke="@soft_stroke@"))
        parts.append(_rect(40, 1098, 12, 104, "@primary@", radius=6))
        parts.append(_text(74, 1166, "\u201c", size=64, fill="@primary@", weight="bold"))
        parts.extend(_lines(124, 1138, plan["takeaway"], 890, size=25, max_lines=2, step=32,
                            fill="@soft_ink@", weight="bold"))
        parts.append(_rect(40, 1210, 1000, 72, "@warn_bg@", stroke="@warn_stroke@", radius=36))
        parts.append(_icon("warning", 58, 1228, "@warn_icon@", 1.3))
        label = _fit_words(heading, 190, 22)
        parts.append(_text(98, 1253, label, size=22, fill="@warn_head@", weight="bold"))
        x = 98 + int(len(label) * 22 * 0.61) + 18
        one_line = _fits(gotcha.get("text"), 1010 - x, 22, 1)
        parts.extend(_lines(x, 1253 if one_line else 1240, gotcha.get("text"), 1010 - x, size=22,
                            max_lines=2, step=25, fill="@warn_text@"))
    else:
        _bottom_bars(parts, plan, gotcha)
    parts.append('<line x1="60" y1="1290" x2="1020" y2="1290" stroke="@rule@" '
                 'stroke-width="2" stroke-dasharray="none"/>')
    parts.append(_text(60, 1324, footer, size=22, fill="@footer@"))


def _bottom_bars(parts: list[str], plan: dict, gotcha: dict) -> None:
    parts.append(_rect(40, 1098, 1000, 100, "@warn_bg@", stroke="@warn_stroke@"))
    parts.append(_icon("warning", 60, 1112, "@warn_icon@", 1.5))
    parts.append(_text(110, 1132, _fit_words(gotcha.get("heading") or "Watch out", 880, 24),
                       size=24, fill="@warn_head@", weight="bold"))
    parts.extend(_lines(110, 1160, gotcha.get("text"), 900, size=22, max_lines=2, step=26,
                        fill="@warn_text@"))
    parts.append(_rect(40, 1206, 1000, 74, "@strong@"))
    parts.append(_icon("bulb", 60, 1226, "@on_strong@", 1.5))
    parts.extend(_lines(110, 1236, plan["takeaway"], 900, size=23, max_lines=2, step=26,
                        fill="@on_strong@", weight="bold"))


def _kicker_width(kicker: str, size: int = 22) -> int:
    return int(len(kicker) * size * 0.66)


def _panel(parts: list[str], classic: str, top: int, h: int, stripe: str, icon: str, kicker: str,
           icon_xy: tuple[int, int], kicker_xy: tuple[int, int]) -> None:
    """The box, icon and kicker of a header panel in the poster's header style.

    classic: the helper's own box (a tinted "soft" card, or a white "card" with a left stripe).
    bold: a white card with a coloured top strip and the kicker in a filled tab.
    minimal: no box, a tall accent bar on the left and a rule underneath.
    """
    style = _VARIANT.get("header", "classic")
    (ix, iy), (kx, ky) = icon_xy, kicker_xy
    if style == "bold":
        parts.append(_rect(40, top, 1000, h, "@card@", stroke="@card_stroke@"))
        parts.append(_rect(40, top, 1000, 10, stripe, radius=5))
        width = kx - ix + _kicker_width(kicker) + 40
        parts.append(_rect(ix - 14, ky - 31, width, 42, "@strong@", radius=21))
        parts.append(_icon(icon, ix, ky - 26, "@on_strong@", 1.3))
        parts.append(_text(kx, ky, kicker, size=22, fill="@on_strong@", weight="bold"))
        return
    if style == "minimal":
        parts.append(_rect(40, top + 6, 10, h - 12, stripe, radius=5))
        parts.append(f'<line x1="40" y1="{top + h + 4}" x2="1040" y2="{top + h + 4}" '
                     'stroke="@rule@" stroke-width="2" stroke-dasharray="none"/>')
    elif classic == "soft":
        parts.append(_rect(40, top, 1000, h, "@soft@", stroke="@soft_stroke@"))
    else:
        parts.append(_rect(40, top, 1000, h, "@card@", stroke="@card_stroke@"))
        parts.append(_rect(40, top, 12, h, stripe, radius=6))
    parts.append(_icon(icon, ix, iy, stripe, 1.3 if classic == "card" else 1.4))
    parts.append(_text(kx, ky, kicker, size=22, fill=stripe, weight="bold"))


def _soft_header(parts: list[str], plan: dict, headline: str, kicker: str, icon: str) -> None:
    """Tinted header card (y 35-220): kicker, title of up to two lines and a subtitle."""
    _panel(parts, "soft", 35, 185, "@primary@", icon, kicker, (65, 55), (110, 83))
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
    """Full-bleed header band (y 0-250) with the title in the banner colour.

    classic: a flat band. bold: the band with two large translucent discs and an accent stripe
    along its foot. minimal: a pale band with dark text and a thin accent line.
    """
    style = _VARIANT.get("header", "classic")
    ink, kick, sub = "@on_strong@", "@on_strong@", "@on_strong@"
    if style == "minimal":
        parts.append(_rect(0, 0, 1080, 250, "@soft@", radius=0))
        parts.append(_rect(0, 244, 1080, 6, "@primary@", radius=0))
        ink, kick, sub = "@ink@", "@primary@", "@muted@"
    else:
        parts.append(_rect(0, 0, 1080, 250, "@strong@", radius=0))
        if style == "bold":
            parts.append('<circle cx="1010" cy="40" r="170" fill="@on_strong@" opacity="0.07"/>')
            parts.append('<circle cx="1060" cy="230" r="110" fill="@on_strong@" opacity="0.06"/>')
            parts.append(_rect(0, 240, 1080, 10, "@a2@", radius=0))
    parts.append(_icon(icon, 45, 40, kick, 1.4))
    parts.append(_text(92, 68, kicker, size=22, fill=kick, weight="bold"))
    title = _wrap(plan.get("title") or headline, 990, 46, 2)
    for i, line in enumerate(title):
        parts.append(_text(45, 128 + i * 52, line, size=46, fill=ink, weight="bold"))
    subtitle_y = 190 if len(title) == 1 else 226
    parts.extend(_lines(45, subtitle_y, plan.get("subtitle"), 990, size=22, max_lines=1,
                        fill=sub))


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
    _panel(parts, "card", 35, 180, stripe, icon, kicker, (72, 52), (114, 78))
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
        _half(parts, "left" if x < 540 else "right")
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
        _half(parts)
    parts.append(_arrow(524, 440, 554, 440))
    parts.append(_text(45, 684, _fit_words(hero.get("caption") or "In practice", 990, 24),
                       size=24, fill="@ink@", weight="bold"))
    _modules_grid(parts, plan, plan["modules"], accent, 700, 186, gap=10)


def _stats_module(plan: dict) -> dict | None:
    """The first stats module with at least two 'value | caption' lines."""
    for module in plan["modules"]:
        lines = module.get("lines") if isinstance(module.get("lines"), list) else []
        if (_clean(module.get("kind")).lower() in STAT_KINDS
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
    if _comparable(stats["lines"], _clean(stats.get("kind")).lower() == "chart"):
        # Numbers in one unit read best side by side, as a bar chart.
        pairs = _pairs(stats["lines"])[:4]
        k = len(pairs)
        step = min(52, 150 // k)
        parts.append(_rect(40, 235, 1000, 170, "@card@", stroke="@card_stroke@"))
        parts.append(_rect(40, 235, 1000, 7, accent[0], radius=3))
        _bars(parts, pairs, 70, 235 + (170 - step * (k - 1)) // 2 + 8, 940, step, accent,
              "@ink@")
    else:
        pairs = _pairs(stats["lines"])[:4]
        k = len(pairs)
        w, size = (1000 - 16 * (k - 1)) // k, 44 if k <= 3 else 36
        for i, (value, caption) in enumerate(pairs):
            x, colour = 40 + i * (w + 16), accent[i % len(accent)]
            parts.append(_rect(x, 235, w, 170, "@card@", stroke="@card_stroke@"))
            parts.append(_rect(x, 235, w, 7, colour, radius=3))
            number = _number(value)
            room = w - 44
            if number and number[1] == "%" and w >= 230:
                # A percentage also gets a progress ring in the tile's corner.
                _ring(parts, x + w - 52, 282, 28, number[0], colour)
                room = w - 44 - 80
            parts.append(_counting(_text(x + 22, 300, _fit_words(value, room, size), size=size,
                                         fill=colour, weight="bold"), value))
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


# --- Layouts that draw extra planner content: cards, a comparison table, layers or stages ---

def _items(value: object, low: int, high: int) -> list[dict]:
    """The first `high` dict items of a list, or [] when there are fewer than `low`."""
    items = [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []
    return items[:high] if len(items) >= low else []


def _cards(plan: dict) -> list[dict]:
    """Six or nine titled cards (problems, tips, principles), each with an optional fix."""
    cards = [c for c in _items(plan.get("cards"), 6, 9) if _clean(c.get("title"))]
    return cards[:9] if len(cards) >= 9 else cards[:6] if len(cards) >= 6 else []


def _table(plan: dict) -> dict | None:
    """Two named sides and 3-5 aspect rows, or None."""
    table = plan.get("table")
    if not isinstance(table, dict) or not (_clean(table.get("left")) and _clean(table.get("right"))):
        return None
    rows = [r for r in _items(table.get("rows"), 3, 5) if _clean(r.get("aspect"))]
    return {**table, "rows": rows} if len(rows) >= 3 else None


def _layers(plan: dict) -> list[dict]:
    """Two to four named layers, each with one to three items."""
    out = []
    for layer in _items(plan.get("layers"), 2, 4):
        items = _items(layer.get("items"), 1, 3)
        if _clean(layer.get("name")) and items:
            out.append({**layer, "items": items})
    return out if len(out) >= 2 else []


def _stages(plan: dict) -> list[dict]:
    """Three to five stages whose words fit the narrowest ring band."""
    stages = [s for s in _items(plan.get("stages"), 3, 5) if _clean(s.get("label"))]
    if len(stages) < 3:
        return []
    limit = int((1000 // len(stages) - 40) / (22 * 0.61))
    words = " ".join(_clean(s.get("label")) + " " + _clean(s.get("detail")) for s in stages).split()
    return stages if all(len(w) <= limit for w in words) else []


def _hub_label(plan: dict, headline: str) -> list[str]:
    """Up to three short lines for the hub circle, or [] when a word is too long for it."""
    label = _clean(plan["hero"].get("hub") or plan.get("title") or headline)
    if not label or any(len(w) > 11 for w in label.split()):
        return []
    lines = _wrap(label, 160, 22, 99)
    return lines if len(lines) <= 3 else []


def _centre_header(parts: list[str], plan: dict, headline: str, kicker: str) -> int:
    """Centred kicker, title and subtitle on the page background; returns the next free y.

    classic: a plain kicker. bold: the kicker in a filled pill. minimal: rules either side of it.
    """
    style, half = _VARIANT.get("header", "classic"), _kicker_width(kicker) // 2
    if style == "bold":
        parts.append(_rect(540 - half - 26, 39, 2 * half + 52, 42, "@strong@", radius=21))
        parts.append(_text(540, 68, kicker, size=22, fill="@on_strong@", weight="bold",
                           anchor="middle"))
    else:
        if style == "minimal":
            for sign in (-1, 1):
                parts.append(f'<line x1="{540 + sign * (half + 22)}" y1="60" '
                             f'x2="{540 + sign * (half + 112)}" y2="60" stroke="@primary@" '
                             'stroke-width="3" stroke-dasharray="none"/>')
        parts.append(_text(540, 68, kicker, size=22, fill="@primary@", weight="bold",
                           anchor="middle"))
    title = _wrap(plan.get("title") or headline, 1000, 44, 2)
    for i, line in enumerate(title):
        parts.append(_text(540, 122 + i * 50, line, size=44, fill="@ink@", weight="bold",
                           anchor="middle"))
    y = 122 + (len(title) - 1) * 50 + 44
    parts.extend(_text(540, y, line, size=22, fill="@muted@", anchor="middle")
                 for line in _wrap(plan.get("subtitle"), 1000, 22, 1))
    return y + 24


def _layout_matrix(parts: list[str], plan: dict, headline: str, accent: list[str]) -> None:
    """A grid of numbered cards: what goes wrong, why, and the fix (3x3, or 2x3 for six)."""
    cards = _cards(plan)
    top = _centre_header(parts, plan, headline, "WHAT TO WATCH FOR") + 14
    cols = 3 if len(cards) == 9 else 2
    w, h = (1000 - 16 * (cols - 1)) // cols, (1085 - top - 14 * 2) // 3
    for i, card in enumerate(cards):
        x, y = 40 + (i % cols) * (w + 16), top + (i // cols) * (h + 14)
        colour = accent[i % len(accent)]
        parts.append(_rect(x, y, w, h, "@card@", stroke="@card_stroke@", radius=14)
                     .replace("<rect ", f'<rect data-motion-step="{i + 1}" ', 1))
        parts.append(_rect(x, y, w, 70, "@soft@", radius=14))
        parts.append(f'<circle cx="{x + 30}" cy="{y + 35}" r="19" fill="{colour}"/>')
        parts.append(_text(x + 30, y + 43, f"{i + 1:02d}", size=22, fill="@bg@", weight="bold",
                           anchor="middle"))
        title = _wrap(card.get("title"), w - 80, 22, 2) or ["Point"]
        for j, line in enumerate(title):
            parts.append(_text(x + 60, y + (43 if len(title) == 1 else 31 + j * 25), line,
                               size=22, fill="@ink@", weight="bold"))
        parts.append(_icon(card.get("icon"), x + 18, y + 84, colour, 1.5))
        parts.extend(_lines(x + 66, y + 106, card.get("text"), w - 86, size=22,
                            max_lines=max(1, min(3, (h - 196) // 28 + 1)), step=28))
        fix = _clean(card.get("fix"))
        if fix:
            parts.append(_rect(x + 12, y + h - 84, w - 24, 72, "@soft2@", stroke="@card_stroke@",
                               radius=10))
            parts.extend(_lines(x + 26, y + h - 54, f"Fix: {fix}", w - 56, size=22, max_lines=2,
                                step=27, fill="@soft_ink@", weight="bold"))


def _layout_versus(parts: list[str], plan: dict, headline: str, accent: list[str]) -> None:
    """Two tools side by side: what each is, a table of differences, and when to use each."""
    table = _table(plan)
    _centre_header(parts, plan, headline, "SIDE BY SIDE")
    sides = [(40, "@a1@", table["left"], table.get("left_about"), table.get("left_when")),
             (548, "@a2@", table["right"], table.get("right_about"), table.get("right_when"))]
    for x, colour, name, about, _ in sides:
        _half(parts, "left" if x < 540 else "right")
        parts.append(_rect(x, 235, 492, 140, "@soft2@", stroke=colour))
        parts.append(_icon("layers", x + 24, 256, colour, 1.5))
        parts.append(_text(x + 72, 285, _fit_words(name, 390, 30), size=30, fill=colour,
                           weight="bold"))
        parts.extend(_lines(x + 24, 325, about, 444, size=22, max_lines=2, step=28))
        _half(parts)
    parts.append(_rect(390, 391, 300, 44, "@strong@", radius=22))
    parts.append(_text(540, 421, "KEY DIFFERENCES", size=22, fill="@on_strong@", weight="bold",
                       anchor="middle"))
    columns = [(40, 250), (290, 375), (665, 375)]
    heads = ["Aspect", table["left"], table["right"]]
    fills = ["@soft@", "@soft@", "@soft@"]
    inks = ["@ink@", "@a1@", "@a2@"]
    for (x, w), head, fill, ink in zip(columns, heads, fills, inks):
        parts.append(_rect(x, 450, w, 48, fill, stroke="@card_stroke@", radius=0))
        parts.append(_text(x + 16, 482, _fit_words(head, w - 32, 22), size=22, fill=ink,
                           weight="bold"))
    y = 498
    for r, row in enumerate(table["rows"]):
        for c, ((x, w), key) in enumerate(zip(columns, ("aspect", "left", "right"))):
            rect = _rect(x, y, w, 66, "@card@", stroke="@card_stroke@", radius=0)
            if c == 0:
                rect = rect.replace("<rect ", f'<rect data-motion-step="{r + 1}" ', 1)
            parts.append(rect)
            if c == 0:
                parts.append(_text(x + 16, y + 41, _fit_words(row.get(key), w - 32, 22),
                                   size=22, fill="@ink@", weight="bold"))
            else:
                parts.extend(_lines(x + 16, y + 29, row.get(key), w - 32, size=22, max_lines=2,
                                    step=26))
        y += 66
    top = y + 20
    for x, colour, name, _, when in sides:
        _half(parts, "left" if x < 540 else "right")
        parts.append(_rect(x, top, 492, 1085 - top, "@card@", stroke=colour))
        parts.append(_icon("check", x + 22, top + 20, colour, 1.4))
        parts.append(_text(x + 64, top + 44, _fit_words(f"Use {_clean(name)} when", 400, 24),
                           size=24, fill=colour, weight="bold"))
        rows = 0
        for item in when if isinstance(when, list) else []:
            wrapped = _wrap(item, 430, 22, 2)
            if not wrapped or rows + len(wrapped) > 5:
                break
            for j, line in enumerate(wrapped):
                parts.append(_text(x + 24, top + 86 + rows * 28, ("• " if j == 0 else "  ") + line,
                                   size=22, fill="@muted@"))
                rows += 1
        _half(parts)


def _layout_architecture(parts: list[str], plan: dict, headline: str, accent: list[str]) -> None:
    """Numbered layer bands from top to bottom, each holding its components, joined by arrows."""
    layers = _layers(plan)
    _band_header(parts, plan, headline, "SYSTEM MAP", "network")
    count, gap = len(layers), 30
    h = (815 - gap * (count - 1)) // count
    step = 0
    for i, layer in enumerate(layers):
        y, colour = 270 + i * (h + gap), accent[i % len(accent)]
        parts.append(_rect(40, y, 1000, h, "@card@", stroke="@soft_stroke@", radius=14))
        parts.append(_rect(40, y, 78, 52, "@soft@", radius=14))
        parts.append(_text(79, y + 36, f"{i + 1:02d}", size=26, fill=colour, weight="bold",
                           anchor="middle"))
        parts.append(_text(134, y + 36, _fit_words(layer.get("name"), 860, 24).upper() or "LAYER",
                           size=24, fill=colour, weight="bold"))
        items = layer["items"]
        k = len(items)
        ch = min(h - 76, 150)
        w = (920 - 24 * (k - 1)) // k
        cy = y + 60 + (h - 76 - ch) // 2
        for j, item in enumerate(items):
            step += 1
            x = 80 + j * (w + 24)
            parts.append(_rect(x, cy, w, ch, "@node@", stroke="@card_stroke@", radius=12)
                         .replace("<rect ", f'<rect data-motion-step="{step}" ', 1))
            parts.append(_icon(item.get("icon"), x + 18, cy + 18, colour, 1.4))
            parts.append(_text(x + 64, cy + 44, _fit_words(item.get("label"), w - 84, 24) or "Part",
                               size=24, fill="@ink@", weight="bold"))
            parts.extend(_lines(x + 18, cy + 80, item.get("detail"), w - 36, size=22,
                                max_lines=max(1, min(2, (ch - 70) // 28)), step=28))
        if i < count - 1:
            parts.append(_arrow(540, y + h + 3, 540, y + h + gap - 5))


def _layout_progression(parts: list[str], plan: dict, headline: str, accent: list[str]) -> None:
    """Nested rounded stages growing left to right, from the core idea to the most advanced."""
    stages = _stages(plan)
    _card_header(parts, plan, headline, "THE PROGRESSION", "rocket")
    n = len(stages)
    band = 1000 // n
    parts.append(_text(45, 250, _fit_words(plan["hero"].get("caption") or "Stage by stage", 990, 22),
                       size=22, fill="@muted@", weight="bold"))
    fills = ["@soft2@", "@card@", "@soft@", "@card@", "@soft2@"]
    for i in reversed(range(n)):
        inset = (n - 1 - i) * 28
        top, bottom, right = 268 + inset, 840 - inset, 40 + band * (i + 1)
        fill = "@strong@" if i == 0 else fills[(n - 1 - i) % len(fills)]
        parts.append(_rect(40, top, right - 40, bottom - top, fill, stroke="@soft_stroke@",
                           radius=60).replace("<rect ", f'<rect data-motion-step="{i + 1}" ', 1))
    for i, stage in enumerate(stages):
        inset = (n - 1 - i) * 28
        top, bottom = 268 + inset, 840 - inset
        left = 40 + band * i + (24 if i else 30)
        ink, colour = ("@on_strong@", "@on_strong@") if i == 0 else ("@ink@", accent[i % len(accent)])
        muted = "@on_strong@" if i == 0 else "@muted@"
        parts.append(_icon(stage.get("icon"), left, top + 70, colour, 1.5))
        parts.append(_text(left, top + 150, f"{i + 1:02d}", size=26, fill=colour, weight="bold"))
        label = _wrap(stage.get("label"), band - 50, 22, 2) or ["Stage"]
        for j, line in enumerate(label):
            parts.append(_text(left, top + 188 + j * 27, line, size=22, fill=ink, weight="bold"))
        parts.extend(_lines(left, max(bottom - 150, top + 188 + len(label) * 27 + 30),
                            stage.get("detail"), band - 50, size=22, max_lines=4, step=27,
                            fill=muted))
    _module_row(parts, plan["modules"][:2], accent, 860, 225)


def _layout_hub(parts: list[str], plan: dict, headline: str, accent: list[str]) -> None:
    """One central idea with its parts around it, joined by spokes, then the details."""
    import math

    nodes = plan["hero"]["nodes"]
    _card_header(parts, plan, headline, "AT THE CORE", "network")
    hub_x, hub_y, radius = 540, 458, 100
    _VARIANT["origin"] = (hub_x, hub_y)  # the ripple motion spreads out from the hub
    parts.append(f'<circle cx="{hub_x}" cy="{hub_y}" r="{radius}" fill="@strong@"/>')
    parts.append(_icon("target", hub_x - 22, hub_y - 82, "@on_strong@", 1.8))
    label = _hub_label(plan, headline)
    for j, line in enumerate(label):
        parts.append(_text(hub_x, hub_y + 4 + j * 28 - (len(label) - 1) * 10, line, size=22,
                           fill="@on_strong@", weight="bold", anchor="middle"))
    columns = [(40, nodes[0::2], 0), (740, nodes[1::2], 1)]
    for x, column, offset in columns:
        c = len(column)
        top = hub_y - (c * 126 + (c - 1) * 12) // 2
        for j, node in enumerate(column):
            i = offset + 2 * j
            y, colour = top + j * 138, accent[i % len(accent)]
            parts.append(_rect(x, y, 300, 126, "@card@", stroke="@card_stroke@", radius=14)
                         .replace("<rect ", f'<rect data-motion-step="{i + 1}" ', 1))
            parts.append(_rect(x, y, 300, 6, colour, radius=3))
            parts.append(_icon(node.get("icon"), x + 18, y + 18, colour, 1.4))
            parts.append(_text(x + 270, y + 44, str(i + 1), size=22, fill=colour, weight="bold"))
            parts.append(_text(x + 64, y + 44, _fit_words(node.get("label"), 190, 24) or "Part",
                               size=24, fill="@ink@", weight="bold"))
            parts.extend(_lines(x + 18, y + 82, node.get("detail"), 264, size=22, max_lines=2,
                                step=27))
            sx, sy = (x + 300, y + 63) if x < hub_x else (x, y + 63)
            dx, dy = hub_x - sx, hub_y - sy
            dist = math.hypot(dx, dy)
            ex, ey = hub_x - dx / dist * (radius + 10), hub_y - dy / dist * (radius + 10)
            parts.append(_arrow(sx + (6 if x < hub_x else -6), sy, round(ex), round(ey)))
    parts.append(_text(45, 684, "IN PRACTICE", size=24, fill="@ink@", weight="bold"))
    _modules_grid(parts, plan, plan["modules"], accent, 700, 186, gap=10)


# ----------------------------------------------------------------------------- more layouts
# Each of these draws a content shape the planner adds on purpose (profiles, scorecard, decision,
# pros/cons, cards, layers, table, stages), inspired by common hand-made LinkedIn infographics.

def _card_list(plan: dict, low: int, high: int) -> list[dict]:
    """low..high titled cards, or [] when the post has a different number."""
    cards = [c for c in (plan.get("cards") if isinstance(plan.get("cards"), list) else [])
             if isinstance(c, dict) and _clean(c.get("title"))]
    return cards if low <= len(cards) <= high else []


def _strings(value: object, low: int, high: int) -> list[str]:
    items = [_clean(v) for v in value if _clean(v)] if isinstance(value, list) else []
    return items[:high] if len(items) >= low else []


def _profiles(plan: dict) -> list[dict]:
    """Three to six named profiles (types, roles, tools), each with a short description."""
    out = [p for p in _items(plan.get("profiles"), 3, 6) if _clean(p.get("name"))]
    return out if len(out) >= 3 else []


def _scorecard(plan: dict) -> dict | None:
    card = plan.get("scorecard")
    keys = ("left", "right", "left_value", "right_value")
    if isinstance(card, dict) and all(_clean(card.get(k)) for k in keys):
        return card
    return None


def _decision(plan: dict) -> dict | None:
    decision = plan.get("decision")
    if isinstance(decision, dict) and all(_clean(decision.get(k)) for k in ("question", "yes", "no")):
        return decision
    return None


def _pros_cons(plan: dict) -> tuple[list[str], list[str]]:
    pros, cons = _strings(plan.get("pros"), 2, 5), _strings(plan.get("cons"), 2, 5)
    return (pros, cons) if pros and cons else ([], [])


def _bullets(parts: list[str], x: int, y: int, items: object, width: int, rows: int, *,
             step: int = 28, fill: str = "@muted@", mark: str = "• ", anchor: str = "start") -> int:
    """Draw whole list items (each wrapped onto at most 3 lines) until `rows` lines are used."""
    used = 0
    for item in items if isinstance(items, list) else []:
        wrapped = _wrap(item, width, 22, 99)
        if not wrapped or len(wrapped) > 3 or used + len(wrapped) > rows:
            if wrapped:
                _CUTS.append(_clean(item))  # an item that does not fit is a loss: try another layout
            break
        for j, line in enumerate(wrapped):
            prefix = (mark if j == 0 else " " * len(mark)) if anchor == "start" else ""
            parts.append(_text(x, y + used * step, prefix + line, size=22, fill=fill,
                               anchor=anchor))
            used += 1
    return used


def _labelled(parts: list[str], x: int, y: int, label: object, items: object, width: int,
              colour: str, max_lines: int) -> int:
    """'Label: a · b · c' wrapped, with the label in bold colour; returns the lines drawn."""
    label = _clean(label).rstrip(":")
    values = [_clean(v) for v in items if _clean(v)] if isinstance(items, list) else []
    lines = _wrap(f"{label}: " + " · ".join(values), width, 22, max_lines)
    for i, line in enumerate(lines):
        if i == 0 and line.startswith(label + ":"):
            rest = line[len(label) + 1:]
            parts.append(f'<text x="{x}" y="{y}" font-size="22" font-family="Arial, DejaVu Sans, '
                         f'sans-serif" fill="@muted@"><tspan font-weight="bold" fill="{colour}">'
                         f'{escape(label)}:</tspan>{escape(rest)}</text>')
        else:
            parts.append(_text(x, y + i * 27, line, size=22, fill="@muted@"))
    return len(lines)


def _centred(parts: list[str], cx: int, y: int, value: object, width: int, max_lines: int, *,
             size: int = 22, fill: str = "@muted@", weight: str = "normal", step: int = 27) -> int:
    lines = _wrap(value, width, size, max_lines)
    for i, line in enumerate(lines):
        parts.append(_text(cx, y + i * step, line, size=size, fill=fill, weight=weight,
                           anchor="middle"))
    return len(lines)


def _step_rect(x: int, y: int, w: int, h: int, fill: str, step: int, *, stroke: str = "@card_stroke@",
               radius: int = 14) -> str:
    return _rect(x, y, w, h, fill, stroke=stroke, radius=radius).replace(
        "<rect ", f'<rect data-motion-step="{step}" ', 1)


def _layout_profiles(parts: list[str], plan: dict, headline: str, accent: list[str]) -> None:
    """A 2-column grid of profile cards: name band, what it is, then two labelled lists."""
    profiles = _profiles(plan)
    top = max(_centre_header(parts, plan, headline, "KNOW THE TYPES") + 6, 230)
    rows = len(profiles) // 2
    h = (1085 - top - 14 * (rows - 1)) // rows
    for i, p in enumerate(profiles):
        x, y, colour = 40 + (i % 2) * 508, top + (i // 2) * (h + 14), accent[i % len(accent)]
        parts.append(_step_rect(x, y, 492, h, "@card@", i + 1))
        parts.append(_rect(x, y, 492, 56, colour, radius=14))
        parts.append(_icon(p.get("icon"), x + 16, y + 12, "@bg@", 1.3))
        parts.append(_text(x + 60, y + 37, _fit_words(p.get("name"), 410, 24), size=24,
                           fill="@bg@", weight="bold"))
        about = _lines(x + 20, y + 88, p.get("about"), 452, size=22, max_lines=2, step=27)
        parts.extend(about)
        ly = y + 88 + len(about) * 27 + 10
        rows = max(1, (y + h - 14 - ly) // 27 + 1) // 2
        for label, items, default in ((p.get("a_label"), p.get("a_items"), "Used in"),
                                      (p.get("b_label"), p.get("b_items"), "Key ideas")):
            ly += _labelled(parts, x + 20, ly, label or default, items, 452, colour, rows) * 27 + 8


def _layout_columns(parts: list[str], plan: dict, headline: str, accent: list[str]) -> None:
    """Tall side-by-side columns, one per profile, each opened by an icon medallion."""
    profiles = _profiles(plan)[:5]
    n = len(profiles)
    top = max(_centre_header(parts, plan, headline, "WHO IS WHO") + 56, 290)
    w = (1000 - 14 * (n - 1)) // n
    for i, p in enumerate(profiles):
        x, colour = 40 + i * (w + 14), accent[i % len(accent)]
        cx = x + w // 2
        parts.append(_step_rect(x, top, w, 1085 - top, "@card@", i + 1, stroke=colour))
        parts.append(f'<circle cx="{cx}" cy="{top}" r="40" fill="@card@" stroke="{colour}" '
                     f'stroke-width="3"/>')
        parts.append(_icon(p.get("icon"), cx - 22, top - 22, colour, 1.8))
        y = top + 78
        y += _centred(parts, cx, y, p.get("name"), w - 24, 2, size=24, fill="@ink@",
                      weight="bold", step=29) * 29 + 10
        sections = [(p.get("about_label") or "What it is", [p.get("about")]),
                    (p.get("a_label") or "Best for", p.get("a_items")),
                    (p.get("b_label") or "Watch for", p.get("b_items"))]
        room = (1085 - 14 - y) // 3
        for k, (label, items) in enumerate(sections):
            parts.append(_rect(x + 10, y, w - 20, 36, "@soft@", radius=10))
            parts.append(_text(cx, y + 26, _fit_words(label, w - 40, 22), size=22, fill=colour,
                               weight="bold", anchor="middle"))
            rows = max(1, (room - 56) // 26)
            if k == 0:
                _centred(parts, cx, y + 64, items[0], w - 28, rows, step=26)
            else:
                _bullets(parts, cx, y + 64, items, w - 28, rows, step=26, anchor="middle")
            y += room


def _layout_zigzag(parts: list[str], plan: dict, headline: str, accent: list[str]) -> None:
    """Numbered problems alternating either side of a spine: what goes wrong, then the fix."""
    cards = _card_list(plan, 5, 7)
    n = len(cards)
    top = max(_centre_header(parts, plan, headline, "DIAGNOSE AND FIX") + 8, 232)
    avail = 1085 - top
    step = (avail + 20) // (n + 1)
    h = min(2 * step - 20, 300)
    step = (avail - h) // (n - 1)
    for i in range(n - 1):
        parts.append(f'<line x1="540" y1="{top + i * step + 62}" x2="540" '
                     f'y2="{top + (i + 1) * step + 10}" stroke="@soft_stroke@" stroke-width="4" '
                     'stroke-dasharray="none"/>')
    for i, card in enumerate(cards):
        y, colour = top + i * step, accent[i % len(accent)]
        x = 40 if i % 2 == 0 else 570
        parts.append(_step_rect(x, y, 470, h, "@card@", i + 1))
        parts.append(f'<circle cx="540" cy="{y + 36}" r="22" fill="{colour}"/>')
        parts.append(_text(540, y + 44, str(i + 1), size=22, fill="@bg@", weight="bold",
                           anchor="middle"))
        parts.append(_icon(card.get("icon"), x + 18, y + 16, colour, 1.3))
        parts.append(_text(x + 62, y + 41, _fit_words(card.get("title"), 390, 24), size=24,
                           fill="@ink@", weight="bold"))
        fix = _clean(card.get("fix"))
        fix_lines = _wrap(f"Fix: {fix}", 410, 22, 2) if fix else []
        box = len(fix_lines) * 27 + 22 if fix_lines else 0
        text_rows = max(1, (h - 62 - box - 16) // 27)
        parts.extend(_lines(x + 20, y + 80, card.get("text"), 430, size=22,
                            max_lines=text_rows, step=27))
        if fix_lines:
            by = y + h - 12 - box
            parts.append(_rect(x + 12, by, 446, box, "@soft2@", stroke="@card_stroke@", radius=10))
            for j, line in enumerate(fix_lines):
                parts.append(_text(x + 26, by + 31 + j * 27, line, size=22, fill="@soft_ink@",
                                   weight="bold"))


def _layout_playbook(parts: list[str], plan: dict, headline: str, accent: list[str]) -> None:
    """Numbered rows on a coloured spine: the step on the left, what to do on the right."""
    cards = _card_list(plan, 4, 6)
    n = len(cards)
    _band_header(parts, plan, headline, "THE PLAYBOOK", "list")
    gap = 14
    h = (810 - gap * (n - 1)) // n
    parts.append(_rect(66, 290, 12, 780, "@soft_stroke@", radius=6))
    for i, card in enumerate(cards):
        y, colour = 275 + i * (h + gap), accent[i % len(accent)]
        parts.append(f'<circle cx="72" cy="{y + h // 2}" r="30" fill="{colour}"/>')
        parts.append(_text(72, y + h // 2 + 9, str(i + 1), size=26, fill="@bg@", weight="bold",
                           anchor="middle"))
        parts.append(_step_rect(110, y, 930, h, "@card@", i + 1))
        parts.append(_icon(card.get("icon"), 128, y + 18, colour, 1.3))
        parts.append(_text(172, y + 44, _fit_words(card.get("title"), 420, 24), size=24,
                           fill="@ink@", weight="bold"))
        parts.extend(_lines(130, y + 80, card.get("text"), 470, size=22,
                            max_lines=max(1, (h - 92) // 27 + 1), step=27))
        parts.append(_rect(640, y + 12, 388, h - 24, "@soft2@", radius=12))
        parts.append(_text(660, y + 42, "What to do", size=22, fill=colour, weight="bold"))
        parts.append(_icon("check", 660, y + 52, colour, 1.1))
        parts.extend(_lines(700, y + 72, card.get("fix") or card.get("text"), 316, size=22,
                            max_lines=max(1, (h - 92) // 27 + 1), step=27, fill="@ink@"))


def _layout_scorecard(parts: list[str], plan: dict, headline: str, accent: list[str]) -> None:
    """Two contenders' headline numbers around a ratio badge, KPI tiles, then how it works."""
    card, stats = _scorecard(plan), _stats_module(plan)
    _centre_header(parts, plan, headline, "THE SCORECARD")
    sides = [(40, 245, "@a1@", "@soft@", card["left"], card["left_value"], card.get("left_caption")),
             (630, 835, "@a2@", "@soft2@", card["right"], card["right_value"],
              card.get("right_caption"))]
    for x, cx, colour, fill, name, value, caption in sides:
        _half(parts, "left" if x < 540 else "right")
        parts.append(_rect(x, 255, 410, 240, fill, stroke=colour, radius=16))
        parts.append(_text(cx, 300, _fit_words(name, 330, 26).upper(), size=26, fill=colour,
                           weight="bold", anchor="middle"))
        parts.append(_counting(_text(cx, 385, _fit_words(value, 330, 56), size=56, fill=colour,
                                     weight="bold", anchor="middle"), value))
        _centred(parts, cx, 428, caption, 330, 2)
        _half(parts)
    parts.append('<circle cx="540" cy="375" r="86" fill="@card@" stroke="@strong@" '
                 'stroke-width="4"/>')
    ratio = _clean(card.get("ratio"))
    parts.append(_text(540, 368 if ratio else 386, _fit_words(ratio or "VS", 150, 40), size=40,
                       fill="@primary@", weight="bold", anchor="middle"))
    if ratio:
        _centred(parts, 540, 400, card.get("ratio_caption"), 140, 2, size=22, fill="@ink@",
                 weight="bold", step=25)
    pairs = _pairs(stats["lines"])[:4]
    k = len(pairs)
    w = (1000 - 16 * (k - 1)) // k
    for i, (value, caption) in enumerate(pairs):
        x, colour = 40 + i * (w + 16), accent[(i + 2) % len(accent)]
        parts.append(_rect(x, 515, w, 140, "@card@", stroke="@card_stroke@"))
        parts.append(_counting(_text(x + 22, 570, _fit_words(value, w - 44, 36), size=36,
                                     fill=colour, weight="bold"), value))
        parts.extend(_lines(x + 22, 607, caption, w - 44, size=22, max_lines=2, step=26))
    parts.append(_text(45, 700, "WHAT DRIVES IT", size=24, fill="@primary@", weight="bold"))
    _ribbon(parts, plan["hero"]["nodes"], accent, 715, 200)
    parts.append(_rect(40, 935, 1000, 145, "@soft@", stroke="@soft_stroke@"))
    parts.append(_icon("target", 64, 958, "@primary@", 1.4))
    parts.append(_text(110, 984, "WHY IT MATTERS", size=24, fill="@primary@", weight="bold"))
    lead = _clean(plan.get("tagline")) or _clean(plan["hero"].get("caption")) or plan["takeaway"]
    parts.extend(_lines(64, 1030, lead, 950, size=24, max_lines=2, step=32, fill="@soft_ink@",
                        weight="bold"))


def _layout_swimlanes(parts: list[str], plan: dict, headline: str, accent: list[str]) -> None:
    """One lane per layer: a label block, then its parts as boxes joined by arrows."""
    layers = _layers(plan)
    _soft_header(parts, plan, headline, "HOW THE PIECES FLOW", "network")
    n, gap = len(layers), 18
    h = (595 - gap * (n - 1)) // n
    step = 0
    for i, layer in enumerate(layers):
        y, colour = 245 + i * (h + gap), accent[i % len(accent)]
        parts.append(_rect(40, y, 1000, h, "@card@", stroke="@card_stroke@", radius=14))
        parts.append(_rect(40, y, 220, h, "@soft@", radius=14))
        parts.append(_text(60, y + 40, f"{i + 1:02d}", size=26, fill=colour, weight="bold"))
        parts.extend(_lines(60, y + 72, layer.get("name"), 180, size=22, max_lines=2, step=26,
                            fill="@ink@", weight="bold"))
        items = layer["items"]
        k = len(items)
        w = (735 - 44 * (k - 1)) // k
        for j, item in enumerate(items):
            step += 1
            x = 285 + j * (w + 44)
            parts.append(_step_rect(x, y + 14, w, h - 28, "@node@", step, radius=12))
            parts.append(_icon(item.get("icon"), x + 14, y + 22, colour, 1.1))
            label = _wrap(item.get("label"), w - 28, 22, 2) or ["Part"]
            for m, line in enumerate(label):
                parts.append(_text(x + 14, y + 74 + m * 26, line, size=22, fill="@ink@",
                                   weight="bold"))
            first = y + 74 + len(label) * 26
            rows = (y + h - 14 - 8 - first) // 26 + 1
            if rows >= 1:
                parts.extend(_lines(x + 14, first, item.get("detail"), w - 28, size=22,
                                    max_lines=rows, step=26))
            elif _clean(item.get("detail")):
                _CUTS.append(_clean(item.get("detail")))
            if j < k - 1:
                parts.append(_arrow(x + w + 4, y + h // 2, x + w + 40, y + h // 2))
    _module_row(parts, plan["modules"][:3], accent, 865, 215)


def _layout_twin(parts: list[str], plan: dict, headline: str, accent: list[str]) -> None:
    """Two coloured columns: what each option is and what it is best for, then how to start."""
    table = _table(plan)
    _centre_header(parts, plan, headline, "PICK THE RIGHT ONE")
    for x, colour, name, about, when in ((40, "@a1@", table["left"], table.get("left_about"),
                                         table.get("left_when")),
                                        (560, "@a2@", table["right"], table.get("right_about"),
                                         table.get("right_when"))):
        _half(parts, "left" if x < 540 else "right")
        parts.append(_rect(x, 255, 480, 435, "@card@", stroke=colour, radius=16))
        parts.append(_rect(x, 255, 480, 70, colour, radius=16))
        parts.append(_text(x + 240, 301, _fit_words(name, 430, 30).upper(), size=30,
                           fill="@bg@", weight="bold", anchor="middle"))
        about_lines = _lines(x + 24, 362, about, 432, size=22, max_lines=3, step=28)
        parts.extend(about_lines)
        label_y = 362 + len(about_lines) * 28 + 20
        parts.append(_text(x + 24, label_y, "Best for", size=24, fill=colour, weight="bold"))
        _bullets(parts, x + 24, label_y + 36, when, 420, (690 - 20 - label_y - 36) // 28 + 1)
        _half(parts)
    parts.append('<circle cx="540" cy="290" r="19" fill="@strong@"/>')
    parts.append(_text(540, 297, "VS", size=18, fill="@on_strong@", weight="bold", anchor="middle"))
    parts.append(_text(45, 735, _fit_words(plan["hero"].get("caption") or "How to start", 990, 24),
                       size=24, fill="@ink@", weight="bold"))
    _ribbon(parts, plan["hero"]["nodes"], accent, 750, 200)
    parts.append(_rect(40, 965, 1000, 115, "@soft@", stroke="@soft_stroke@"))
    parts.append(_icon("bulb", 64, 990, "@primary@", 1.4))
    lead = _clean(plan.get("tagline")) or plan["takeaway"]
    parts.extend(_lines(112, 1012, lead, 900, size=24, max_lines=2, step=32, fill="@soft_ink@",
                        weight="bold"))


def _layout_flowchart(parts: list[str], plan: dict, headline: str, accent: list[str]) -> None:
    """A flowchart: start, parallel branches, merge, then a yes/no decision with a loop back."""
    nodes, decision = plan["hero"]["nodes"], _decision(plan)
    _centre_header(parts, plan, headline, "HOW IT DECIDES")

    def box(node, x, y, w, h, number, colour):
        parts.append(_step_rect(x, y, w, h, "@node@", number, radius=12))
        parts.append(_icon(node.get("icon"), x + 16, y + 14, colour, 1.2))
        parts.append(_text(x + 56, y + 36, _fit_words(node.get("label"), w - 72, 22) or "Step",
                           size=22, fill="@ink@", weight="bold"))
        parts.extend(_lines(x + 16, y + 66, node.get("detail"), w - 32, size=22,
                            max_lines=max(1, (h - 66) // 26), step=26))

    box(nodes[0], 290, 245, 500, 82, 1, accent[0])
    branches = nodes[1:-1]
    k = len(branches)
    w = (930 - 24 * (k - 1)) // k
    for j, node in enumerate(branches):
        x = 110 + j * (w + 24)
        box(node, x, 365, w, 134, j + 2, accent[(j + 1) % len(accent)])
        parts.append(_arrow(540, 329, x + w // 2, 361))
        parts.append(_arrow(x + w // 2, 501, 540, 528))
    box(nodes[-1], 290, 532, 500, 82, len(nodes), accent[(k + 1) % len(accent)])
    parts.append(_arrow(540, 616, 540, 626))
    parts.append('<polygon points="540,630 740,700 540,770 340,700" fill="@soft@" '
                 'stroke="@strong@" stroke-width="3"/>')
    _centred(parts, 540, 696, decision["question"], 280, 2, size=22, fill="@ink@", weight="bold",
             step=26)
    parts.append(_text(768, 688, "YES", size=22, fill="@good@", weight="bold", anchor="middle"))
    parts.append(_arrow(742, 700, 790, 700))
    parts.append(_rect(795, 650, 245, 100, "@good_soft@", stroke="@good@", radius=12))
    parts.extend(_lines(812, 684, decision["yes"], 215, size=22, max_lines=3, step=26,
                        fill="@ink@", weight="bold"))
    parts.append(_text(305, 688, "NO", size=22, fill="@bad@", weight="bold", anchor="middle"))
    parts.append('<polyline points="338,700 70,700 70,286 284,286" fill="none" stroke="@bad@" '
                 'stroke-width="3" marker-end="url(#arrow)"/>')
    parts.append(_rect(40, 735, 290, 95, "@bad_soft@", stroke="@bad@", radius=12))
    parts.extend(_lines(56, 768, decision["no"], 258, size=22, max_lines=3, step=26,
                        fill="@ink@"))
    _module_row(parts, plan["modules"][:3], accent, 848, 232)


def _notes_module(plan: dict) -> dict | None:
    """The first plain list module (not code or numbers), shown as side notes."""
    for module in plan["modules"]:
        kind = _clean(module.get("kind")).lower()
        lines = module.get("lines") if isinstance(module.get("lines"), list) else []
        if kind not in ("code",) + STAT_KINDS and any(_clean(x) for x in lines):
            return module
    return None


def _layout_pipeline(parts: list[str], plan: dict, headline: str, accent: list[str]) -> None:
    """Numbered stages down the page with an annotation column beside them."""
    stages, notes = _stages(plan), _notes_module(plan)
    _card_header(parts, plan, headline, "STEP BY STEP", "layers")
    n, gap = len(stages), 22
    h = (620 - gap * (n - 1)) // n
    for i, stage in enumerate(stages):
        y, colour = 240 + i * (h + gap), accent[i % len(accent)]
        parts.append(f'<circle cx="74" cy="{y + h // 2}" r="27" fill="{colour}"/>')
        parts.append(_text(74, y + h // 2 + 8, str(i + 1), size=24, fill="@bg@", weight="bold",
                           anchor="middle"))
        if i < n - 1:
            parts.append(_arrow(74, y + h // 2 + 30, 74, y + h + gap + h // 2 - 32))
        parts.append(_step_rect(120, y, 570, h, "@card@", i + 1))
        parts.append(_icon(stage.get("icon"), 138, y + 16, colour, 1.3))
        parts.append(_text(184, y + 42, _fit_words(stage.get("label"), 480, 24), size=24,
                           fill="@ink@", weight="bold"))
        parts.extend(_lines(140, y + 78, stage.get("detail"), 530, size=22,
                            max_lines=max(1, min(3, (h - 90) // 27 + 1)), step=27))
    parts.append(_rect(715, 240, 325, 620, "@soft2@", stroke="@soft_stroke@"))
    parts.append(_icon(notes.get("icon") or "bulb", 735, 258, "@primary@", 1.3))
    parts.append(_text(780, 284, _fit_words(notes.get("heading") or "Notes", 240, 22), size=22,
                       fill="@primary@", weight="bold"))
    used = _bullets(parts, 737, 330, notes.get("lines"), 285, 12, fill="@ink@", mark="→ ")
    lead = _clean(plan.get("tagline")) or _clean(plan["hero"].get("caption"))
    if lead and used <= 10:
        # The rest of the side panel carries the one-line reason this pipeline matters.
        parts.append(_rect(731, 670, 293, 174, "@card@", stroke="@card_stroke@", radius=12))
        parts.append(_icon("target", 749, 688, "@primary@", 1.2))
        parts.append(_text(787, 711, "WHY IT MATTERS", size=22, fill="@primary@", weight="bold"))
        parts.extend(_lines(749, 752, lead, 257, size=22, max_lines=3, step=28,
                            fill="@soft_ink@", weight="bold"))
    rest = [m for m in plan["modules"] if m is not notes][:2]
    _module_row(parts, rest, accent, 880, 200)


def _layout_snake(parts: list[str], plan: dict, headline: str, accent: list[str]) -> None:
    """Steps winding left to right, then right to left, three to a row."""
    cards = _card_list(plan, 6, 9)
    n = len(cards)
    rows = (n + 2) // 3
    _band_header(parts, plan, headline, "THE ROADMAP", "loop")
    gap_x, gap_y, w = 50, 46, 300
    h = 239 if rows == 3 else 260
    for i, card in enumerate(cards):
        r, c = divmod(i, 3)
        col = c if r % 2 == 0 else 2 - c
        x, y, colour = 40 + col * (w + gap_x), 275 + r * (h + gap_y), accent[i % len(accent)]
        parts.append(_step_rect(x, y, w, h, "@card@", i + 1))
        parts.append(_rect(x, y, w, 7, colour, radius=3))
        parts.append(_icon(card.get("icon"), x + 18, y + 22, colour, 1.4))
        parts.append(_text(x + w - 58, y + 50, f"{i + 1:02d}", size=26, fill=colour,
                           weight="bold"))
        title = _wrap(card.get("title"), w - 36, 23, 2) or ["Step"]
        for j, line in enumerate(title):
            parts.append(_text(x + 18, y + 96 + j * 28, line, size=23, fill="@ink@", weight="bold"))
        parts.extend(_lines(x + 18, y + 104 + len(title) * 28, card.get("text"), w - 36, size=22,
                            max_lines=max(1, (h - 120 - len(title) * 28) // 27 + 1), step=27))
        if i < n - 1:
            if c < 2:
                ax = x + w + 4 if r % 2 == 0 else x - 4
                bx = x + w + gap_x - 4 if r % 2 == 0 else x - gap_x + 4
                parts.append(_arrow(ax, y + h // 2, bx, y + h // 2))
            else:
                parts.append(_arrow(x + w // 2, y + h + 4, x + w // 2, y + h + gap_y - 4))
    if rows == 2:
        _module_row(parts, plan["modules"][:3], accent, 865, 215)


def _layout_proscons(parts: list[str], plan: dict, headline: str, accent: list[str]) -> None:
    """How it works down the middle, with the pros on one side and the cons on the other."""
    pros, cons = _pros_cons(plan)
    nodes = plan["hero"]["nodes"]
    _band_header(parts, plan, headline, "THE TRADE-OFFS", "target")
    for x, colour, fill, icon, label, items, mark in (
            (40, "@good@", "@good_soft@", "check", "PROS", pros, "+ "),
            (740, "@bad@", "@bad_soft@", "warning", "CONS", cons, "– ")):
        _half(parts, "left" if x < 540 else "right")
        parts.append(_rect(x, 275, 300, 580, fill, stroke=colour))
        parts.append(_icon(icon, x + 20, 292, colour, 1.4))
        parts.append(_text(x + 66, 320, label, size=26, fill=colour, weight="bold"))
        used = 0
        for item in items:
            wrapped = _wrap(item, 244, 22, 99)
            if used + len(wrapped) > 16:
                _CUTS.append(item)
                break
            for j, line in enumerate(wrapped):
                parts.append(_text(x + 22, 368 + used * 27, (mark if j == 0 else "  ") + line,
                                   size=22, fill="@ink@"))
                used += 1
        _half(parts)
    parts.append(_text(540, 304, "HOW IT WORKS", size=22, fill="@primary@", weight="bold",
                       anchor="middle"))
    n, gap = len(nodes), 30
    h = (528 - gap * (n - 1)) // n
    for i, node in enumerate(nodes):
        y, colour = 326 + i * (h + gap), accent[i % len(accent)]
        parts.append(_step_rect(362, y, 356, h, "@node@", i + 1, radius=12))
        parts.append(_icon(node.get("icon"), 378, y + 14, colour, 1.2))
        parts.append(_text(418, y + 36, _fit_words(node.get("label"), 285, 22) or "Step", size=22,
                           fill="@ink@", weight="bold"))
        parts.extend(_lines(378, y + 64, node.get("detail"), 324, size=22,
                            max_lines=max(1, (h - 64) // 26 + 1), step=26))
        if i < n - 1:
            parts.append(_arrow(540, y + h + 3, 540, y + h + gap - 3))
    _module_row(parts, plan["modules"][:3], accent, 875, 205)


def _layout_masonry(parts: list[str], plan: dict, headline: str, accent: list[str]) -> None:
    """Numbered cards of different heights in two columns: the goal, then the best practice."""
    cards = _card_list(plan, 4, 6)
    top = max(_centre_header(parts, plan, headline, "FIELD NOTES") + 6, 232)
    sized = []
    for card in cards:
        text = _wrap(card.get("text"), 380, 22, 4)
        fix = _wrap(card.get("fix"), 440, 22, 3) if _clean(card.get("fix")) else []
        sized.append((card, text, fix, 76 + len(text) * 27 + (len(fix) * 27 + 56 if fix else 0) + 16))
    columns: list[list] = [[], []]
    heights = [0, 0]
    for i, item in enumerate(sized):
        col = 0 if heights[0] <= heights[1] else 1
        columns[col].append((i, item))
        heights[col] += item[3] + 14
    avail = 1085 - top
    for col, column in enumerate(columns):
        natural = sum(item[3] for _, item in column) + 14 * (len(column) - 1)
        if natural > avail:
            _CUTS.append("masonry overflow")
        spare = max(0, avail - natural)
        x = 40 + col * 508
        if spare >= 170:
            # A big gap becomes a "why it matters" card at the foot of the column.
            fh = min(spare - 14, 230)
            fy = 1085 - fh
            parts.append(_rect(x, fy, 492, fh, "@soft@", stroke="@soft_stroke@"))
            parts.append(_icon("target", x + 20, fy + 20, "@primary@", 1.4))
            parts.append(_text(x + 66, fy + 46, "WHY IT MATTERS", size=22, fill="@primary@",
                               weight="bold"))
            lead = _clean(plan.get("tagline")) or plan["takeaway"]
            parts.extend(_lines(x + 20, fy + 88, lead, 450, size=22, max_lines=(fh - 70) // 28,
                                step=28, fill="@soft_ink@", weight="bold"))
            spare -= fh + 14
        spare //= max(1, len(column))
        y = top
        for i, (card, text, fix, h) in column:
            h += spare
            colour = accent[i % len(accent)]
            parts.append(_step_rect(x, y, 492, h, "@card@", i + 1))
            parts.append(_rect(x, y, 492, 56, "@soft@", radius=14))
            parts.append(_text(x + 20, y + 37, _fit_words(f"{i + 1}. {_clean(card.get('title'))}",
                                                          400, 24), size=24, fill="@ink@",
                               weight="bold"))
            parts.append(_icon(card.get("icon"), x + 440, y + 12, colour, 1.3))
            parts.append(_rect(x + 16, y + 72, 76, 34, colour, radius=8))
            parts.append(_text(x + 54, y + 96, "Goal", size=22, fill="@bg@", weight="bold",
                               anchor="middle"))
            for j, line in enumerate(text):
                parts.append(_text(x + 104, y + 96 + j * 27, line, size=22, fill="@muted@"))
            if fix:
                fh = len(fix) * 27 + 46
                by = y + h - 12 - fh
                parts.append(_rect(x + 12, by, 468, fh, "@soft2@", stroke="@card_stroke@", radius=10))
                parts.append(_text(x + 26, by + 30, "Best practice", size=22, fill=colour,
                                   weight="bold"))
                for j, line in enumerate(fix):
                    parts.append(_text(x + 26, by + 58 + j * 27, line, size=22, fill="@ink@"))
            y += h + 14


_LAYOUTS = {"guide": _layout_guide, "timeline": _layout_timeline,
            "spotlight": _layout_spotlight, "comparison": _layout_comparison,
            "dashboard": _layout_dashboard, "code_focus": _layout_code_focus,
            "incident": _layout_incident, "stack": _layout_stack, "sidebar": _layout_sidebar,
            "matrix": _layout_matrix, "versus": _layout_versus,
            "architecture": _layout_architecture, "progression": _layout_progression,
            "hub": _layout_hub, "profiles": _layout_profiles, "columns": _layout_columns,
            "zigzag": _layout_zigzag, "playbook": _layout_playbook,
            "scorecard": _layout_scorecard, "swimlanes": _layout_swimlanes, "twin": _layout_twin,
            "flowchart": _layout_flowchart, "pipeline": _layout_pipeline, "snake": _layout_snake,
            "proscons": _layout_proscons, "masonry": _layout_masonry}
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
    "matrix": "lists of 6 or 9 problems, mistakes, tips or principles (needs cards)",
    "versus": "one tool or approach against another (needs table)",
    "architecture": "a system's components layer by layer (needs layers)",
    "progression": "a maturity model or evolution in stages (needs stages)",
    "hub": "one central idea and the parts around it",
    "profiles": "4 or 6 types, models or tools, each with what it is and two short lists (needs profiles)",
    "columns": "3-5 personas, roles or options side by side (needs profiles)",
    "zigzag": "5-7 mistakes or sins, each with a symptom and a fix (needs cards with fix)",
    "playbook": "4-6 steps of a playbook, each with what to do (needs cards with fix)",
    "scorecard": "a benchmark of two contenders with headline numbers (needs scorecard and stats)",
    "swimlanes": "3-4 areas, each a short flow of parts (needs layers)",
    "twin": "two options and when each is best, plus how to start (needs table)",
    "flowchart": "a process with parallel branches and a yes/no check (needs decision)",
    "pipeline": "a step-by-step pipeline with side notes (needs stages)",
    "snake": "6-9 ordered steps of a build or roadmap (needs cards)",
    "proscons": "a new technology with clear pros and cons (needs pros and cons)",
    "masonry": "4-6 practical tips, each with a goal and a best practice (needs cards with fix)",
}
POST_TYPES = ("release", "bug_fix", "how_to", "concept", "comparison", "benchmark", "architecture")


def _eligible(plan: dict, headline: str = "") -> list[str]:
    """Layouts that can draw this content cleanly, in a stable order."""
    hero, modules = plan["hero"], plan["modules"]
    n, form = len(hero["nodes"]), _clean(hero.get("form")).lower()
    post_type = _clean(plan.get("post_type")).lower()
    has_stats = any(_clean(m.get("kind")).lower() in STAT_KINDS for m in modules)
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
        "matrix": bool(_cards(plan)),
        "versus": _table(plan) is not None,
        "architecture": bool(_layers(plan)),
        "progression": bool(_stages(plan)),
        "hub": bool(_hub_label(plan, headline)),
        "profiles": len(_profiles(plan)) in (4, 6),
        "columns": 3 <= len(_profiles(plan)) <= 5,
        # A symptom and its fix either side of the spine; fewer than five leaves empty space.
        "zigzag": all(_clean(c.get("fix")) for c in _card_list(plan, 5, 7) or [{}]),
        "playbook": bool(_card_list(plan, 4, 6)),
        "scorecard": _scorecard(plan) is not None and _stats_module(plan) is not None and n <= 4,
        "swimlanes": len(_layers(plan)) >= 3,  # two lanes leave the page half empty
        "twin": _table(plan) is not None and n <= 4,
        "flowchart": _decision(plan) is not None and n >= 3,
        "pipeline": bool(_stages(plan)) and _notes_module(plan) is not None,
        "snake": bool(_card_list(plan, 6, 9)),
        "proscons": bool(_pros_cons(plan)[0]),
        "masonry": all(_clean(c.get("fix")) for c in _card_list(plan, 4, 6) or [{}]),
    }
    return [s for s in STYLES if ok[s]]


def _style_candidates(plan: dict, headline: str = "") -> list[str]:
    """Layouts that suit this content, best first: the planner's pick, then by content type."""
    hero, modules = plan["hero"], plan["modules"]
    n, form = len(hero["nodes"]), _clean(hero.get("form")).lower()
    post_type = _clean(plan.get("post_type")).lower()
    kinds = {_clean(m.get("kind")).lower() for m in modules}
    # Content the planner drew specially for one layout is the strongest signal.
    order = [_clean(plan.get("layout")).lower(), "scorecard", "flowchart", "proscons", "profiles",
             "columns", "matrix", "zigzag", "playbook", "snake", "masonry", "versus", "twin",
             "architecture", "swimlanes", "progression", "pipeline"]
    if form == "before_after":
        order.append("comparison")
    if post_type in ("bug_fix", "breaking_change", "incident"):
        order.append("incident")
    if post_type == "benchmark" or kinds & set(STAT_KINDS):
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
    order += ["sidebar", "hub", "spotlight", "timeline", "guide", "stack"]
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


def choose_style(plan: dict, recent: str | list | tuple | None = None, headline: str = "",
                 rng=None) -> str:
    """A suitable layout not used in the last three posters (or at least not the last one).

    Without rng the best-suited layout wins (stable, for tests). With rng one of the three
    best-suited fresh layouts is picked at random, so the roster is used rather than one favourite.
    """
    return _style_order(plan, recent, headline, rng)[0]


HISTORY = 10  # posters remembered; nothing used in them comes back while a fresh option fits
# The twelve layouts modelled on hand-made LinkedIn infographics; they look the least alike, so a
# random pick prefers them whenever the content fits one.
NEWER_STYLES = ("profiles", "columns", "zigzag", "playbook", "scorecard", "swimlanes", "twin",
                "flowchart", "pipeline", "snake", "proscons", "masonry")


def _least_recent(options: list[str], recent: list[str]) -> list[str]:
    """The options used longest ago (never-used ones count as oldest), keeping their order."""
    def last_use(option: str) -> int:
        return max((i for i, r in enumerate(recent) if r == option), default=-1)
    oldest = min(last_use(o) for o in options)
    return [o for o in options if last_use(o) == oldest]


def _style_order(plan: dict, recent: str | list | tuple | None, headline: str,
                 rng=None) -> list[str]:
    """Every eligible layout in the order to try: the chosen one first, recent ones last.

    Without rng: the best-suited layout not in the last three (stable, for tests). With rng: a
    layout not used in the last HISTORY posters (or, when every suitable one was, the one used
    longest ago), picked at random among the three best-suited, newer layouts first.
    """
    recent = _recent(recent)
    candidates = _style_candidates(plan, headline)
    if rng is None:
        fresh = [s for s in candidates if s not in recent[-3:]]
        if not fresh:
            fresh = [s for s in candidates if s not in recent[-1:]] or candidates
        return fresh + [s for s in candidates if s not in fresh]
    fresh = _least_recent(candidates, recent[-HISTORY:])
    fresh = ([s for s in fresh if s in NEWER_STYLES] + [s for s in fresh if s not in NEWER_STYLES])
    pick = rng.choice(fresh[:3])
    rest = sorted((s for s in candidates if s != pick),
                  key=lambda s: max((i for i, r in enumerate(recent) if r == s), default=-1))
    return [pick] + rest


def theme_family(theme: str) -> str:
    """A theme's look in a word: dark or light page, plus the hue of its banner colour.

    Two themes in the same family (say steel, ocean and seafoam: all navy on white) look alike
    on a feed even though their names differ.
    """
    import colorsys

    palette = THEMES[theme]
    r, g, b = (int(palette["strong"][i:i + 2], 16) / 255 for i in (1, 3, 5))
    hue, light, sat = colorsys.rgb_to_hls(r, g, b)
    bg = palette["bg"]
    dark = sum(int(bg[i:i + 2], 16) for i in (1, 3, 5)) < 3 * 100
    if sat < 0.18 or light < 0.12:
        tone = "neutral"
    else:
        tone = ("red", "orange", "yellow", "green", "teal", "blue", "violet", "pink")[
            int(((hue * 360 + 15) % 360) // 45)]
    return f"{'dark' if dark else 'light'}-{tone}"


def choose_theme(plan: dict, recent: str | list | tuple | None = None, rng=None) -> str:
    """A colour theme that is never one of the last two, and with rng never the same colour
    family (page tone and banner hue) as the last two either.

    Without rng: the planner's hint, else a stable pick from the title. With rng: the hint about
    half the time, otherwise any other fresh theme at random.
    """
    hint = _clean(plan.get("theme")).lower()
    if rng is not None:
        # Never a theme from the last HISTORY posters, nor the colour family of the last two.
        history = [t for t in _recent(recent)[-HISTORY:] if t in THEMES]
        families = {theme_family(t) for t in history[-2:]}
        names = _least_recent(list(THEMES), history)
        names = [t for t in names if theme_family(t) not in families] or names
        if hint in names and rng.random() < 0.5:
            return hint
        return rng.choice(names)
    recent = _recent(recent)[-2:]
    names = [t for t in THEMES if t not in recent]
    if hint in names:
        return hint
    seed = sum(ord(c) for c in _clean(plan.get("title")) + _clean(plan.get("takeaway")))
    return names[seed % len(names)]


# The motions that suit each layout, its signature motion first: a timeline draws its path in, two
# halves slide together, numbers count up, a hub sends ripples out and a grid of cards gets a sweep.
MOTION_SETS = {
    "timeline": ("draw", "build", "flow"), "snake": ("draw", "wave", "flow"),
    "pipeline": ("draw", "build", "flow"), "flowchart": ("draw", "flow", "pulse"),
    "progression": ("draw", "build", "sweep"), "zigzag": ("draw", "sweep", "wave"),
    "architecture": ("draw", "build", "ripple"), "swimlanes": ("draw", "wave", "flow"),
    "comparison": ("slide", "wave", "flow"), "versus": ("slide", "sweep", "build"),
    "twin": ("slide", "ripple", "flow"), "proscons": ("slide", "draw", "flow"),
    "dashboard": ("count", "build", "ripple"), "scorecard": ("count", "slide", "pulse"),
    "hub": ("ripple", "pulse", "draw"), "spotlight": ("ripple", "sweep", "flow"),
    "guide": ("ripple", "draw", "wave"), "sidebar": ("sweep", "draw", "flow"),
    "matrix": ("sweep", "pulse", "ripple"), "masonry": ("sweep", "build", "ripple"),
    "profiles": ("sweep", "wave", "ripple"), "columns": ("sweep", "wave", "build"),
    "playbook": ("build", "sweep", "draw"), "stack": ("build", "ripple", "wave"),
    "code_focus": ("draw", "flow", "sweep"), "incident": ("build", "sweep", "wave"),
}


def choose_motion(plan: dict, recent: str | list | tuple | None = None, rng=None,
                  style: str | None = None) -> str:
    """The GIF's motion style, never one of the last two used (or at least not the last one).

    With a layout, the choice comes from the motions that suit it (MOTION_SETS): with rng its
    signature motion about half the time, otherwise one of its motions used longest ago; without
    rng the first suitable one. Without a layout every motion is a candidate.
    """
    from infographic import MOTIONS

    options = list(MOTION_SETS.get(style or "", MOTIONS))
    recent = _recent(recent)
    fresh = ([m for m in options if m not in recent[-2:]]
             or [m for m in options if m not in recent[-1:]] or options)
    if rng is not None:
        if fresh[0] == options[0] and rng.random() < 0.5:
            return fresh[0]
        return rng.choice(_least_recent(fresh, recent[-HISTORY:]))
    if style:
        return fresh[0]
    return fresh[sum(ord(c) for c in _clean(plan.get("title"))) % len(fresh)]


def choose_variant(options: list[str] | tuple, recent: str | list | tuple | None = None,
                   rng=None) -> str:
    """A detail or finish style: with rng, one of those used longest ago (so all of them take
    turns and none repeats the last); without rng, the first."""
    if rng is None:
        return options[0]
    return rng.choice(_least_recent(list(options), _recent(recent)[-HISTORY:]))


def _render(plan: dict, headline: str, footer: str, style: str, theme: str,
            motion: str = "flow", details: str = "grid", finish: str = "bars",
            header: str | None = None, corners: str = "round") -> tuple[str, list[str]]:
    """Draw one layout; returns the SVG and any text that had to be shortened."""
    _CUTS.clear()
    header = header if header in HEADERS else HEADER_DEFAULTS.get(style, "classic")
    corners = corners if corners in CORNERS else "round"
    _VARIANT.update(details=details, finish=finish, header=header, corners=corners,
                    origin=(540, 130))
    parts: list[str] = []
    _start(parts, style, theme)
    _LAYOUTS[style](parts, plan, headline, list(ACCENTS))
    _bottom(parts, plan, footer)
    parts.append("</svg>")
    ox, oy = _VARIANT["origin"]
    parts[0] = parts[0].replace(
        " data-highlight=", f' data-motion="{motion}" data-details="{details}" '
                            f'data-finish="{finish}" data-header="{header}" '
                            f'data-corners="{corners}" data-origin="{ox},{oy}" '
                            'data-soft="@soft@" data-highlight=', 1)
    return _apply_theme("".join(parts), theme), list(_CUTS)


def poster_from_brief(brief: str, headline: str, footer: str, *,
                      recent_styles: str | list | tuple | None = None,
                      recent_themes: str | list | tuple | None = None, style: str | None = None,
                      theme: str | None = None, rng=None, exclude: tuple | list = (),
                      recent_motions: str | list | tuple | None = None,
                      recent_details: str | list | tuple | None = None,
                      recent_finishes: str | list | tuple | None = None,
                      recent_headers: str | list | tuple | None = None,
                      recent_corners: str | list | tuple | None = None,
                      details: str | None = None, finish: str | None = None,
                      header: str | None = None, corners: str | None = None,
                      motion: str | None = None) -> str | None:
    """Render a complete poster from the blueprint embedded by plan_infographic.

    The layout and colour theme follow the content and always differ from the previous poster's
    (recent_styles, recent_themes, oldest first); rng randomises both among the suitable ones.
    When a layout would have to shorten any text, the next suitable layout is tried, so a phrase
    is never cut off; if every layout needs a cut, the one with the fewest is used.
    exclude skips layouts that already failed a later check. style/theme force a choice, which the
    tests use to cover every pair.
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

    if theme not in THEMES:
        theme = choose_theme(plan, recent_themes, rng)
    options = details_options(plan)
    if details not in options:
        details = choose_variant(options, recent_details, rng)
    if finish not in FINISHES:
        finish = choose_variant(FINISHES, recent_finishes, rng)
    if header not in HEADERS and rng is not None:
        header = choose_variant(HEADERS, recent_headers, rng)
    if corners not in CORNERS:
        corners = choose_variant(CORNERS, recent_corners, rng)

    def motion_for(name: str) -> str:
        from infographic import MOTIONS
        return motion if motion in MOTIONS else choose_motion(plan, recent_motions, rng, name)

    if style in _eligible(plan, headline):
        return _render(plan, headline, footer, style, theme, motion_for(style), details, finish,
                       header, corners)[0]
    order = [s for s in _style_order(plan, recent_styles, headline, rng) if s not in exclude]
    if not order:
        return None
    # The chosen detail and finish styles are tried first; if they would shorten text, the
    # plain grid and bars are tried with the same layout before moving to another layout.
    looks = list(dict.fromkeys([(details, finish), ("grid", finish), ("grid", "bars")]))
    best: tuple[str, list[str]] | None = None
    for name in order:
        for look in looks:
            svg, cuts = _render(plan, headline, footer, name, theme, motion_for(name), *look,
                                header, corners)
            if not cuts:
                return svg
            if best is None or len(cuts) < len(best[1]):
                best = (svg, cuts)
    return best[0]
