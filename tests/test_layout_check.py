"""Rendered layout check: overlapping, hidden, clipped and spilling items in the PNG and GIF."""
from pathlib import Path
from unittest.mock import MagicMock

import agent
from infographic import finalize_svg, gif_frame_svgs
from layout_check import gif_dash_issues, gif_issues, layout_issues

HEAD = ('<svg viewBox="0 0 1080 1350" xmlns="http://www.w3.org/2000/svg" '
        'font-family="Helvetica, Arial, DejaVu Sans, sans-serif">'
        '<defs><marker id="arrow" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="6" markerHeight="6">'
        '<path d="M 0 1.5 L 8 5 L 0 8.5 z" fill="#2563EB"/></marker></defs>'
        '<rect x="0" y="0" width="1080" height="1350" fill="#FFFFFF"/>')


def poster(body: str) -> str:
    return finalize_svg(HEAD + body + "</svg>")


CLEAN = poster(
    '<rect x="60" y="60" width="960" height="200" rx="20" fill="#F2F5FA"/>'
    '<use href="#icon-bolt" transform="translate(80,90) scale(2)" color="#2563EB"/>'
    '<text x="140" y="125" font-size="40" font-weight="bold" fill="#111827">A clean heading</text>'
    '<text x="80" y="200" font-size="24" fill="#4B5563">A short line inside its card</text>'
    '<circle cx="980" cy="110" r="16" fill="#2563EB"/>'
    '<text x="980" y="110" text-anchor="middle" dominant-baseline="central" font-size="18" fill="#FFF">1</text>'
    '<line x1="100" y1="400" x2="900" y2="400" stroke="#2563EB" stroke-width="3" '
    'stroke-dasharray="10 10" marker-end="url(#arrow)"/>'
    '<text x="100" y="460" font-size="24" fill="#111827">Label well below the arrow</text>'
    '<line x1="60" y1="1270" x2="1020" y2="1270" stroke="#CBD5E1" stroke-dasharray="none"/>'
    '<text x="60" y="1302" font-size="22" fill="#64748B">Footer text</text>')


def kinds(issues):
    return " | ".join(issues)


def test_clean_poster_has_no_layout_issues():
    assert layout_issues(CLEAN) == []
    assert gif_issues(CLEAN, gif_frame_svgs(CLEAN)) == []


def test_text_covered_by_a_later_card_is_hidden():
    svg = poster('<text x="60" y="110" font-size="40" fill="#111">Covered heading</text>'
                 '<rect x="40" y="60" width="700" height="80" fill="#EFF6FF"/>')
    assert "Hidden" in kinds(layout_issues(svg)) and "Covered heading" in kinds(layout_issues(svg))


def test_text_same_colour_as_background_is_hidden():
    assert "Hidden" in kinds(layout_issues(poster(
        '<text x="60" y="220" font-size="28" fill="#FFFFFF">White on white</text>')))


def test_text_overlapping_text_icon_and_line():
    issues = kinds(layout_issues(poster(
        '<text x="60" y="300" font-size="30" fill="#111">First label here</text>'
        '<text x="200" y="310" font-size="30" fill="#111">Second label collides</text>'
        '<use href="#icon-bolt" transform="translate(70,540) scale(2.5)" color="#2563EB"/>'
        '<text x="80" y="570" font-size="26" fill="#111">Icon sits on me</text>'
        '<line x1="60" y1="790" x2="900" y2="790" stroke="#2563EB" stroke-width="3"/>'
        '<text x="300" y="800" font-size="28" fill="#111">Arrow runs through me</text>')))
    assert "Text overlaps text" in issues
    assert "Icon overlaps text" in issues
    assert "Line or arrow crosses text" in issues


def test_text_spilling_out_of_card_and_off_canvas():
    issues = kinds(layout_issues(poster(
        '<rect x="60" y="360" width="300" height="120" rx="16" fill="#F2F5FA"/>'
        '<text x="80" y="430" font-size="26" fill="#111">This line is far too long for its card</text>'
        '<text x="900" y="700" font-size="30" fill="#111">Falls off canvas</text>')))
    assert "spills out of its card" in issues
    assert "Cut off at the canvas edge" in issues


def test_gif_no_longer_dashes_filled_shapes_but_flags_plain_dividers():
    svg = poster('<path d="M60 900 H1020 V1000 H60 Z" fill="#FEF3C7" stroke="#F59E0B"/>'
                 '<line x1="60" y1="1100" x2="1020" y2="1100" stroke="#CBD5E1"/>'
                 '<text x="80" y="960" font-size="26" fill="#92400E">Callout</text>')
    frame = gif_frame_svgs(svg)[0]
    assert 'stroke="#F59E0B" stroke-dasharray' not in frame  # the callout outline stays solid
    issues = gif_dash_issues(svg, frame)
    assert issues and "<line> without arrowhead" in issues[0]


def test_render_poster_files_falls_back_to_png_when_gif_fails_layout(tmp_path, monkeypatch):
    monkeypatch.setattr(agent, "gif_issues", MagicMock(return_value=["GIF: Hidden: 'x'"]))
    gif = MagicMock()
    monkeypatch.setattr(agent, "render_svg_to_gif", gif)
    out = agent.render_poster_files(CLEAN, tmp_path / "p.png")
    assert out == tmp_path / "p.png" and Path(out).exists()
    gif.assert_not_called()


def test_draw_poster_redraws_until_layout_is_clean(tmp_path, monkeypatch):
    bad = poster('<text x="60" y="220" font-size="28" fill="#FFFFFF">White on white</text>')
    designer = MagicMock(side_effect=[bad, CLEAN])
    monkeypatch.setattr(agent, "design_svg", designer)
    monkeypatch.setattr(agent, "design_quality_checks", MagicMock(return_value=[]))
    monkeypatch.setattr(agent, "svg_checks", MagicMock(return_value=[]))
    media, feedback = agent.draw_poster("post", "brief", "Head", "foot", tmp_path / "p.png")
    assert media is not None and designer.call_count == 2
    assert "Hidden" in designer.call_args.args[3]  # the second call got the layout feedback


def test_diagonal_strike_through_a_small_badge_is_not_flagged():
    # A crossed-out XSS badge: a small rounded card with a diagonal line across its label.
    svg = poster('<rect x="400" y="300" width="160" height="80" rx="10" fill="#FEE2E2" stroke="#DC2626"/>'
                 '<text x="420" y="350" font-size="30" font-weight="bold" fill="#DC2626">XSS</text>'
                 '<line x1="385" y1="395" x2="575" y2="290" stroke="#111827" stroke-width="8"/>')
    assert not any("crosses text" in i for i in layout_issues(svg))


def test_diagonal_line_through_plain_text_is_still_flagged():
    svg = poster('<text x="100" y="600" font-size="40" fill="#111">A long label on the page</text>'
                 '<line x1="60" y1="520" x2="900" y2="680" stroke="#111" stroke-width="6"/>')
    assert any("crosses text" in i for i in layout_issues(svg))
