"""Whole-poster layouts and colour themes: chosen from the content, never the same as last time,
and every layout x theme pair passes the same checks as any published poster."""
import json
import re

import pytest

from infographic import design_quality_checks, finalize_svg, gif_frame_svgs, svg_checks
from layout_check import layout_issues
from poster_layout import (MARKER, STYLES, THEME_HINTS, THEMES, _apply_theme, choose_style,
                           choose_theme, poster_from_brief)

NODES = [
    {"label": "Find usage", "detail": "Inspect one library's calls", "icon": "search"},
    {"label": "Select API", "detail": "Check support and permissions", "icon": "code"},
    {"label": "Measure", "detail": "Compare bundle size", "icon": "check"},
    {"label": "Ship safely", "detail": "Keep a fallback in place", "icon": "layers"},
    {"label": "Monitor errors", "detail": "Alert on regressions", "icon": "eye"},
]
CODE = {"kind": "code", "heading": "Clipboard API", "icon": "code",
        "lines": ["await navigator.clipboard.writeText(text)"]}
CHECKS = {"kind": "checklist", "heading": "Compatibility", "icon": "check",
          "lines": ["Check browser support", "Check secure context", "Keep a fallback"]}
STEPS = {"kind": "steps", "heading": "Rollout", "icon": "layers",
         "lines": ["Replace one call", "Test in browsers", "Measure bundle size"]}
STATS = {"kind": "stats", "heading": "By the numbers", "icon": "chart",
         "lines": ["40% | smaller bundle", "3x | faster cold start", "v2.1 | release"]}


def _plan(form="flow", n=3, modules=(CODE, CHECKS, STEPS), **extra):
    plan = {"title": "Built-in Web APIs for leaner apps",
            "subtitle": "A practical path through browser capabilities",
            "tagline": "Less dependency code, with a compatibility check",
            "hero": {"form": form, "caption": "Replace one library with a native capability",
                     "left_label": "Old way", "right_label": "New way", "nodes": NODES[:n]},
            "modules": list(modules),
            "gotcha": {"heading": "Watch out", "text": "Browser support and permissions vary."},
            "takeaway": "Try one native API and measure its impact."}
    plan.update(extra)
    return plan


def _brief(plan):
    return MARKER + "\n" + json.dumps(plan)


def _svg(plan, **kw):
    return finalize_svg(poster_from_brief(_brief(plan), "Heading", "Guhaprasaanth N", **kw))


def _style(svg):
    return re.search(r'data-style="([a-z]+)"', svg).group(1)


def _theme(svg):
    return re.search(r'data-theme="([a-z]+)"', svg).group(1)


# A content shape that suits each layout, so every layout is checked with every palette.
SHAPES = {
    "guide": _plan("flow", 3),
    "timeline": _plan("flow", 4, (CODE, CHECKS, STEPS, STATS)),
    "spotlight": _plan("flow", 4, (CODE, CHECKS, STATS)),
    "comparison": _plan("before_after", 4, (CODE, CHECKS, STEPS, STATS)),
}


@pytest.mark.parametrize("theme", sorted(THEMES))
@pytest.mark.parametrize("style", STYLES)
def test_every_layout_in_every_theme_passes_all_checks(style, theme):
    svg = _svg(SHAPES[style], style=style, theme=theme)
    assert _style(svg) == style and _theme(svg) == theme
    assert "@" not in svg  # every colour token was replaced
    assert svg_checks(svg) == []
    assert design_quality_checks(svg) == []
    assert layout_issues(svg) == []


@pytest.mark.parametrize("style, plan", [
    ("timeline", _plan("layers", 5)),                        # five short cards, no tagline card
    ("timeline", _plan("flow", 3, tagline="")),              # room left but nothing to put there
    ("timeline", _plan("flow", 3, (CODE, CHECKS, STEPS, STATS))),
    ("spotlight", _plan("flow", 3, badge="v2.1 release", tagline="")),
    ("comparison", _plan("before_after", 4)),                # three modules: APPLICATION card
    ("guide", _plan("flow", 5)),
])
def test_layout_variants_stay_clean(style, plan):
    svg = _svg(plan, style=style, theme="midnight")
    assert _style(svg) == style
    assert svg_checks(svg) + design_quality_checks(svg) + layout_issues(svg) == []


def test_layouts_are_structurally_different():
    # Same theme, tags only (no coordinates or words): each layout is a different drawing.
    shapes = {style: tuple(re.findall(r"<(\w+)", _svg(SHAPES[style], style=style, theme="ocean")))
              for style in STYLES}
    assert len(set(shapes.values())) == 4


def test_timeline_fills_spare_room_with_the_tagline_and_drops_a_long_caption():
    svg = _svg(_plan("flow", 3), style="timeline", theme="forest")
    assert "Less dependency code" in svg and "THE PATH" in svg
    short = _svg(_plan("flow", 3, hero={**_plan()["hero"], "caption": "Four moves"}),
                 style="timeline", theme="forest")
    assert "FOUR MOVES" in short


