"""Rendered layout check: finds overlapping, hidden, clipped and spilling items in a poster.

design_quality_checks() in infographic.py estimates text widths from character counts and only
compares text with text. That misses real problems: a label covered by a card drawn on top of it,
text in the same colour as its background, an icon sitting on a label, a line running through
text, text spilling out of its card, or ink cut off at the canvas edge.

This module measures the drawing the way CairoSVG actually renders it, so the result matches the
PNG and GIF exactly (same fonts, same engine). For every item it renders:
  - the item alone on a padded transparent canvas, which gives its exact ink mask, and
  - the full poster without that item, which shows how much of the item is visible in the poster.
The masks are compared pixel by pixel. Rendering runs at half scale, so a typical poster takes a few
seconds and needs no browser or extra dependency.
"""

import io
import re
import xml.etree.ElementTree as ET

import cairosvg
from PIL import Image, ImageChops, ImageFilter

SVG_NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG_NS)
ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")

W, H = 1080, 1350
SCALE = 0.5          # render at half size: 1 mask pixel = 2 SVG units
PAD = 120            # SVG units of extra canvas on every side, to catch ink that falls off the poster
NON_DRAWN = {"defs", "marker", "clipPath", "mask", "pattern", "symbol", "linearGradient",
             "radialGradient", "filter", "title", "desc", "metadata", "style"}

# Tuning: a text item counts as hidden when less than HIDDEN_RATIO of its core ink pixels change the
# poster when the item is removed, and as partly hidden below PARTLY_RATIO.
HIDDEN_RATIO = 0.35
PARTLY_RATIO = 0.80
DIFF_LEVEL = 40      # per-channel difference (0-255) that counts as "this pixel shows the item"
MIN_OVERLAP_PX = 4   # mask pixels (about 16 square SVG units) before two items count as overlapping


def _local(tag: str) -> str:
    return tag.split("}")[-1]


def _label(el) -> str:
    tag = _local(el.tag)
    if tag == "text":
        return "'" + " ".join("".join(el.itertext()).split())[:30] + "'"
    if tag == "use":
        href = el.get("href") or el.get("{http://www.w3.org/1999/xlink}href") or ""
        return f"icon {href.lstrip('#').removeprefix('icon-')}"
    return f"<{tag}>"


class _Poster:
    """Holds the parsed poster and renders variants of it on a padded canvas."""

    def __init__(self, svg: str):
        self.root = ET.fromstring(svg)
        self.root.set("viewBox", f"{-PAD} {-PAD} {W + 2 * PAD} {H + 2 * PAD}")
        for attr in ("width", "height"):
            self.root.attrib.pop(attr, None)
        self.size = (round((W + 2 * PAD) * SCALE), round((H + 2 * PAD) * SCALE))
        self.parents = {c: p for p in self.root.iter() for c in p}
        self.items = [el for el in self.root.iter() if el is not self.root and self._drawn(el)]
        self.order = {el: i for i, el in enumerate(self.root.iter())}

    def _drawn(self, el) -> bool:
        node = el
        while node is not None and node is not self.root:
            if _local(node.tag) in NON_DRAWN:
                return False
            node = self.parents.get(node)
        return True

    def render(self) -> Image.Image:
        png = cairosvg.svg2png(bytestring=ET.tostring(self.root), output_width=self.size[0],
                               output_height=self.size[1])
        return Image.open(io.BytesIO(png)).convert("RGBA")

    def solo(self, el) -> Image.Image:
        """Binary ink mask of one item drawn alone (its group transforms and opacity still apply)."""
        old_root, old_el = self.root.get("visibility"), el.get("visibility")
        self.root.set("visibility", "hidden")
        el.set("visibility", "visible")
        try:
            alpha = self.render().getchannel("A")
        finally:
            _restore(self.root, "visibility", old_root)
            _restore(el, "visibility", old_el)
        return alpha.point(lambda a: 255 if a > 96 else 0).convert("1")

    def without(self, el) -> Image.Image:
        old = el.get("visibility")
        el.set("visibility", "hidden")
        try:
            return self.render()
        finally:
            _restore(el, "visibility", old)

    def to_svg(self, box) -> tuple[int, int, int, int]:
        """Mask pixel box -> SVG coordinates."""
        x0, y0, x1, y1 = box
        return (round(x0 / SCALE - PAD), round(y0 / SCALE - PAD),
                round(x1 / SCALE - PAD), round(y1 / SCALE - PAD))


