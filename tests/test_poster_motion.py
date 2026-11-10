"""Layout-tied motions and header styles: each layout moves its own way, layouts open differently,
and every new look passes the same rendered checks as any published poster."""
import random
import re

import pytest
from PIL import Image

from infographic import (MOTION_FRAMES, MOTIONS, design_quality_checks, gif_frame_svgs,
                         render_svg_to_gif, svg_checks)
from layout_check import gif_issues, layout_issues
from poster_layout import (CORNERS, HEADER_DEFAULTS, HEADERS, MOTION_SETS, STYLES, choose_motion)
from tests.test_poster_styles import SHAPES, _svg


def _attr(svg, name):
    return re.search(rf'data-{name}="([a-z_]+)"', svg).group(1)


# ------------------------------------------------------------------ motions follow the layout

def test_every_layout_has_motions_and_every_motion_exists():
    assert set(MOTION_SETS) == set(STYLES)
    for style, motions in MOTION_SETS.items():
        assert len(motions) >= 2 and set(motions) <= set(MOTIONS), style


@pytest.mark.parametrize("style, signature", [("timeline", "draw"), ("comparison", "slide"),
                                              ("dashboard", "count"), ("hub", "ripple"),
                                              ("matrix", "sweep")])
def test_a_layout_starts_with_its_signature_motion(style, signature):
    assert _attr(_svg(SHAPES[style], style=style), "motion") == signature
    assert choose_motion({}, None, style=style) == signature


def test_motion_never_repeats_the_last_two_and_stays_in_the_layouts_set():
    rng = random.Random(3)
    for style, options in MOTION_SETS.items():
        for recent in ([], [options[0]], [options[1], options[0]]):
            for _ in range(10):
                pick = choose_motion({}, recent, rng, style)
                assert pick in options and pick not in recent[-2:]


def test_a_forced_motion_is_used():
    assert _attr(_svg(SHAPES["guide"], style="guide", motion="sweep"), "motion") == "sweep"


# ------------------------------------------------------------------ what each motion does

def test_draw_reveals_connectors_one_after_another_and_holds():
    svg = _svg(SHAPES["timeline"], style="timeline", motion="draw")
    frames = gif_frame_svgs(svg)
    assert len(frames) == MOTION_FRAMES["draw"]
    first, last = frames[0], frames[-1]
    assert re.search(r'stroke-dasharray="0\.0 [\d.]+"', first)  # nothing drawn yet
    assert not re.search(r'stroke-dasharray="0\.0 [\d.]+"', last)  # everything drawn
    lit = [len(re.findall(r'data-motion-step="\d+"[^>]*stroke-width="7"', f)) for f in frames]
    assert lit == sorted(lit) and lit[0] == 0 and lit[-1] == 4  # steps light as they are reached


def test_count_counts_numbers_up_and_grows_bars():
    svg = _svg(SHAPES["dashboard"], style="dashboard", motion="count")
    assert svg.count('data-motion-count="1"') >= 2
    frames = gif_frame_svgs(svg)
    values = lambda f: re.findall(r'data-motion-count="1"[^>]*>([^<]*)<', f)  # noqa: E731
    assert values(frames[0])[0].startswith("0") and values(frames[-1]) == values(svg)
    assert ">v2.1<" in frames[0]  # a version is not a number to count


def test_count_keeps_decimals_separators_and_units():
    from infographic import _count_text

    pattern = re.compile(r"(<t>)([^<]*)(</t>)")
    assert _count_text(pattern.search("<t>~$1,250.50 ms</t>"), 0.5) == "<t>~$625.25 ms</t>"
    assert _count_text(pattern.search("<t>3x</t>"), 1.0) == "<t>3x</t>"
    assert _count_text(pattern.search("<t>none</t>"), 0.5) == "<t>none</t>"


def test_slide_moves_the_halves_apart_then_together():
    svg = _svg(SHAPES["comparison"], style="comparison", motion="slide")
    assert svg.count('data-motion-part="left"') == 1 and svg.count('data-motion-part="right"') == 1
    frames = gif_frame_svgs(svg)
    assert 'translate(-40.0,0)' in frames[0] and 'translate(40.0,0)' in frames[0]
    assert 'translate(0.0,0)' in frames[len(frames) // 2]


def test_ripple_spreads_rings_from_the_hub_behind_the_content():
    svg = _svg(SHAPES["hub"], style="hub", motion="ripple")
    assert 'data-origin="540,458"' in svg
    frame = gif_frame_svgs(svg)[3]
    background = re.search(r'<rect x="0" y="0" width="1080" height="1350"[^>]*/>', frame)
    rings = frame[background.end():].split("<circle", 4)[1:4]
    assert all('cx="540" cy="458"' in ring for ring in rings)


def test_sweep_tints_the_cards_it_passes():
    svg = _svg(SHAPES["matrix"], style="matrix", motion="sweep")
    soft = re.search(r'data-soft="(#[0-9A-Fa-f]{6})"', svg).group(1)
    tinted = [len(re.findall(rf'data-motion-step="\d+"[^>]*fill="{soft}"', f))
              for f in gif_frame_svgs(svg)]
    assert max(tinted) >= 2 and min(tinted) == 0


def test_reveal_gifs_hold_the_finished_poster(tmp_path):
    svg = _svg(SHAPES["dashboard"], style="dashboard", motion="count")
    gif = render_svg_to_gif(svg, tmp_path / "count.gif", n_frames=4)
    with Image.open(gif) as image:
        durations = []
        for k in range(image.n_frames):
            image.seek(k)
            durations.append(image.info["duration"])
    assert durations[-1] > 1000 > durations[0]


@pytest.mark.parametrize("style, motion", [("timeline", "draw"), ("comparison", "slide"),
                                           ("dashboard", "count"), ("hub", "ripple"),
                                           ("matrix", "sweep")])
def test_new_motions_stay_clean_in_the_gif(style, motion):
    svg = _svg(SHAPES[style], style=style, theme="midnight", motion=motion)
    assert gif_issues(svg, gif_frame_svgs(svg)) == []


# ------------------------------------------------------------------ headers and corners

def test_every_layout_has_a_default_header_and_they_differ():
    assert set(HEADER_DEFAULTS) <= set(STYLES)
    assert set(HEADER_DEFAULTS.values()) == set(HEADERS)


@pytest.mark.parametrize("header", HEADERS)
@pytest.mark.parametrize("style", ["playbook", "comparison", "versus"])  # band, panel, centre
def test_header_styles_stay_clean(style, header):
    corners = CORNERS[HEADERS.index(header)]
    svg = _svg(SHAPES[style], style=style, theme="sunset", header=header, corners=corners)
    assert _attr(svg, "header") == header and _attr(svg, "corners") == corners
    assert svg_checks(svg) + design_quality_checks(svg) + layout_issues(svg) == []


def test_header_styles_draw_differently():
    drawings = {h: _svg(SHAPES["guide"], style="guide", theme="ocean", header=h) for h in HEADERS}
    head = {h: s.split("TECHNICAL FIELD GUIDE")[0] for h, s in drawings.items()}
    assert len(set(head.values())) == 3


def test_corner_styles_change_card_corners_only():
    shapes = {c: _svg(SHAPES["guide"], style="guide", corners=c) for c in CORNERS}
    radii = {c: set(re.findall(r'rx="(\d+)"', s)) for c, s in shapes.items()}
    assert "4" in radii["square"] and "26" in radii["soft"] and "18" in radii["round"]
    assert 'rx="3"' in shapes["square"]  # thin accent strips keep their shape
