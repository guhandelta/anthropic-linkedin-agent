"""Infographic engine: Validates and renders pure SVG architecture diagrams to PNG & animated GIF.

This module is responsible for:
1. Extracting pure <svg> markup from LLM responses (stripping markdown fences and extraneous conversational text).
2. Sanitizing and auto-repairing common XML quirks (e.g. converting non-breaking spaces &nbsp; and auto-escaping unescaped ampersands).
3. Enforcing strict structural safety and design quality checks (viewBox dimensions, element limits, minimum font sizes with badge exemptions, emoji rejections, and XSS/SSRF prevention via forbidden elements and external imports).
4. Rendering static high-resolution PNGs via CairoSVG.
5. Transforming static connector lines into dynamic looping streaming data motion to produce smooth 12-frame animated GIFs via CairoSVG and Pillow (PIL).
"""

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import cairosvg

# Standard canvas dimensions for LinkedIn portrait infographics (4:5 aspect ratio)
W, H = 1080, 1350

# Minimum font size in SVG units to ensure high readability on mobile devices
MIN_FONT = 22

# Cap on maximum XML elements to prevent overly complex or unrenderable vector trees
MAX_ELEMENTS = 1500

# Elements forbidden for security (XSS, script injection) and deterministic offline rendering
FORBIDDEN = {
    "script", "foreignObject", "image", "iframe", "object", "embed",
    "audio", "video", "animate", "set", "animateTransform", "animateMotion"
}

# Regex to detect and reject raw emoji characters in SVG text elements (vectors/shapes should be used instead)
EMOJI_RE = re.compile(r"[☀-➿\U0001F300-\U0001FAFF]")


def extract_svg(text: str) -> str:
    """Extract raw <svg>...</svg> markup from the model's text response and repair XML entities.
    
    - Matches the outermost <svg ... </svg> block using DOTALL.
    - Replaces non-standard HTML &nbsp; with a standard space.
    - Auto-escapes raw ampersands ('&' not part of a valid XML entity like &amp; or &#123;) to ensure XML validity.
    """
    m = re.search(r"<svg\b.*</svg>", text, re.S)
    if not m:
        raise ValueError("Designer did not return an <svg> drawing.")
    svg = m.group(0)
    
    # Clean &nbsp; into standard space and auto-escape unescaped ampersands
    svg = svg.replace("&nbsp;", " ")
    svg = re.sub(r"&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)", "&amp;", svg)
    return svg


def _local(tag: str) -> str:
    """Extract the local XML tag name without its namespace prefix (e.g. '{http://...}svg' -> 'svg')."""
    return tag.split("}")[-1]