def test_spotlight_uses_the_badge_as_its_kicker_and_falls_back_to_the_caption():
    svg = _svg(_plan("flow", 3, badge="v2.1", tagline=""), style="spotlight", theme="sunset")
    assert "V2.1" in svg and "IN FOCUS" not in svg
    assert "Replace one library with a native capability" in svg
    plain = _svg(_plan("flow", 3), style="spotlight", theme="sunset")
    assert "IN FOCUS" in plain


def test_comparison_shows_both_sides_with_their_labels():
    svg = _svg(_plan("before_after", 4), style="comparison", theme="grape")
    assert "Old way" in svg and "New way" in svg and "WHAT CHANGED" in svg
    assert svg.count("data-motion-step=") == 4


# --- Choosing a layout ---

@pytest.mark.parametrize("plan, expected", [
    (_plan("before_after", 4), "comparison"),
    (_plan("flow", 3, (CODE, CHECKS, STATS)), "spotlight"),
    (_plan("layers", 3), "timeline"),
    (_plan("flow", 4), "timeline"),
    (_plan("flow", 3), "spotlight"),
    (_plan("flow", 5, (CODE, CHECKS, STATS)), "timeline"),  # five steps never go in the ribbon
])
def test_layout_follows_the_content(plan, expected):
    assert choose_style(plan) == expected
    assert _style(_svg(plan)) == expected


@pytest.mark.parametrize("plan", [_plan("before_after", 4), _plan("flow", 3), _plan("flow", 5),
                                  _plan("layers", 4), _plan("flow", 3, (CODE, STATS, STEPS))])
def test_layout_never_repeats_the_last_one(plan):
    for last in STYLES:
        assert choose_style(plan, last) != last


def test_a_forced_layout_that_does_not_suit_the_content_is_replaced():
    svg = _svg(_plan("flow", 3), style="comparison", theme="ocean")
    assert _style(svg) == "spotlight"
    assert _style(_svg(_plan("flow", 5), style="spotlight", theme="ocean")) == "timeline"


# --- Choosing a colour theme ---

def test_the_planners_theme_is_used():
    svg = _svg(_plan(theme="Midnight"))
    assert _theme(svg) == "midnight" and THEMES["midnight"]["bg"] in svg


def test_theme_never_repeats_the_last_one():
    for last in THEMES:
        assert choose_theme(_plan(theme=last), last) != last
        assert choose_theme(_plan(), last) != last


def test_unknown_theme_hint_gets_a_stable_pick():
    plan = _plan(theme="neon")
    assert choose_theme(plan) in THEMES
    assert choose_theme(plan) == choose_theme(plan)
    assert _svg(plan, theme="neon").count('data-theme="') == 1


def test_different_posts_get_different_themes():
    titles = ["Native APIs", "Rust 1.80 released", "Postgres 17 vacuum", "React compiler",
              "Kafka tiered storage", "Python 3.13 JIT"]
    assert len({choose_theme(_plan(title=t)) for t in titles}) >= 3


def test_every_theme_defines_the_same_colours_and_has_a_hint():
    keys = set(THEMES["ocean"])
    assert all(set(palette) == keys for palette in THEMES.values())
    assert set(THEME_HINTS) == set(THEMES)
    assert all(re.fullmatch(r"#[0-9A-F]{6}", v) for p in THEMES.values() for v in p.values())


def _contrast(a, b):
    def lum(h):
        c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
    hi, lo = sorted([lum(a), lum(b)], reverse=True)
    return (hi + 0.05) / (lo + 0.05)


@pytest.mark.parametrize("theme", sorted(THEMES))
def test_text_colours_are_readable_in_every_theme(theme):
    t = THEMES[theme]
    body = [("ink", "card"), ("muted", "card"), ("muted", "node"), ("muted", "bg"), ("ink", "soft"),
            ("muted", "soft"), ("ink", "soft2"), ("on_strong", "strong"), ("code_ink", "code_bg"),
            ("code_muted", "code_bg"), ("warn_text", "warn_bg"), ("warn_head", "warn_bg"),
            ("soft_ink", "soft"), ("footer", "bg")]
    bold = [("primary", "card"), ("primary", "soft"), ("good", "good_soft"), ("bad", "bad_soft")]
    bold += [(f"a{i}", bg) for i in range(1, 6) for bg in ("card", "node")]
    assert [p for p in body if _contrast(t[p[0]], t[p[1]]) < 4.5] == []
    assert [p for p in bold if _contrast(t[p[0]], t[p[1]]) < 3] == []


def test_apply_theme_rejects_unknown_tokens():
    with pytest.raises(KeyError):
        _apply_theme('<rect fill="@nope@"/>', "ocean")


def test_gif_highlight_uses_the_theme_colour():
    svg = _svg(_plan(), style="guide", theme="sunset")
    frames = gif_frame_svgs(svg, 4)
    assert f'stroke="{THEMES["sunset"]["primary"]}" stroke-width="7"' in frames[0]
    assert 'stroke="#3768B7" stroke-width="7"' not in frames[0]


def test_gif_frames_refuse_an_invalid_drawing():
    with pytest.raises(ValueError):
        gif_frame_svgs("<svg", 2)
