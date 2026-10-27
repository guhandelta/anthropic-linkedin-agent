"""Render a clean infographic PNG (1080x1350, LinkedIn portrait) from a JSON spec.

Drawing the text ourselves (instead of using an image-generation model) guarantees
every word in the image is spelled correctly and matches the post.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1350
PAD = 80


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
    """Render a colour emoji as an RGBA image `px` wide, or None if no emoji font."""
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
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def render_infographic(spec: dict, path: Path, style: dict):
    bg, ink, muted, accent = style["bg"], style["ink"], style["muted"], style["accent"]
    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)

    # Accent bar + title
    d.rectangle([0, 0, W, 16], fill=accent)
    y = PAD
    for line in _wrap(d, spec["title"], _font(64, True), W - 2 * PAD):
        d.text((PAD, y), line, font=_font(64, True), fill=ink)
        y += 76
    y += 8
    for line in _wrap(d, spec.get("subtitle", ""), _font(32), W - 2 * PAD):
        d.text((PAD, y), line, font=_font(32), fill=muted)
        y += 42
    y += 40

    # Points as numbered cards
    points = spec["points"][:5]
    avail = H - y - 220
    card_h = min(190, avail // len(points) - 20)
    for i, p in enumerate(points, 1):
        d.rounded_rectangle([PAD, y, W - PAD, y + card_h], radius=24,
                            fill=style["card"], outline=None)
        cx, cy = PAD + 60, y + card_h // 2
        d.ellipse([cx - 34, cy - 34, cx + 34, cy + 34], fill=accent)
        num = str(i)
        tw = d.textlength(num, font=_font(36, True))
        d.text((cx - tw / 2, cy - 22), num, font=_font(36, True), fill=bg)

        icon = _emoji(p.get("icon", ""), 56) if p.get("icon") else None
        if icon:
            img.paste(icon, (W - PAD - 30 - 56, y + 22), icon)

        tx = PAD + 130
        d.text((tx, y + 26), p["heading"], font=_font(36, True), fill=ink)  # heading <= 32 chars
        ty = y + 76
        for line in _wrap(d, p["detail"], _font(28), W - PAD - tx - 110)[:3]:  # leave room for the icon
            d.text((tx, ty), line, font=_font(28), fill=muted)
            ty += 36
        y += card_h + 20

    # Takeaway footer
    fy = H - 180
    d.rounded_rectangle([PAD, fy, W - PAD, fy + 110], radius=24, fill=accent)
    lines = _wrap(d, spec.get("takeaway", ""), _font(32, True), W - 2 * PAD - 60)[:2]
    ty = fy + 55 - 20 * len(lines)
    for line in lines:
        d.text((PAD + 30, ty), line, font=_font(32, True), fill=bg)
        ty += 40
    d.text((PAD, H - 50), style.get("footer", ""), font=_font(24), fill=muted)

    img.save(path, "PNG")
    return path
