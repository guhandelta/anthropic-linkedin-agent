"""Infographic step: Claude designs a drawing as SVG, this module checks it and renders it to PNG.

Claude is free to pick any visual form (metaphor, scene, map, timeline, character, chart...).
The checks keep the file safe and readable: valid SVG, portrait canvas, no scripts or external
links, no emoji characters, minimum text size, bounded length.
"""
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import cairosvg

W, H = 1080, 1350
MIN_FONT = 22
MAX_ELEMENTS = 1500
FORBIDDEN = {"script", "foreignObject", "image", "iframe", "object", "embed",
             "audio", "video", "animate", "set", "animateTransform", "animateMotion"}
EMOJI_RE = re.compile(r"[☀-➿\U0001F300-\U0001FAFF]")


def extract_svg(text: str) -> str:
    m = re.search(r"<svg\b.*</svg>", text, re.S)
    if not m:
        raise ValueError("Designer did not return an <svg> drawing.")
    svg = m.group(0)
    # Clean &nbsp; into standard space and auto-escape unescaped ampersands
    svg = svg.replace("&nbsp;", " ")
    svg = re.sub(r"&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)", "&amp;", svg)
    return svg


def _local(tag: str) -> str:
    return tag.split("}")[-1]


def svg_checks(svg: str) -> list[str]:
    """Structure and safety checks the drawing must pass before it is rendered."""
    issues = []
    try:
        root = ET.fromstring(svg)
    except ET.ParseError as e:
        return [f"SVG is not valid XML ({e}). Escape & as &amp; and close every tag."]
    if _local(root.tag) != "svg":
        return ["The drawing must start with an <svg> root element."]
    if root.get("viewBox") != f"0 0 {W} {H}":
        issues.append(f'Root svg must have viewBox="0 0 {W} {H}".')
    if re.search(r"""(href|url\()\s*["']?\s*https?:|@import""", svg):
        issues.append("External links and imports are not allowed.")

    elements = list(root.iter())
    if len(elements) > MAX_ELEMENTS:
        issues.append(f"Drawing is too complex ({len(elements)} elements; max {MAX_ELEMENTS}). Simplify.")
    for el in elements:
        tag = _local(el.tag)
        if tag in FORBIDDEN:
            issues.append(f"Element <{tag}> is not allowed.")
        for key, value in el.attrib.items():
            if _local(key) == "href" and not value.startswith("#"):
                issues.append(f"External reference not allowed: {value[:60]}")
        if tag in ("text", "tspan"):
            fs = el.get("font-size", "")
            text_val = "".join(el.itertext()).strip()
            min_allowed = 14 if len(text_val) <= 3 else MIN_FONT
            if re.fullmatch(r"\d+(\.\d+)?", fs) and float(fs) < min_allowed:
                issues.append(f"Text too small (font-size {fs}; minimum {min_allowed}): {text_val[:30]}")

    texts = []
    for el in root.iter():
        if _local(el.tag) == "text":
            t = " ".join("".join(el.itertext()).split())
            if t:
                texts.append(t)
    if len(texts) < 3:
        issues.append("Use at least 3 labelled text elements so the picture explains itself.")
    for t in texts:
        if len(t) > 90:
            issues.append(f"Text line too long (max 90 characters): {t[:40]}...")
        if EMOJI_RE.search(t):
            issues.append(f"Emoji characters are not allowed in the drawing; draw the icon with shapes: {t[:40]}")
    return issues


def render_svg(svg: str, path: Path) -> Path:
    issues = svg_checks(svg)
    if issues:
        raise ValueError("; ".join(issues))
    try:
        cairosvg.svg2png(bytestring=svg.encode("utf-8"), write_to=str(path),
                         output_width=W, output_height=H)
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"The drawing could not be rendered: {e}") from e
    return path


def render_svg_to_gif(svg: str, path: Path, n_frames: int = 12, fps: int = 12) -> Path:
    """Renders a technical SVG infographic into a smooth, looping animated GIF with subtle motion."""
    import math
    import io
    from PIL import Image

    issues = svg_checks(svg)
    if issues:
        raise ValueError("; ".join(issues))

    # Auto-convert solid connector lines/paths into dashed streams if not already dashed
    # (Exclude card rectangles and container boxes, target lines, polylines, and connector paths)
    def _ensure_dashed(m):
        tag = m.group(1)
        attrs = m.group(2).rstrip()
        is_self_closing = attrs.endswith("/")
        if is_self_closing:
            attrs = attrs[:-1].rstrip()
        # If it's a stroked path/line/polyline with no dasharray, make it dashed so it animates
        if "stroke=" in attrs and "stroke-dasharray" not in attrs and not attrs.startswith("rect"):
            attrs += ' stroke-dasharray="10 10"'
        return f"<{tag} {attrs} />" if is_self_closing else f"<{tag} {attrs}>"

    base_svg = re.sub(r'<(line|polyline|path)\s+([^>]*(?:x1=|d="M|points=)[^>]*)>', _ensure_dashed, svg)

    frames = []
    dash_period = 20  # 20 matches 10+10 and loops seamlessly

    for i in range(n_frames):
        phase = 2 * math.pi * (i / n_frames)
        flow_offset = int((i / n_frames) * dash_period)
        pulse_r_delta = 8 * (0.5 + 0.5 * math.sin(phase))
        pulse_op = round(0.85 - 0.45 * (0.5 + 0.5 * math.sin(phase)), 2)

        frame_svg = base_svg

        # Shift dashoffset on all dashed connector lines, paths, and polylines
        def _shift_dash(m):
            tag = m.group(1)
            attrs = m.group(2).rstrip()
            is_self_closing = attrs.endswith("/")
            if is_self_closing:
                attrs = attrs[:-1].rstrip()
            if "stroke-dashoffset" in attrs:
                attrs = re.sub(r'stroke-dashoffset="[^"]*"', f'stroke-dashoffset="{flow_offset}"', attrs)
            else:
                attrs += f' stroke-dashoffset="{flow_offset}"'
            return f"<{tag} {attrs} />" if is_self_closing else f"<{tag} {attrs}>"

        frame_svg = re.sub(r'<(path|line|polyline)\s+([^>]*stroke-dasharray="[^"]*"[^>]*)>', _shift_dash, frame_svg)

        # Dynamic placeholder substitutions
        if "{flow_offset}" in frame_svg:
            frame_svg = frame_svg.replace("{flow_offset}", str(flow_offset))
        if "{pulse_r}" in frame_svg:
            frame_svg = frame_svg.replace("{pulse_r}", str(int(16 + pulse_r_delta)))
        if "{pulse_op}" in frame_svg:
            frame_svg = frame_svg.replace("{pulse_op}", str(pulse_op))

        png_bytes = cairosvg.svg2png(bytestring=frame_svg.encode("utf-8"), output_width=W, output_height=H)
        img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
        resized = img.resize((720, 900), Image.Resampling.LANCZOS)
        quantized = resized.quantize(colors=128, method=Image.Quantize.MEDIANCUT)
        frames.append(quantized)

    path.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        path,
        save_all=True,
        append_images=frames[1:],
        duration=int(1000 / fps),
        loop=0,
        optimize=True,
    )
    return path
