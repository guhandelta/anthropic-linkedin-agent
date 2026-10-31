import io
from pathlib import Path
import pytest
from PIL import Image

from infographic import (
    extract_svg,
    svg_checks,
    render_svg,
    render_svg_to_gif,
    design_quality_checks,
    finalize_svg,
    inject_icon_defs,
    ICONS,
    ICON_NAMES,
    _float,
    _translate,
    W,
    H,
    MIN_FONT,
    MAX_ELEMENTS,
)

SAMPLE_VALID_SVG = f"""<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <marker id="arrow" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 1.5 L 8 5 L 0 8.5 z" fill="#2563EB"/>
    </marker>
  </defs>
  <rect x="55" y="55" width="970" height="1240" rx="16" fill="#F8FAFC" stroke="#E2E8F0" stroke-width="2"/>
  <text x="100" y="150" font-size="48" font-weight="bold" fill="#0F172A">System Architecture Overview</text>
  <text x="100" y="240" font-size="24" fill="#334155">Primary Service Pipeline Flow</text>
  <line x1="100" y1="300" x2="800" y2="300" stroke="#2563EB" stroke-width="3" stroke-dasharray="10 10" marker-end="url(#arrow)"/>
  <circle cx="280" cy="300" r="15" fill="#2563EB"/>
  <text x="280" y="300" text-anchor="middle" font-size="15" font-weight="bold" fill="#FFFFFF">1</text>
  <text x="100" y="400" font-size="22" fill="#64748B">Step one processes the incoming event stream.</text>
</svg>"""


def test_extract_svg_valid():
    text = "Here is your diagram:\n" + SAMPLE_VALID_SVG + "\nHope you enjoy it!"
    extracted = extract_svg(text)
    assert extracted.startswith("<svg")
    assert extracted.endswith("</svg>")


def test_extract_svg_clean_nbsp_and_ampersands():
    raw = f'<svg viewBox="0 0 {W} {H}">Text&nbsp;with & unescaped &amp; ampersand<text x="1" y="2" font-size="22">A</text><text x="1" y="3" font-size="22">B</text><text x="1" y="4" font-size="22">C</text></svg>'
    cleaned = extract_svg(raw)
    assert "&nbsp;" not in cleaned
    assert "Text with &amp; unescaped &amp; ampersand" in cleaned


def test_extract_svg_missing_raises_value_error():
    with pytest.raises(ValueError, match="did not return an <svg> drawing"):
        extract_svg("No SVG here at all.")


def test_svg_checks_valid():
    issues = svg_checks(SAMPLE_VALID_SVG)
    assert issues == []


def test_svg_checks_invalid_xml():
    issues = svg_checks("<svg><unclosed></svg>")
    assert any("SVG is not valid XML" in i for i in issues)


def test_svg_checks_non_svg_root():
    issues = svg_checks("<div viewBox='0 0 1080 1350'><text font-size='22'>A</text><text font-size='22'>B</text><text font-size='22'>C</text></div>")
    assert any("start with an <svg> root element" in i for i in issues)


def test_svg_checks_bad_viewbox():
    svg = f'<svg viewBox="0 0 500 500"><text font-size="22">A</text><text font-size="22">B</text><text font-size="22">C</text></svg>'
    issues = svg_checks(svg)
    assert any("must have viewBox" in i for i in issues)


def test_svg_checks_external_links_and_imports():
    svg = f'<svg viewBox="0 0 {W} {H}"><style>@import url("https://fonts.googleapis.com");</style><text font-size="22">A</text><text font-size="22">B</text><text font-size="22">C</text></svg>'
    issues = svg_checks(svg)
    assert any("External links and imports are not allowed" in i for i in issues)

    svg2 = f'<svg viewBox="0 0 {W} {H}"><style>rect {{ background: url("https://example.com/bg.png"); }}</style><text font-size="22">A</text><text font-size="22">B</text><text font-size="22">C</text></svg>'
    issues2 = svg_checks(svg2)
    assert any("External links and imports are not allowed" in i for i in issues2)