def _restore(el, attr, old):
    if old is None:
        el.attrib.pop(attr, None)
    else:
        el.set(attr, old)


def _count(mask: Image.Image) -> int:
    return mask.convert("L").histogram()[255]


def _and(a: Image.Image, b: Image.Image) -> Image.Image:
    return ImageChops.logical_and(a, b)


def _grow(mask: Image.Image, px: int = 1) -> Image.Image:
    return mask.convert("L").filter(ImageFilter.MaxFilter(2 * px + 1)).convert("1")


def _visible_share(full: Image.Image, without: Image.Image, core: Image.Image) -> float:
    """Share of an item's core ink pixels that actually change the poster when the item is drawn."""
    diff = ImageChops.difference(full.convert("RGB"), without.convert("RGB"))
    changed = diff.convert("L").point(lambda v: 255 if v >= DIFF_LEVEL // 3 else 0)
    r, g, b = diff.split()
    strong = ImageChops.lighter(ImageChops.lighter(r, g), b).point(lambda v: 255 if v >= DIFF_LEVEL else 0)
    changed = ImageChops.lighter(changed, strong).convert("1")
    total = _count(core)
    return _count(_and(changed, core)) / total if total else 1.0


def _is_stroke_line(el) -> bool:
    """Open stroked lines and connectors (not filled shapes)."""
    tag = _local(el.tag)
    if tag in ("line", "polyline"):
        return True
    if tag == "path":
        fill = (el.get("fill") or "").strip().lower()
        return fill == "none" and bool(el.get("stroke"))
    return False


def layout_issues(svg: str, max_items: int = 4) -> list[str]:
    """Return human-readable layout problems found in the rendered poster (empty list = clean).

    Reports: text or icons cut off at the canvas edge; text that is hidden or partly hidden (covered
    by a later shape, or the same colour as what is behind it); text overlapping text, icons or
    lines; text spilling out of the card it sits in; icons overlapping each other.
    """
    try:
        poster = _Poster(svg)
    except ET.ParseError:
        return []  # svg_checks() reports invalid XML

    canvas = Image.new("1", poster.size, 0)
    inner = (round(PAD * SCALE), round(PAD * SCALE), round((PAD + W) * SCALE), round((PAD + H) * SCALE))
    canvas.paste(1, inner)
    outside = ImageChops.invert(canvas.convert("L")).convert("1")

    texts = [el for el in poster.items if _local(el.tag) == "text" and "".join(el.itertext()).strip()]
    icons = [el for el in poster.items if _local(el.tag) == "use"]
    lines = [el for el in poster.items if _is_stroke_line(el)]
    cards = [el for el in poster.items if _local(el.tag) == "rect"]

    full = poster.render()
    masks = {el: poster.solo(el) for el in texts + icons + lines + cards}
    problems: dict[str, list[str]] = {}

    def add(kind, text):
        problems.setdefault(kind, []).append(text)

    # 1. Cut off at the canvas edge, or drawing nothing at all
    for el in texts + icons:
        if not masks[el].getbbox():
            add("Draws nothing (zero size, zero opacity or hidden)", _label(el))
        elif _count(_and(masks[el], outside)) > MIN_OVERLAP_PX:
            add("Cut off at the canvas edge", _label(el))

    # 2. Hidden or partly hidden: removing the item barely changes the poster
    for el in texts + icons:
        core = masks[el].convert("L").filter(ImageFilter.MinFilter(3)).convert("1")
        if _count(core) < 6:
            core = masks[el]
        core = _and(core, canvas)
        if not core.getbbox():
            continue
        share = _visible_share(full, poster.without(el), core)
        if share < HIDDEN_RATIO:
            add("Hidden (covered by a later shape or same colour as its background)",
                f"{_label(el)} ({share:.0%} visible)")
        elif share < PARTLY_RATIO:
            add("Partly covered", f"{_label(el)} ({share:.0%} visible)")

    # 3. Overlaps between text, icons and lines
    grown = {el: _grow(masks[el]) for el in texts}
    for i, a in enumerate(texts):
        for b in texts[i + 1:]:
            if _count(_and(grown[a], masks[b])) > MIN_OVERLAP_PX:
                add("Text overlaps text", f"{_label(a)} / {_label(b)}")
        for icon in icons:
            if _count(_and(grown[a], masks[icon])) > MIN_OVERLAP_PX:
                add("Icon overlaps text", f"{_label(icon)} on {_label(a)}")
        for line in lines:
            if _count(_and(grown[a], masks[line])) > MIN_OVERLAP_PX:
                add("Line or arrow crosses text", f"{_label(a)}")
    for i, a in enumerate(icons):
        for b in icons[i + 1:]:
            if _count(_and(masks[a], masks[b])) > MIN_OVERLAP_PX:
                add("Icons overlap", f"{_label(a)} / {_label(b)}")

    # 4. Text spilling out of the card it starts in (smallest rect drawn before it that holds its start)
    canvas_area = W * H * SCALE * SCALE
    card_boxes = {el: masks[el].getbbox() for el in cards}
    for t in texts:
        box = masks[t].getbbox()
        if not box:
            continue
        probe = (box[0] + 1, (box[1] + box[3]) // 2)
        holders = []
        for card in cards:
            cb = card_boxes[card]
            if not cb or poster.order[card] > poster.order[t]:
                continue
            area = (cb[2] - cb[0]) * (cb[3] - cb[1])
            if area > 0.6 * canvas_area or not masks[card].getpixel(probe):
                continue
            holders.append((area, -poster.order[card], card))
        if not holders:
            continue
        card = min(holders, key=lambda h: h[:2])[2]
        spill = ImageChops.subtract(masks[t].convert("L"), _grow(masks[card], 2).convert("L")).convert("1")
        if _count(spill) > MIN_OVERLAP_PX:
            add("Text spills out of its card", _label(t))

    issues = []
    for kind, items in problems.items():
        shown = "; ".join(dict.fromkeys(items))  # keep order, drop duplicates
        parts = shown.split("; ")
        extra = f" (+{len(parts) - max_items} more)" if len(parts) > max_items else ""
        issues.append(f"{kind}: " + "; ".join(parts[:max_items]) + extra)
    return issues


def gif_dash_issues(original_svg: str, gif_svg: str, max_items: int = 4) -> list[str]:
    """Shapes the GIF engine turned dashed that are not connectors (filled shapes, closed outlines)."""
    try:
        before = [el for el in ET.fromstring(original_svg).iter()]
        after = [el for el in ET.fromstring(gif_svg).iter()]
    except ET.ParseError:
        return []
    if len(before) != len(after):
        return []
    hit = []
    for a, b in zip(before, after):
        if a.get("stroke-dasharray") is None and b.get("stroke-dasharray") is not None:
            fill = (a.get("fill") or "").strip().lower()
            d = (a.get("d") or "").strip().lower()
            if _local(a.tag) == "path" and (fill != "none" or d.endswith("z")):
                hit.append(f"<path> {d[:24]}")
            elif a.get("marker-end") is None and a.get("marker-start") is None:
                hit.append(f"<{_local(a.tag)}> without arrowhead")
    if not hit:
        return []
    extra = f" (+{len(hit) - max_items} more)" if len(hit) > max_items else ""
    return ["GIF turns these non-connector outlines into moving dashes (add stroke-dasharray=\"none\"): "
            + "; ".join(hit[:max_items]) + extra]


def gif_issues(svg: str, frame_svgs: list[str]) -> list[str]:
    """Check the animated GIF frames the same way as the PNG.

    The GIF engine rewrites the SVG (auto-dashed connectors, moving dash offsets, pulsing rings), so
    an item that is clean in the PNG can still collide or vanish in a frame. Two frames are checked:
    the pulse's largest and smallest states (a quarter and three quarters through the loop).
    """
    if not frame_svgs:
        return []
    picks = sorted({len(frame_svgs) // 4, (3 * len(frame_svgs)) // 4})
    issues = gif_dash_issues(svg, frame_svgs[picks[0]])
    for k in picks:
        for issue in layout_issues(frame_svgs[k]):
            if issue not in issues:
                issues.append(issue)
    return [f"GIF: {i}" for i in issues]


if __name__ == "__main__":
    # Check saved posters: python layout_check.py output/*/infographic_*.svg
    import sys
    from infographic import finalize_svg, gif_frame_svgs

    failed = 0
    for name in sys.argv[1:]:
        text = finalize_svg(open(name, encoding="utf-8").read())
        png = layout_issues(text)
        found = png + [i for i in gif_issues(text, gif_frame_svgs(text)) if i.removeprefix("GIF: ") not in png]
        failed += bool(found)
        print(("FAIL " if found else "PASS ") + name)
        for issue in found:
            print("   - " + issue)
    sys.exit(1 if failed else 0)
