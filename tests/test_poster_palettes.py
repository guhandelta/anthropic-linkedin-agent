"""Themes built from brand palettes: readable everywhere, and every one draws clean posters."""
import re

import pytest

from infographic import design_quality_checks, svg_checks
from layout_check import layout_issues
from poster_layout import STYLES, THEME_HINTS, THEMES
from poster_palettes import EXTRA_THEMES, PALETTES, build_theme, contrast, fit, luminance
from tests.test_poster_styles import SHAPES, _style, _svg, _theme

NAMES = sorted(EXTRA_THEMES)


def test_every_palette_is_a_theme_with_a_hint():
    assert len(PALETTES) == 29 and set(NAMES) <= set(THEMES) and set(NAMES) <= set(THEME_HINTS)
    assert len(THEMES) == 35
    assert all(re.fullmatch(r"[a-z]+", name) for name in NAMES)


def test_palettes_are_all_different():
    assert len({tuple(sorted(colours)) for colours, _, _ in PALETTES.values()}) == len(PALETTES)
    assert len({(t["primary"], t["bg"]) for t in EXTRA_THEMES.values()}) == len(EXTRA_THEMES)


@pytest.mark.parametrize("name", NAMES)
def test_a_palettes_brand_colour_shows_on_its_posters(name):
    colours, mode, _ = PALETTES[name]
    theme = THEMES[name]
    # Dark palettes get a dark page, light ones a light page.
    assert (luminance(theme["bg"]) < 0.1) == (mode == "dark")
    # At least one of the palette's own colours survives (nearly) unchanged on the poster.
    accents = [theme[f"a{i}"] for i in range(1, 6)] + [theme["strong"], theme["primary"]]
    assert any(sum(abs(int(a[i:i + 2], 16) - int(c[i:i + 2], 16)) for i in (1, 3, 5)) < 90
               for a in accents for c in colours)


def test_fit_gives_up_at_black_or_white():
    assert fit("#777777", ["#777777"], 30, "#000000") == "#000000"
    assert contrast(fit("#FFFF00", ["#FFFFFF"], 4.5, "#000000"), "#FFFFFF") >= 4.5


def test_a_palette_with_too_few_colours_borrows_spare_accents():
    theme = build_theme(("#123456", "#F8F8F8"), "light")
    assert len({theme[f"a{i}"] for i in range(1, 6)}) == 5


@pytest.mark.parametrize("i, name", list(enumerate(NAMES)))
def test_every_palette_draws_clean_posters(i, name):
    for style in (STYLES[i % len(STYLES)], STYLES[(i + 13) % len(STYLES)]):
        svg = _svg(SHAPES[style], style=style, theme=name)
        assert _style(svg) == style and _theme(svg) == name and "@" not in svg
        assert svg_checks(svg) + design_quality_checks(svg) + layout_issues(svg) == [], style