def test_svg_checks_forbidden_elements():
    for forbidden in ["script", "foreignObject", "image", "iframe", "animate"]:
        svg = f'<svg viewBox="0 0 {W} {H}"><{forbidden}>alert(1)</{forbidden}><text font-size="22">A</text><text font-size="22">B</text><text font-size="22">C</text></svg>'
        issues = svg_checks(svg)
        assert any(f"Element <{forbidden}> is not allowed" in i for i in issues)


def test_svg_checks_external_href_attr():
    svg = f'<svg viewBox="0 0 {W} {H}"><use href="external.svg#icon"/><text font-size="22">A</text><text font-size="22">B</text><text font-size="22">C</text></svg>'
    issues = svg_checks(svg)
    assert any("External reference not allowed" in i for i in issues)


def test_svg_checks_font_size_rules():
    # Long text with font size 18 (< 22) should fail
    svg = f'<svg viewBox="0 0 {W} {H}"><text font-size="18">Long descriptive paragraph text</text><text font-size="24">Title</text><text font-size="24">Footer</text></svg>'
    issues = svg_checks(svg)
    assert any("Text too small" in i for i in issues)

    # Short badge text (len <= 3) with font size 15 should PASS (min allowed is 14)
    svg_badge = f'<svg viewBox="0 0 {W} {H}"><text font-size="15">1</text><text font-size="24">Title</text><text font-size="24">Footer</text></svg>'
    issues_badge = svg_checks(svg_badge)
    assert issues_badge == []


def test_svg_checks_too_few_texts():
    svg = f'<svg viewBox="0 0 {W} {H}"><text font-size="24">Only One</text></svg>'
    issues = svg_checks(svg)
    assert any("at least 3 labelled text elements" in i for i in issues)


def test_svg_checks_text_too_long():
    long_txt = "X" * 95
    svg = f'<svg viewBox="0 0 {W} {H}"><text font-size="22">{long_txt}</text><text font-size="24">Title</text><text font-size="24">Footer</text></svg>'
    issues = svg_checks(svg)
    assert any("Text line too long" in i for i in issues)


def test_svg_checks_emoji_rejected():
    svg = f'<svg viewBox="0 0 {W} {H}"><text font-size="22">Rocket launch 🚀</text><text font-size="24">Title</text><text font-size="24">Footer</text></svg>'
    issues = svg_checks(svg)
    assert any("Emoji characters are not allowed" in i for i in issues)


def test_svg_checks_max_elements():
    items = "".join(f'<circle cx="{i}" cy="{i}" r="5"/>' for i in range(MAX_ELEMENTS + 10))
    svg = f'<svg viewBox="0 0 {W} {H}">{items}<text font-size="22">A</text><text font-size="22">B</text><text font-size="22">C</text></svg>'
    issues = svg_checks(svg)
    assert any("Drawing is too complex" in i for i in issues)


def test_render_svg_success(tmp_path: Path):
    out_png = tmp_path / "test.png"
    result = render_svg(SAMPLE_VALID_SVG, out_png)
    assert result == out_png
    assert out_png.exists()
    assert out_png.stat().st_size > 0


def test_render_svg_invalid_raises_value_error(tmp_path: Path):
    out_png = tmp_path / "fail.png"
    with pytest.raises(ValueError, match="must have viewBox"):
        render_svg("<svg viewBox='0 0 10 10'></svg>", out_png)


def test_render_svg_cairosvg_failure_raises_value_error(tmp_path: Path, monkeypatch):
    import cairosvg
    def mock_svg2png(*args, **kwargs):
        raise RuntimeError("Cairo backend error")
    monkeypatch.setattr(cairosvg, "svg2png", mock_svg2png)
    out_png = tmp_path / "cairo_fail.png"
    with pytest.raises(ValueError, match="The drawing could not be rendered"):
        render_svg(SAMPLE_VALID_SVG, out_png)