def svg_checks(svg: str) -> list[str]:
    """Perform structure, safety, and readability checks on the SVG drawing before rendering.
    
    Returns a list of issue descriptions. An empty list signifies a fully valid, publication-grade diagram.
    """
    issues = []
    
    # 1. XML parsing and syntax check
    try:
        root = ET.fromstring(svg)
    except ET.ParseError as e:
        return [f"SVG is not valid XML ({e}). Escape & as &amp; and close every tag."]
        
    # 2. Root element must be <svg>
    if _local(root.tag) != "svg":
        return ["The drawing must start with an <svg> root element."]
        
    # 3. Canvas viewBox verification (1080x1350 portrait)
    if root.get("viewBox") != f"0 0 {W} {H}":
        issues.append(f'Root svg must have viewBox="0 0 {W} {H}".')
        
    # 4. Ban external fonts, CSS @import, or external image links
    if re.search(r"""(href|url\()\s*["']?\s*https?:|@import""", svg):
        issues.append("External links and imports are not allowed.")

    # 5. Element complexity limit
    elements = list(root.iter())
    if len(elements) > MAX_ELEMENTS:
        issues.append(f"Drawing is too complex ({len(elements)} elements; max {MAX_ELEMENTS}). Simplify.")
        
    # 6. Tag-level security and attribute checks
    for el in elements:
        tag = _local(el.tag)
        if tag in FORBIDDEN:
            issues.append(f"Element <{tag}> is not allowed.")
        for key, value in el.attrib.items():
            if _local(key) == "href" and not value.startswith("#"):
                issues.append(f"External reference not allowed: {value[:60]}")
                
        # 7. Typography readability checks (allow smaller fonts for tiny badge numbers like (1), (2), (3))
        if tag in ("text", "tspan"):
            fs = el.get("font-size", "")
            text_val = "".join(el.itertext()).strip()
            min_allowed = 14 if len(text_val) <= 3 else MIN_FONT
            if re.fullmatch(r"\d+(\.\d+)?", fs) and float(fs) < min_allowed:
                issues.append(f"Text too small (font-size {fs}; minimum {min_allowed}): {text_val[:30]}")

    # 8. Text density and character safety checks
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
    """Render valid SVG text into a high-resolution PNG image using CairoSVG."""
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
    """Render a technical SVG infographic into a smooth, seamlessly looping animated GIF.
    
    Animation pipeline:
    1. Detects connector lines and data flow paths. Auto-applies dashed stroke arrays if solid.
    2. Generates 12 discrete animation frames by shifting stroke-dashoffset across a 20px period.
    3. Substitutes dynamic pulse placeholders ({pulse_r}, {pulse_op}) for pulsing radar rings.
    4. Renders each frame via CairoSVG to a bitmap, resizes with LANCZOS antialiasing to 720x900,
       and quantizes to a 128-color median cut palette for compact file size and high fidelity.
    5. Saves as a looping animated GIF.
    """
    import math
    import io
    from PIL import Image

    # Validate SVG validity before proceeding
    issues = svg_checks(svg)
    if issues:
        raise ValueError("; ".join(issues))

    # Helper: Ensure connector lines have stroke-dasharray so they animate
    def _ensure_dashed(m):
        tag = m.group(1)
        attrs = m.group(2).rstrip()
        is_self_closing = attrs.endswith("/")
        if is_self_closing:
            attrs = attrs[:-1].rstrip()
        if "stroke=" in attrs and "stroke-dasharray" not in attrs and not attrs.startswith("rect"):
            attrs += ' stroke-dasharray="10 10"'
        return f"<{tag} {attrs} />" if is_self_closing else f"<{tag} {attrs}>"

    base_svg = re.sub(r'<(line|polyline|path)\s+([^>]*(?:x1=|d="M|points=)[^>]*)>', _ensure_dashed, svg)

    frames = []
    dash_period = 20  # 20 matches dash pattern "10 10" and loops seamlessly without jump cuts

    for i in range(n_frames):
        phase = 2 * math.pi * (i / n_frames)
        flow_offset = int((i / n_frames) * dash_period)
        pulse_r_delta = 8 * (0.5 + 0.5 * math.sin(phase))
        pulse_op = round(0.85 - 0.45 * (0.5 + 0.5 * math.sin(phase)), 2)

        frame_svg = base_svg

        # Shift dashoffset on all dashed connector lines to simulate flowing data packets
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

        # Dynamic placeholder substitutions for animated radar/pulse rings
        if "{flow_offset}" in frame_svg:
            frame_svg = frame_svg.replace("{flow_offset}", str(flow_offset))
        if "{pulse_r}" in frame_svg:
            frame_svg = frame_svg.replace("{pulse_r}", str(int(16 + pulse_r_delta)))
        if "{pulse_op}" in frame_svg:
            frame_svg = frame_svg.replace("{pulse_op}", str(pulse_op))

        # Render frame to PNG buffer, resize cleanly, and quantize palette
        png_bytes = cairosvg.svg2png(bytestring=frame_svg.encode("utf-8"), output_width=W, output_height=H)
        img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
        resized = img.resize((720, 900), Image.Resampling.LANCZOS)
        quantized = resized.quantize(colors=128, method=Image.Quantize.MEDIANCUT)
        frames.append(quantized)

    # Save animated GIF with loop=0 (infinite loop)
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
