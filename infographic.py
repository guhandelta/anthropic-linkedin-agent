"""Draw the infographic PNG (1080x1350, LinkedIn portrait) from a structured spec.

Every word is drawn by code, so labels are exact and match the post. Three layouts:
  pie   - 3 to 5 parts of one whole, drawn as slices of a round object (with callouts)
  stack - 3 to 5 layers or priorities, band heights follow each part's "value" (with callouts)
  flow  - 3 to 5 ordered steps, drawn as boxes joined by arrows
"""
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1350
PAD = 60
TOP, BOTTOM = 340, 1130          # content area under the title
CALL_W = 290                     # callout pill width (sides of pie and stack)
LAYOUTS = ("pie", "stack", "flow")
PALETTE = ["#FFD9B3", "#FFF3B0", "#CDEFD9", "#FAD2E1", "#D6E4FF"]
DOTS = ["#E76F51", "#C9A227", "#2A9D8F", "#D6457A", "#3B7DD8"]

_S = {}  # colours from config, set by render_infographic


def _font(size, bold=False):
    candidates = (["DejaVuSans-Bold.ttf", "Arial Bold.ttf", "arialbd.ttf"] if bold
                  else ["DejaVuSans.ttf", "Arial.ttf", "arial.ttf"])
    for name in candidates:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


EMOJI_FONTS = [("NotoColorEmoji.ttf", 109),
               ("/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf", 109),
               ("/System/Library/Fonts/Apple Color Emoji.ttc", 160)]


