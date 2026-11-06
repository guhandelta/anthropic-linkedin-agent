"""The lower half and the bottom strip change from poster to poster, and so does the colour family."""
import random
import re

import pytest

from infographic import design_quality_checks, finalize_svg, svg_checks
from layout_check import layout_issues
from poster_layout import (DETAILS, FINISHES, STYLES, THEMES, choose_theme, choose_variant,
                           details_options, poster_from_brief, theme_family)
from tests.test_poster_styles import CHECKS, CODE, SHAPES, STATS, STEPS, _brief, _plan

NO_CODE = (CHECKS, STEPS, STATS)


def _draw(plan, style, details, finish, theme="ocean"):
    return finalize_svg(poster_from_brief(_brief(plan), "Heading", "Guhaprasaanth N", style=style,
                                          theme=theme, details=details, finish=finish))


def _attr(svg, name):
    return re.search(rf'data-{name}="([a-z_]+)"', svg).group(1)


def test_detail_styles_follow_the_modules():
    assert details_options(_plan(modules=(CODE, CHECKS, STEPS))) == ["grid", "rows"]
    assert details_options(_plan(modules=NO_CODE)) == ["grid", "rows", "checklist", "tabs"]
    assert details_options(_plan(modules=NO_CODE + (STEPS,))) == ["grid", "rows", "checklist"]


@pytest.mark.parametrize("finish", FINISHES)
@pytest.mark.parametrize("style", STYLES)
def test_every_layout_takes_every_finish_and_detail_style(style, finish):
    plan = SHAPES[style]
    for details in details_options(plan):
        svg = _draw(plan, style, details, finish)
        assert (_attr(svg, "style"), _attr(svg, "details"), _attr(svg, "finish")) == (
            style, details, finish)
        assert svg_checks(svg) + design_quality_checks(svg) == [], (style, details, finish)


# The rendered pixel check is slow (about 17 s a poster), so it covers each detail style with each
# finish on the layouts that use the full-width details block, in a light and a dark theme.
@pytest.mark.parametrize("style, details, finish, theme", [
    ("guide", "rows", "split", "ember"),
    ("guide", "checklist", "quote", "forest"),
    ("guide", "tabs", "bars", "midnight"),
    ("spotlight", "rows", "quote", "tangerine"),
    ("comparison", "tabs", "split", "midnight"),
    ("incident", "checklist", "split", "volcano"),
    ("stack", "rows", "bars", "lagoon"),
    ("hub", "tabs", "quote", "berry"),
    ("dashboard", "rows", "split", "orchid"),
    ("matrix", "grid", "quote", "cyber"),
])
def test_detail_and_finish_styles_render_cleanly(style, details, finish, theme):
    plan = SHAPES[style]
    if details in ("checklist", "tabs"):
        plan = {**plan, "modules": list(NO_CODE)}
    svg = _draw(plan, style, details, finish, theme)
    assert _attr(svg, "details") == details and _attr(svg, "finish") == finish
    assert layout_issues(svg) == []


def test_variants_never_repeat_the_last_one():
    rng = random.Random(3)
    for last in DETAILS:
        assert all(choose_variant(DETAILS, [last], rng) != last for _ in range(30))
    assert choose_variant(FINISHES) == "bars"  # stable without rng


def test_posters_in_a_row_use_different_detail_and_finish_styles():
    rng, recent_d, recent_f = random.Random(7), [], []
    plan = _plan(modules=NO_CODE)
    for _ in range(6):
        svg = poster_from_brief(_brief(plan), "Heading", "Footer", rng=rng, recent_details=recent_d,
                                recent_finishes=recent_f)
        d, f = _attr(svg, "details"), _attr(svg, "finish")
        assert recent_d[-1:] != [d] and recent_f[-1:] != [f]
        recent_d.append(d)
        recent_f.append(f)
    assert len(set(recent_d)) >= 3 and len(set(recent_f)) == 3


def test_a_detail_style_that_would_cut_text_falls_back_to_the_grid():
    long = {**CHECKS, "heading": "Compatibility " * 8}
    svg = poster_from_brief(_brief(_plan(modules=(long, STEPS, STATS))), "Heading", "Footer",
                            rng=random.Random(1), details="tabs")
    assert _attr(svg, "details") != "tabs" or "…" not in svg


def test_every_theme_has_a_colour_family():
    families = {theme_family(t) for t in THEMES}
    assert len(families) >= 8
    assert theme_family("midnight").startswith("dark-") and theme_family("ocean").startswith("light-")


def test_next_theme_differs_in_colour_family_from_the_last_two():
    rng = random.Random(11)
    for recent in (["steel", "ocean"], ["midnight", "ember"], ["forest", "emerald"]):
        banned = {theme_family(t) for t in recent}
        for _ in range(40):
            pick = choose_theme(_plan(), recent, rng)
            assert pick not in recent and theme_family(pick) not in banned