def test_render_svg_to_gif_success_with_all_motion_features(tmp_path: Path):
    out_gif = tmp_path / "test_motion.gif"
    # Include an undashed stroked line (to test line 115 auto-dash),
    # an existing dashed line without stroke-dashoffset (to test line 141),
    # and all placeholders: {flow_offset}, {pulse_r}, {pulse_op} (to test 148, 150, 152)
    svg = f"""<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <filter id="shadow"><feDropShadow dx="0" dy="2" stdDeviation="4"/></filter>
  </defs>
  <line x1="50" y1="50" x2="200" y2="50" stroke="#2563EB" stroke-width="2"/>
  <line x1="200" y1="50" x2="400" y2="50" stroke="#2563EB" stroke-dasharray="10 10" stroke-dashoffset="0" stroke-width="2"/>
  <line x1="400" y1="50" x2="600" y2="50" stroke="#2563EB" stroke-dasharray="10 10" stroke-width="2"/>
  <circle cx="500" cy="500" r="{{pulse_r}}" opacity="{{pulse_op}}" fill="#2563EB"/>
  <text x="100" y="200" font-size="30">Dynamic Offset: {{flow_offset}}</text>
  <text x="100" y="300" font-size="24">Second Text Line</text>
  <text x="100" y="400" font-size="22">Third Text Line For Validation</text>
</svg>"""
    result = render_svg_to_gif(svg, out_gif, n_frames=2, fps=4)
    assert result == out_gif
    assert out_gif.exists()
    assert out_gif.stat().st_size > 0

    with Image.open(out_gif) as img:
        assert img.format == "GIF"
        assert getattr(img, "is_animated", False)
        assert img.n_frames == 2


def test_render_svg_to_gif_invalid_raises_value_error(tmp_path: Path):
    out_gif = tmp_path / "fail.gif"
    with pytest.raises(ValueError):
        render_svg_to_gif("<svg></svg>", out_gif)


# ----------------------------------------------------------------------------- icon library
def test_icon_library_is_complete_and_gif_safe():
    assert len(ICON_NAMES) >= 30
    assert {"check", "x", "warning", "bolt", "database", "code", "bulb", "rocket"} <= set(ICON_NAMES)
    for name, markup in ICONS.items():
        # Every stroked path/line must opt out of the GIF engine's auto-dashing
        for tag in __import__("re").findall(r"<(?:path|line|polyline)\b[^>]*>", markup):
            assert 'stroke-dasharray="none"' in tag, f"icon {name} would animate as dashes"


def test_inject_icon_defs_adds_only_referenced_icons():
    svg = f'<svg viewBox="0 0 {W} {H}"><use href="#icon-bolt"/><use href="#icon-check"/></svg>'
    out = inject_icon_defs(svg)
    assert 'id="icon-bolt"' in out and 'id="icon-check"' in out
    assert 'id="icon-database"' not in out
    assert out.index("<defs>") < out.index("<use")
    # Idempotent: a second pass must not duplicate definitions
    assert inject_icon_defs(out).count('id="icon-bolt"') == 1


def test_inject_icon_defs_leaves_unknown_and_unreferenced_svgs_alone():
    plain = f'<svg viewBox="0 0 {W} {H}"><text>x</text></svg>'
    assert inject_icon_defs(plain) == plain
    unknown = f'<svg viewBox="0 0 {W} {H}"><use href="#icon-nonexistent"/></svg>'
    assert inject_icon_defs(unknown) == unknown
    assert inject_icon_defs("not svg #icon-bolt") == "not svg #icon-bolt"


def test_finalize_svg_rewrites_xlink_lifts_near_miss_fonts_and_injects_icons():
    svg = (f'<svg viewBox="0 0 {W} {H}"><use xlink:href="#icon-bolt"/>'
           '<text font-size="20">near miss</text><text font-size="15">1</text>'
           '<text font-size="30">big</text></svg>')
    out = finalize_svg(svg)
    assert "xlink:href" not in out and 'href="#icon-bolt"' in out
    assert 'font-size="22">near miss' in out   # 20 lifted to the 22 minimum
    assert 'font-size="15">1<' in out          # badge digits keep their small size
    assert 'font-size="30">big' in out
    assert 'id="icon-bolt"' in out