def _emoji(char: str, px: int):
    """Colour emoji as an RGBA image px wide, or None if no emoji font is installed."""
    for name, native in EMOJI_FONTS:
        try:
            font = ImageFont.truetype(name, native)
        except OSError:
            continue
        canvas = Image.new("RGBA", (native * 2, native * 2), (0, 0, 0, 0))
        ImageDraw.Draw(canvas).text((native // 2, native // 2), char, font=font, embedded_color=True)
        box = canvas.getbbox()
        if not box:
            return None
        return canvas.crop(box).resize((px, px), Image.LANCZOS)
    return None


def _wrap(draw, text, font, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        test = f"{cur} {w}".strip()
        if draw.textlength(test, font=font) <= max_w:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def infographic_checks(spec: dict) -> list[str]:
    """Structure checks the writer's spec must pass before anything is drawn."""
    issues = []
    if spec.get("layout") not in LAYOUTS:
        issues.append(f"Infographic layout must be one of {', '.join(LAYOUTS)}.")
    parts = spec.get("parts") or []
    if not 3 <= len(parts) <= 5:
        issues.append(f"Infographic needs 3 to 5 parts (found {len(parts)}).")
    if len(spec.get("title", "")) > 60:
        issues.append("Infographic title must be 60 characters or fewer.")
    for p in parts:
        if not p.get("label"):
            issues.append("Every infographic part needs a label.")
        if len(p.get("label", "")) > 24:
            issues.append(f"Label too long (max 24): {p.get('label')}")
        if len(p.get("detail", "")) > 70:
            issues.append(f"Detail too long (max 70): {p.get('label')}")
        if p.get("icon") and len(p["icon"]) > 2:
            issues.append(f"Icon must be a single emoji: {p.get('icon')}")
    return issues


# ---------------------------------------------------------------- shared pieces
def _leader(d, p0, p1, dot):
    d.line([p0, p1], fill=dot, width=4)
    r = 11
    d.ellipse([p1[0] - r, p1[1] - r, p1[0] + r, p1[1] + r], fill=dot, outline="#FFFFFF", width=4)


def _callout(img, d, side, cy, part, fill, dot, anchor):
    """A rounded label pill beside the object, joined to its anchor point by a leader line."""
    label_f, detail_f = _font(28, True), _font(22)
    icon = _emoji(part["icon"], 36) if part.get("icon") else None
    tx = 18 + (46 if icon else 0)
    avail = CALL_W - tx - 16
    label_lines = _wrap(d, part["label"], label_f, avail)[:2]
    detail_lines = _wrap(d, part.get("detail", ""), detail_f, avail)[:3]
    h = 16 + 34 * len(label_lines) + 8 + 26 * len(detail_lines) + 16
    x0 = 30 if side == "left" else W - 30 - CALL_W
    y0 = int(cy - h / 2)
    d.rounded_rectangle([x0, y0, x0 + CALL_W, y0 + h], radius=22, fill=fill)
    if icon:
        img.paste(icon, (x0 + 14, y0 + 16), icon)
    y = y0 + 14
    for line in label_lines:
        d.text((x0 + tx, y), line, font=label_f, fill=_S["ink"])
        y += 34
    y += 8
    for line in detail_lines:
        d.text((x0 + tx, y), line, font=detail_f, fill=_S["muted"])
        y += 26
    edge = (x0 + CALL_W) if side == "left" else x0
    _leader(d, (edge, cy), anchor, dot)


def _place_callouts(img, d, items):
    """items: (part, side, anchor, fill, dot). Spreads pills evenly down each side."""
    for side in ("left", "right"):
        group = sorted((it for it in items if it[1] == side), key=lambda it: it[2][1])
        n = len(group)
        for k, (part, _, anchor, fill, dot) in enumerate(group):
            if n == 1:
                cy = anchor[1]
            else:
                cy = TOP + 80 + k * (BOTTOM - TOP - 160) / (n - 1)
            _callout(img, d, side, cy, part, fill, dot, anchor)


# ---------------------------------------------------------------- layouts
def _pie(img, d, parts):
    cx, cy, R = W // 2, (TOP + BOTTOM) // 2, 230
    n, start = len(parts), -math.pi / 2
    items = []
    for i, p in enumerate(parts):
        a0 = start + 2 * math.pi * i / n
        a1 = start + 2 * math.pi * (i + 1) / n
        d.pieslice([cx - R, cy - R, cx + R, cy + R], math.degrees(a0), math.degrees(a1),
                   fill=PALETTE[i % len(PALETTE)], outline="#FFFFFF", width=6)
        am = (a0 + a1) / 2
        anchor = (cx + 0.6 * R * math.cos(am), cy + 0.6 * R * math.sin(am))
        side = "left" if anchor[0] < cx else "right"
        items.append((p, side, anchor, PALETTE[i % len(PALETTE)], DOTS[i % len(DOTS)]))
    _place_callouts(img, d, items)


def _stack(img, d, parts):
    cx, colw, gap = W // 2, 320, 8
    top, avail = TOP + 40, BOTTOM - TOP - 40
    vals = [max(float(p.get("value", 1)), 0.01) for p in parts]
    total, usable = sum(vals), avail - gap * (len(parts) - 1)
    items, y = [], top
    for i, p in enumerate(parts):
        h = usable * vals[i] / total
        fill, dot = PALETTE[i % len(PALETTE)], DOTS[i % len(DOTS)]
        d.rounded_rectangle([cx - colw // 2, y, cx + colw // 2, y + h], radius=16,
                            fill=fill, outline=dot, width=3)
        side = "left" if i % 2 == 0 else "right"
        edge_x = cx - colw // 2 if side == "left" else cx + colw // 2
        items.append((p, side, (edge_x, y + h / 2), fill, dot))
        y += h + gap
    _place_callouts(img, d, items)


def _flow(img, d, parts):
    n, bw, gap = len(parts), 560, 22
    x0 = W // 2 - bw // 2
    bh = (BOTTOM - TOP - gap * (n - 1)) // n
    y = TOP
    for i, p in enumerate(parts):
        fill, dot = PALETTE[i % len(PALETTE)], DOTS[i % len(DOTS)]
        d.rounded_rectangle([x0, y, x0 + bw, y + bh], radius=24, fill=fill, outline=dot, width=3)
        tx = x0 + 28
        icon = _emoji(p["icon"], 44) if p.get("icon") else None
        if icon:
            img.paste(icon, (x0 + 22, y + bh // 2 - 22), icon)
            tx += 60
        d.text((tx, y + 18), p["label"], font=_font(30, True), fill=_S["ink"])
        for k, line in enumerate(_wrap(d, p.get("detail", ""), _font(24), x0 + bw - tx - 24)[:2]):
            d.text((tx, y + 60 + 28 * k), line, font=_font(24), fill=_S["muted"])
        if i < n - 1:
            ax = W // 2
            d.line([(ax, y + bh), (ax, y + bh + gap - 6)], fill=dot, width=5)
            d.polygon([(ax - 12, y + bh + gap - 12), (ax + 12, y + bh + gap - 12),
                       (ax, y + bh + gap)], fill=dot)
        y += bh + gap


# ---------------------------------------------------------------- render
def _centered(d, text, font, y, fill, max_w=W - 2 * PAD, line_h=None):
    line_h = line_h or int(font.size * 1.2)
    for line in _wrap(d, text, font, max_w):
        w = d.textlength(line, font=font)
        d.text(((W - w) / 2, y), line, font=font, fill=fill)
        y += line_h
    return y


def render_infographic(spec: dict, path: Path, style: dict) -> Path:
    issues = infographic_checks(spec)
    if issues:
        raise ValueError("; ".join(issues))
    _S.update(ink=style["ink"], muted=style["muted"])
    img = Image.new("RGB", (W, H), style["bg"])
    d = ImageDraw.Draw(img)

    d.rectangle([0, 0, W, 14], fill=style["accent"])
    y = _centered(d, spec["title"], _font(60, True), 56, style["ink"], line_h=72)
    _centered(d, spec.get("subtitle", ""), _font(30), y + 6, style["muted"], line_h=40)

    layout = spec["layout"]
    {"pie": _pie, "stack": _stack, "flow": _flow}[layout](img, d, spec["parts"])

    # takeaway pill
    fy = 1170
    d.rounded_rectangle([PAD, fy, W - PAD, fy + 90], radius=24, fill=style["accent"])
    tk_f = _font(30, True)
    lines = _wrap(d, spec.get("takeaway", ""), tk_f, W - 2 * PAD - 50)[:2]
    ty = fy + 45 - 19 * len(lines)
    for line in lines:
        w = d.textlength(line, font=tk_f)
        d.text(((W - w) / 2, ty), line, font=tk_f, fill=style["bg"])
        ty += 38
    fw = d.textlength(style.get("footer", ""), font=_font(24))
    d.text(((W - fw) / 2, H - 56), style.get("footer", ""), font=_font(24), fill=style["muted"])

    img.save(path, "PNG")
    return path
