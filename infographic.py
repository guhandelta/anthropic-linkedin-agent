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
    return m.group(0)


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
            if re.fullmatch(r"\d+(\.\d+)?", fs) and float(fs) < MIN_FONT:
                issues.append(f"Text too small (font-size {fs}; minimum {MIN_FONT}).")

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