def test_icons_render_through_cairosvg(tmp_path: Path):
    svg = finalize_svg(
        f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg">'
        '<use href="#icon-bolt" transform="translate(40,40) scale(3)" color="#2563EB"/>'
        '<text x="10" y="300" font-size="24">A</text><text x="10" y="340" font-size="24">B</text>'
        '<text x="10" y="380" font-size="24">C</text></svg>')
    assert render_svg(svg, tmp_path / "icons.png").exists()


# ----------------------------------------------------------------------------- helpers
def test_translate_and_float_helpers():
    assert _translate(None) == (0.0, 0.0, True)
    assert _translate("translate(10,20)") == (10.0, 20.0, True)
    assert _translate("translate(10 20) scale(2)") == (10.0, 20.0, False)
    assert _translate("rotate(45)") == (0.0, 0.0, False)
    assert _float("24") == 24.0 and _float("24px") == 24.0
    assert _float("50%") is None and _float(None, 7.0) == 7.0


# ----------------------------------------------------------------------------- design quality
def _rich_svg() -> str:
    """A poster with 20 well-spaced text lines, 6 icons and 10 panels spanning the whole canvas."""
    parts = [f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" font-family="Arial">']
    parts += [f'<rect x="40" y="{100 + i * 120}" width="1000" height="100" rx="16"/>' for i in range(10)]
    parts += [f'<text x="60" y="{150 + i * 60}" font-size="24">Row {i} label text</text>' for i in range(20)]
    parts += [f'<use href="#icon-check" transform="translate({700 + i * 50},300)"/>' for i in range(6)]
    parts.append("</svg>")
    return "".join(parts)


def test_design_quality_checks_accepts_a_rich_poster():
    assert design_quality_checks(_rich_svg()) == []


def test_design_quality_checks_flags_sparse_poster():
    issues = design_quality_checks(SAMPLE_VALID_SVG)
    joined = " ".join(issues)
    assert "Too sparse" in joined
    assert "at least 4 library icons" in joined
    assert "at least 8 rounded panels" in joined
    assert "Large empty area" in joined


def test_design_quality_checks_flags_unknown_icons():
    svg = _rich_svg().replace("#icon-check", "#icon-banana", 1)
    assert any("Unknown icon names: banana" in i for i in design_quality_checks(svg))


def test_design_quality_checks_flags_off_canvas_text():
    svg = _rich_svg().replace("</svg>", '<text x="900" y="400" font-size="30">This line is far too long to fit</text></svg>')
    assert any("runs off the canvas" in i for i in design_quality_checks(svg))


def test_design_quality_checks_flags_overlapping_text():
    svg = _rich_svg().replace("</svg>", '<text x="62" y="152" font-size="24">Row 0 label text</text></svg>')
    assert any("Overlapping text" in i for i in design_quality_checks(svg))


def test_design_quality_checks_handles_anchors_tspans_inherited_fonts_and_transforms():
    svg = (f'<svg viewBox="0 0 {W} {H}" font-size="22" font-family="Menlo">'
           '<g transform="translate(0,200)"><text x="100" y="50" text-anchor="middle" font-weight="bold">Centered heading text</text>'
           '<text x="500" y="50" text-anchor="end">Right aligned</text></g>'
           '<text x="60" y="600"><tspan x="60" y="600">first run</tspan><tspan x="60" y="640">second run</tspan></text>'
           '<text x="60" y="700">plain <tspan fill="red">inline</tspan> colour</text>'
           '<g transform="rotate(10)"><text x="10" y="10">skipped geometry</text></g>'
           '<text y="900">no x so ignored</text><text x="5%" y="900">percent ignored</text></svg>')
    # Must not raise; only structural/sparse issues are reported for this tiny drawing
    issues = design_quality_checks(svg)
    assert any("Too sparse" in i for i in issues)
    # Centered text at x=100 with a long width extends left of the 25px margin
    assert any("runs off the canvas" in i for i in issues)


def test_design_quality_checks_ignores_malformed_xml():
    assert design_quality_checks("<svg><unclosed>") == []

