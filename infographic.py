"""Infographic engine: Validates and renders pure SVG architecture diagrams to PNG & animated GIF.

This module is responsible for:
1. Extracting pure <svg> markup from LLM responses (stripping markdown fences and extraneous conversational text).
2. Sanitizing and auto-repairing common XML quirks (e.g. converting non-breaking spaces &nbsp; and auto-escaping unescaped ampersands).
3. Enforcing strict structural safety and design quality checks (viewBox dimensions, element limits, minimum font sizes with badge exemptions, emoji rejections, and XSS/SSRF prevention via forbidden elements and external imports).
4. Rendering static high-resolution PNGs via CairoSVG.
5. Transforming static connector lines into dynamic looping streaming data motion to produce smooth 12-frame animated GIFs via CairoSVG and Pillow (PIL).
6. Providing a built-in icon library (ICONS) so the designer can place real icons with <use href="#icon-NAME"/>
   instead of drawing bare boxes; only the icons actually referenced are injected into the SVG.
7. Running soft design-richness checks (design_quality_checks) that reject sparse, empty, overflowing or
   overlapping posters so the designer is asked to redraw them denser and cleaner.
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

# -----------------------------------------------------------------------------
# Icon library: 24x24 stroke icons the designer places via <use href="#icon-NAME" .../>
# -----------------------------------------------------------------------------
_ICON_SOURCES = {
    "check": '<path d="M4 12.5 L9.5 18 L20 6"/>',
    "x": '<path d="M5 5 L19 19 M19 5 L5 19"/>',
    "warning": '<path d="M12 3 L22 20 H2 Z"/><path d="M12 10 V14 M12 17 V17.2"/>',
    "bolt": '<path d="M13 2 L4 14 H11 L10 22 L20 9 H13 Z"/>',
    "database": '<ellipse cx="12" cy="6" rx="8" ry="3"/><path d="M4 6 V18 C4 19.7 7.6 21 12 21 C16.4 21 20 19.7 20 18 V6 M4 12 C4 13.7 7.6 15 12 15 C16.4 15 20 13.7 20 12"/>',
    "gear": '<circle cx="12" cy="12" r="3"/><circle cx="12" cy="12" r="7"/><path d="M12 2 V5 M12 19 V22 M2 12 H5 M19 12 H22 M5 5 L7 7 M17 17 L19 19 M19 5 L17 7 M7 17 L5 19"/>',
    "search": '<circle cx="10" cy="10" r="6"/><path d="M15 15 L21 21"/>',
    "document": '<path d="M6 3 H14 L19 8 V21 H6 Z M14 3 V8 H19 M9 13 H16 M9 17 H16"/>',
    "folder": '<path d="M3 6 H10 L12 8 H21 V19 H3 Z"/>',
    "shield": '<path d="M12 3 L20 6 V12 C20 17 16.5 20 12 21 C7.5 20 4 17 4 12 V6 Z M8.5 12 L11 14.5 L15.5 9.5"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7 V12 L15.5 14"/>',
    "rocket": '<path d="M12 3 C16 5 17 10 15 15 H9 C7 10 8 5 12 3 Z M9 15 L6 19 M15 15 L18 19 M12 15 V21"/><circle cx="12" cy="10" r="1.8"/>',
    "code": '<path d="M8 7 L3 12 L8 17 M16 7 L21 12 L16 17 M14 5 L10 19"/>',
    "user": '<circle cx="12" cy="8" r="4"/><path d="M4 21 C4 16.5 8 14 12 14 C16 14 20 16.5 20 21"/>',
    "cloud": '<path d="M7 18 H17.5 A4.5 4.5 0 0 0 17 9 A6 6 0 0 0 5.5 11 A3.5 3.5 0 0 0 7 18 Z"/>',
    "layers": '<path d="M12 3 L21 8 L12 13 L3 8 Z M3 12.5 L12 17.5 L21 12.5 M3 16.5 L12 21.5 L21 16.5"/>',
    "target": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.5"/>',
    "bulb": '<path d="M9 18 H15 M10 21 H14 M12 3 C8 3 6 6 6 9 C6 11.5 7.5 13 9 14.5 V18 H15 V14.5 C16.5 13 18 11.5 18 9 C18 6 16 3 12 3 Z"/>',
    "arrow": '<path d="M4 12 H20 M14 6 L20 12 L14 18"/>',
    "loop": '<path d="M20 12 A8 8 0 1 1 17.5 6.3 M20 4 V9 H15"/>',
    "lock": '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11 V8 A4 4 0 0 1 16 8 V11"/>',
    "globe": '<circle cx="12" cy="12" r="9"/><path d="M3 12 H21"/><ellipse cx="12" cy="12" rx="4" ry="9"/>',
    "chart": '<path d="M4 20 V4 M4 20 H21 M8 16 V11 M13 16 V7 M18 16 V13"/>',
    "terminal": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 9 L10 12 L7 15 M12 16 H17"/>',
    "box": '<path d="M12 3 L20 7 V17 L12 21 L4 17 V7 Z M4 7 L12 11 L20 7 M12 11 V21"/>',
    "eye": '<path d="M2 12 C5 6 9 5 12 5 C15 5 19 6 22 12 C19 18 15 19 12 19 C9 19 5 18 2 12 Z"/><circle cx="12" cy="12" r="3"/>',
    "sparkle": '<path d="M12 3 L14 10 L21 12 L14 14 L12 21 L10 14 L3 12 L10 10 Z"/>',
    "gauge": '<path d="M4 17 A9 9 0 1 1 20 17 M12 13 L16 8"/>',
    "bug": '<ellipse cx="12" cy="13" rx="5" ry="6"/><path d="M12 7 V19 M7 11 H3 M21 11 H17 M7 16 H4 M20 16 H17 M9 7 L7 4 M15 7 L17 4"/>',
    "cpu": '<rect x="7" y="7" width="10" height="10" rx="1"/><path d="M10 3 V7 M14 3 V7 M10 17 V21 M14 17 V21 M3 10 H7 M3 14 H7 M17 10 H21 M17 14 H21"/>',
    "network": '<circle cx="6" cy="12" r="2.5"/><circle cx="18" cy="6" r="2.5"/><circle cx="18" cy="18" r="2.5"/><path d="M8.2 11 L15.8 7 M8.2 13 L15.8 17"/>',
    "list": '<path d="M9 6 H21 M9 12 H21 M9 18 H21 M3 6 H5 M3 12 H5 M3 18 H5"/>',
}

# Stroked icon parts must opt out of the GIF engine's auto-dashing (it dashes every stroked <path>/<line>),
# otherwise every icon would look dotted in the animated version.
ICONS = {
    name: re.sub(r"<(path|line|polyline)\b", r'<\1 stroke-dasharray="none"', markup)
    for name, markup in _ICON_SOURCES.items()
}
ICON_NAMES = sorted(ICONS)

# Matches references such as href="#icon-bolt" inside <use> elements
ICON_REF_RE = re.compile(r"""href\s*=\s*["']#icon-([A-Za-z0-9_-]+)["']""")


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


def inject_icon_defs(svg: str) -> str:
    """Insert <defs> for every library icon the drawing references via <use href="#icon-NAME"/>.

    Only referenced icons are injected (keeps the SVG small). Unknown names are left alone so
    design_quality_checks() can report them back to the designer.
    """
    names = {n for n in ICON_REF_RE.findall(svg) if n in ICONS and f'id="icon-{n}"' not in svg}
    root = re.search(r"<svg\b[^>]*>", svg)
    if not names or not root:
        return svg
    defs = "".join(
        f'<g id="icon-{n}" fill="none" stroke="currentColor" stroke-width="2" '
        f'stroke-linecap="round" stroke-linejoin="round">{ICONS[n]}</g>'
        for n in sorted(names)
    )
    return svg[:root.end()] + f"<defs>{defs}</defs>" + svg[root.end():]


def finalize_svg(svg: str) -> str:
    """Post-process model output into render-ready SVG.

    - Rewrites xlink:href to plain href (the xlink namespace is not declared by the designer).
    - Lifts near-miss font sizes (18-21) to the 22 minimum. Smaller badge digits are left untouched.
    - Injects the icon library definitions that the drawing references.
    """
    svg = svg.replace("xlink:href=", "href=")
    svg = re.sub(r'font-size\s*=\s*["\'](1[89]|2[01])(?:\.\d+)?["\']', 'font-size="22"', svg)
    return inject_icon_defs(svg)


def _translate(transform: str | None) -> tuple[float, float, bool]:
    """Parse a transform attribute. Returns (dx, dy, is_simple); non-translate transforms are 'complex'."""
    if not transform:
        return 0.0, 0.0, True
    m = re.search(r"translate\(\s*(-?[\d.]+)[\s,]+(-?[\d.]+)\s*\)", transform)
    rest = re.sub(r"translate\([^)]*\)", "", transform).strip()
    return (float(m.group(1)), float(m.group(2)), not rest) if m else (0.0, 0.0, False)


def _float(value, default=None):
    """Best-effort numeric parse of an SVG attribute ("24", "24px"); returns default when not numeric."""
    try:
        return float(str(value).strip().removesuffix("px"))
    except (TypeError, ValueError):
        return default


def _text_boxes(root) -> list[dict]:
    """Estimate the on-canvas bounding box of every text run (no font metrics needed).

    Width is approximated from character count and font size (0.55em proportional, 0.62em monospace).
    Text inside rotated/scaled groups is skipped because its geometry cannot be estimated reliably.
    """
    parents = {child: parent for parent in root.iter() for child in parent}

    def inherited(el, attr, default=None):
        node = el
        while node is not None:
            if node.get(attr) is not None:
                return node.get(attr)
            node = parents.get(node)
        return default

    def offset(el):
        dx = dy = 0.0
        node = el
        while node is not None:
            tx, ty, simple = _translate(node.get("transform"))
            if not simple:
                return None
            dx, dy = dx + tx, dy + ty
            node = parents.get(node)
        return dx, dy

    boxes = []
    for el in root.iter():
        if _local(el.tag) != "text":
            continue
        shift = offset(el)
        if shift is None:
            continue
        runs = [c for c in el if _local(c.tag) == "tspan" and (c.get("x") or c.get("y"))]
        sources = runs or [el]
        for node in sources:
            text = " ".join("".join(node.itertext()).split())
            x = _float(node.get("x"), _float(el.get("x")))
            y = _float(node.get("y"), _float(el.get("y")))
            if not text or x is None or y is None:
                continue
            fs = _float(inherited(node, "font-size"), 24.0)
            family = (inherited(node, "font-family", "") or "").lower()
            weight = str(inherited(node, "font-weight", "") or "").lower()
            factor = 0.62 if any(k in family for k in ("mono", "menlo", "courier")) else 0.55
            if weight in ("bold", "700", "800", "900"):
                factor += 0.05
            width = len(text) * fs * factor
            anchor = inherited(node, "text-anchor", "start")
            x0 = x - width / 2 if anchor == "middle" else x - width if anchor == "end" else x
            x0, y = x0 + shift[0], y + shift[1]
            boxes.append({"text": text, "x0": x0, "x1": x0 + width, "y": y,
                          "top": y - fs * 0.8, "bottom": y + fs * 0.25, "fs": fs})
    return boxes


def design_quality_checks(svg: str) -> list[str]:
    """Soft richness and cleanliness checks for a poster that already passed svg_checks().

    Returns actionable feedback for the designer. The pipeline retries once or twice with this
    feedback but still publishes the best valid drawing, so these never block a post outright.
    Checks: enough content (text/icons/panels), no large empty vertical gaps, no text off-canvas,
    no overlapping text, and only known icon names.
    """
    try:
        root = ET.fromstring(svg)
    except ET.ParseError:
        return []  # structural problems are svg_checks()' job
    issues = []
    boxes = _text_boxes(root)
    all_text = [t for t in root.iter() if _local(t.tag) == "text" and "".join(t.itertext()).strip()]
    if len(all_text) < 16:
        issues.append(f"Too sparse: only {len(all_text)} text labels. A rich poster needs at least 16 "
                      "(title, subtitle, tagline, section headings, bullets, code lines, stats, takeaway).")

    refs = ICON_REF_RE.findall(svg)
    unknown = sorted({n for n in refs if n not in ICONS})
    if unknown:
        issues.append(f"Unknown icon names: {', '.join(unknown)}. Only use icons from the provided list.")
    if len(refs) < 4:
        issues.append(f"Use at least 4 library icons via <use href=\"#icon-NAME\" .../> (found {len(refs)}).")

    panels = sum(1 for el in root.iter() if _local(el.tag) == "rect")
    if panels < 8:
        issues.append(f"Add more structure: use at least 8 rounded panels, cards, pills or bars (found {panels}).")

    ys = sorted([70.0, 1285.0] + [b["y"] for b in boxes])
    gap, start = max(((b - a), a) for a, b in zip(ys, ys[1:]))
    if gap > 240:
        issues.append(f"Large empty area between y={int(start)} and y={int(start + gap)}: fill it with a diagram, "
                      "card, stats strip or code panel so the whole canvas is used.")

    off = [b["text"][:35] for b in boxes if b["x1"] > W - 30 or b["x0"] < 25]
    if off:
        issues.append("Text runs off the canvas or past the margin (shorten or split the line): "
                      + "; ".join(off[:3]))

    overlaps = []
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            wide = min(a["x1"], b["x1"]) - max(a["x0"], b["x0"])
            high = min(a["bottom"], b["bottom"]) - max(a["top"], b["top"])
            if wide > 6 and high > 0.45 * min(a["bottom"] - a["top"], b["bottom"] - b["top"]):
                overlaps.append(f"'{a['text'][:25]}' / '{b['text'][:25]}'")
    if overlaps:
        issues.append("Overlapping text, move these apart: " + "; ".join(overlaps[:3]))
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
