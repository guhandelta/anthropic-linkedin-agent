import io
from pathlib import Path
import pytest
from PIL import Image

from infographic import (
    extract_svg,
    svg_checks,
    render_svg,
    render_svg_to_gif,
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

