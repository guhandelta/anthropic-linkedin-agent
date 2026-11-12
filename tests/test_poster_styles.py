"""Whole-poster layouts and colour themes: chosen from the content, never the same as last time,
and every layout x theme pair passes the same checks as any published poster."""
import json
import re

import pytest

from infographic import design_quality_checks, finalize_svg, gif_frame_svgs, svg_checks
from layout_check import layout_issues
from poster_layout import (LAYOUT_HINTS, MARKER, POST_TYPES, STYLES, THEME_HINTS, THEMES,
                           _apply_theme, _cards, _hub_label, _layers, _stages, _style_candidates,
                           _table, choose_style, choose_theme,
                           poster_from_brief)

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
    return re.search(r'data-style="([a-z_]+)"', svg).group(1)


def _theme(svg):
    return re.search(r'data-theme="([a-z]+)"', svg).group(1)


# Content the planner adds for the matrix, versus, architecture and progression layouts.
CARDS = [
 {"title": "Tool definition bloat", "text": "Too many vague tools confuse routing and raise error rates.", "fix": "Expose fewer, sharper tools.", "icon": "gear"},
 {"title": "Context window decay", "text": "Key instructions get buried as the context grows.", "fix": "Re-anchor rules and compress.", "icon": "clock"},
 {"title": "Retrieval poisoning", "text": "Low-quality chunks silently distort answers.", "fix": "Filter and rank chunks first.", "icon": "database"},
 {"title": "Runaway loops", "text": "Agents get stuck in retries or repeated tool calls.", "fix": "Set step and budget limits.", "icon": "loop"},
 {"title": "Silent schema drift", "text": "Small schema changes break consumers quietly.", "fix": "Validate every boundary.", "icon": "code"},
 {"title": "Eval blindness", "text": "Toy tests pass while real traffic fails.", "fix": "Evaluate on real traffic slices.", "icon": "eye"},
 {"title": "Hidden randomness", "text": "The same prompt gives different outputs.", "fix": "Trace why outputs diverge.", "icon": "search"},
 {"title": "Cost blind spots", "text": "Costs pile up across tokens and tools.", "fix": "Measure cost per task.", "icon": "chart"},
 {"title": "No failure mode", "text": "Without a fallback, agents fabricate answers.", "fix": "Add refusal and escalation.", "icon": "shield"},
]
TABLE = {"left": "LangChain", "right": "LangGraph",
 "left_about": "Chains prompts, models, tools and retrievers into LLM apps.",
 "right_about": "Builds stateful, multi-step workflows as a graph of nodes.",
 "rows": [{"aspect": "Purpose", "left": "Quick LLM apps from chains", "right": "Complex, stateful workflows"},
          {"aspect": "Workflow", "left": "Linear, modular chains", "right": "Graphs with branches, loops and retries"},
          {"aspect": "State", "left": "Mostly stateless", "right": "Built-in state across steps"},
          {"aspect": "Best for", "left": "Simple single-flow apps", "right": "Agentic, production systems"}],
 "left_when": ["You build a simple RAG or chatbot", "The flow is mostly linear", "You want a quick setup"],
 "right_when": ["You need multi-step agent flows", "You need state or human review", "You want a robust system"]}
LAYERS = [{"name": "Builder layer", "items": [{"label": "Claude Code", "detail": "Scaffold, code, deploy", "icon": "terminal"}]},
 {"name": "User layer", "items": [{"label": "Next.js frontend", "detail": "Hosted on Vercel", "icon": "globe"}, {"label": "FastAPI backend", "detail": "Hosted on Render", "icon": "bolt"}]},
 {"name": "Intelligence layer", "items": [{"label": "LLM inference", "detail": "Llama 3 70B", "icon": "cpu"}, {"label": "Orchestrator", "detail": "LangGraph", "icon": "network"}, {"label": "Embeddings", "detail": "Cohere v3", "icon": "layers"}]},
 {"name": "Data layer", "items": [{"label": "Vector DB", "detail": "Qdrant Cloud, 1 GB free", "icon": "database"}]}]
STAGES = [{"label": "AI and ML", "detail": "Turn data into decisions", "icon": "chart"},
 {"label": "Deep learning", "detail": "Neural networks for complex tasks", "icon": "cpu"},
 {"label": "Gen AI", "detail": "Generate content and code", "icon": "sparkle"},
 {"label": "AI agents", "detail": "Run tasks with tools", "icon": "bolt"},
 {"label": "Agentic AI", "detail": "Run whole workflows end to end", "icon": "network"}]

PROFILES = [
 {"name": "Transformer", "icon": "network", "about": "Understands context with attention; powers modern LLMs.",
  "a_label": "Used in", "a_items": ["Chat assistants", "Code assistants", "Translation"],
  "b_label": "Key ideas", "b_items": ["Attention", "Tokens", "Embeddings"]},
 {"name": "Mixture of Experts", "icon": "layers", "about": "Routes each token to a few expert networks.",
  "a_label": "Used in", "a_items": ["Large LLMs", "Efficient inference"],
  "b_label": "Key ideas", "b_items": ["Router", "Sparse activation", "Experts"]},
 {"name": "Diffusion", "icon": "sparkle", "about": "Generates images by removing noise step by step.",
  "a_label": "Used in", "a_items": ["Image generation", "Video generation"],
  "b_label": "Key ideas", "b_items": ["Noise", "Denoising", "Latent space"]},
 {"name": "CNN", "icon": "eye", "about": "Learns visual patterns with filters and feature maps.",
  "a_label": "Used in", "a_items": ["Object detection", "Medical imaging"],
  "b_label": "Key ideas", "b_items": ["Filters", "Pooling", "Convolution"]},
 {"name": "RNN", "icon": "loop", "about": "Processes sequences step by step with memory.",
  "a_label": "Used in", "a_items": ["Speech", "Time series"],
  "b_label": "Key ideas", "b_items": ["Hidden states", "LSTM", "GRU"]},
 {"name": "Graph Neural Net", "icon": "database", "about": "Learns from connected data and relationships.",
  "a_label": "Used in", "a_items": ["Fraud detection", "Recommendations"],
  "b_label": "Key ideas", "b_items": ["Nodes", "Edges", "Message passing"]},
]
SCORECARD = {"left": "Glean", "right": "Cowork", "left_value": "$0.58", "right_value": "$2.98",
             "left_caption": "per task", "right_caption": "per task", "ratio": "5.2x",
             "ratio_caption": "lower cost"}
DECISION = {"question": "Enough evidence?", "yes": "Cited final answer",
            "no": "Refine the query and retrieve again"}
PROS = ["Real HTML inside canvas apps", "Better accessibility", "Less custom UI code",
        "Easier 3D panels and editors"]
CONS = ["Still experimental", "Limited browser support", "Can hurt performance if overused"]

# A content shape that suits each layout, so every layout is checked with every palette.
DIAGRAM = {"nodes": [{"id": n, "label": label, "detail": "A short detail", "icon": icon}
                     for n, label, icon in [("hook", "Webhook", "globe"), ("agent", "AI agent", "cpu"),
                                            ("memory", "Memory", "database"), ("model", "LLM", "sparkle"),
                                            ("tools", "Tools", "gear"), ("gate", "Approval", "shield")]],
           "edges": [{"from": a, "to": b} for a, b in [("hook", "agent"), ("agent", "memory"),
                                                       ("agent", "model"), ("agent", "tools"),
                                                       ("model", "gate"), ("tools", "gate")]]}
SHAPES = {
    "guide": _plan("flow", 3),
    "timeline": _plan("flow", 4, (CODE, CHECKS, STEPS, STATS)),
    "spotlight": _plan("flow", 4, (CODE, CHECKS, STATS)),
    "comparison": _plan("before_after", 4, (CODE, CHECKS, STEPS, STATS)),
    "dashboard": _plan("flow", 4, (CODE, CHECKS, STATS)),
    "code_focus": _plan("flow", 4, (CODE, CHECKS, STEPS)),
    "incident": _plan("flow", 5, (CODE, CHECKS, STEPS), post_type="bug_fix"),
    "stack": _plan("layers", 5, (CODE, CHECKS, STEPS, STATS)),
    "sidebar": _plan("flow", 4, (CODE, CHECKS, STEPS), title="Native APIs for leaner apps"),
    "matrix": _plan("flow", 3, cards=CARDS, title="9 silent killers of AI agents"),
    "versus": _plan("flow", 3, table=TABLE, title="LangChain vs LangGraph"),
    "architecture": _plan("flow", 3, layers=LAYERS, title="The free AI stack"),
    "progression": _plan("flow", 3, stages=STAGES, title="From models to autonomy"),
    "hub": _plan("flow", 5, (CODE, CHECKS, STEPS), title="Agentic RAG"),
    "profiles": _plan("flow", 3, profiles=PROFILES, title="Top 6 AI model architectures"),
    "columns": _plan("flow", 3, profiles=PROFILES[:4], title="Four model families"),
    "zigzag": _plan("flow", 3, cards=CARDS[:5], title="5 deadly sins of AI agents"),
    "playbook": _plan("flow", 3, cards=CARDS[:5], title="Ship an agent in five moves"),
    "scorecard": _plan("flow", 4, (CODE, CHECKS, STATS), scorecard=SCORECARD, title="Glean vs Cowork"),
    "swimlanes": _plan("flow", 3, layers=LAYERS, title="The free AI stack"),
    "twin": _plan("flow", 4, table=TABLE, title="LangChain vs LangGraph"),
    "flowchart": _plan("flow", 5, decision=DECISION, title="Agentic RAG loop"),
    "pipeline": _plan("flow", 3, stages=STAGES, title="How LLMs generate text"),
    "snake": _plan("flow", 3, cards=[{**c, "text": c["fix"]} for c in CARDS[:8]],
                   title="How to build an AI agent"),
    "proscons": _plan("flow", 4, pros=PROS, cons=CONS, title="HTML in canvas"),
    "masonry": _plan("flow", 3, cards=CARDS[:5], title="Your first content agent"),
    "diagram": _plan("flow", 3, graph=DIAGRAM, title="How an agent handles one message"),
}


# The six hand-tuned themes are checked with every layout; the palettes built from brand colours
# are checked in test_poster_palettes.py (two layouts each, so the suite stays under an hour).
CORE_THEMES = ("ember", "forest", "grape", "midnight", "ocean", "sunset")


@pytest.mark.parametrize("theme", CORE_THEMES)
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
    ("dashboard", _plan("flow", 3, (CODE, CHECKS, STEPS, STATS))),  # three details: 2x2 grid
    ("dashboard", _plan("flow", 4, (CHECKS, {**STATS, "lines": STATS["lines"] + ["9 | regions"]},
                                    STEPS), tagline="")),         # four tiles, caption as lead
    ("code_focus", _plan("flow", 4, ({**CODE, "lines": [
        "const res = await fetch(url, { method: 'POST' })", "if (!res.ok) throw new Error(res.status)",
        "const data = await res.json()", "cache.set(url, data)"]}, CHECKS, STEPS))),  # long snippet
    ("code_focus", _plan("flow", 3, ({**CODE, "heading": ""}, CHECKS, STEPS))),
    ("incident", _plan("flow", 3, post_type="bug_fix")),
    ("stack", _plan("flow", 3, post_type="architecture")),
    ("sidebar", _plan("flow", 3, title="Native APIs", tagline="", badge="Explainer")),
    ("sidebar", _plan("flow", 5, title="Native APIs")),
    ("matrix", _plan("flow", 3, cards=CARDS[:7])),                                 # six cards
    ("matrix", _plan("flow", 3, cards=[{**c, "fix": ""} for c in CARDS])),         # no fixes
    ("versus", _plan("flow", 3, table={**TABLE, "rows": TABLE["rows"] * 2,         # five rows
                                       "left_when": "not a list"})),
    ("architecture", _plan("flow", 3, layers=LAYERS[:2])),
    ("progression", _plan("flow", 3, stages=STAGES[:3])),
    ("hub", _plan("flow", 3, hero={**_plan()["hero"], "hub": "Core loop"})),
])
def test_layout_variants_stay_clean(style, plan):
    svg = _svg(plan, style=style, theme="midnight")
    assert _style(svg) == style
    assert svg_checks(svg) + design_quality_checks(svg) + layout_issues(svg) == []


def test_layouts_are_structurally_different():
    # Same theme, tags only (no coordinates or words): each layout is a different drawing.
    shapes = {style: tuple(re.findall(r"<(\w+)", _svg(SHAPES[style], style=style, theme="ocean")))
              for style in STYLES}
    assert len(set(shapes.values())) == len(STYLES) == 27


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
    (_plan("flow", 3, (CHECKS, STEPS, STATS)), "dashboard"),
    (_plan("flow", 3, (CODE, CHECKS, STEPS)), "code_focus"),
    (_plan("flow", 4, (CODE, CHECKS, STEPS), post_type="bug_fix"), "incident"),
    (_plan("layers", 4, (CHECKS, STEPS, CHECKS)), "stack"),
    (_plan("flow", 4, (CHECKS, STEPS, CHECKS), post_type="how_to"), "timeline"),
    (_plan("flow", 3, (CHECKS, STEPS, CHECKS), title="Native APIs"), "sidebar"),
    (_plan("flow", 3, (CHECKS, STEPS, CHECKS), post_type="release"), "spotlight"),
    (_plan("flow", 5, (CODE, CHECKS, STATS)), "timeline"),  # five steps never go in a ribbon
    (_plan("flow", 3, (CHECKS, STEPS, CHECKS), layout="stack"), "stack"),  # the planner's pick
    (_plan("flow", 3, (CHECKS, STEPS, CHECKS), layout="dashboard"), "sidebar"),  # no stats
])
def test_layout_follows_the_content(plan, expected):
    assert choose_style(plan) == expected
    assert _style(_svg(plan)) == expected


@pytest.mark.parametrize("plan", [_plan("before_after", 4), _plan("flow", 3), _plan("flow", 5),
                                  _plan("layers", 4), _plan("flow", 3, (CODE, STATS, STEPS)),
                                  _plan("flow", 4, post_type="bug_fix")])
def test_layout_never_repeats_the_last_one(plan):
    for last in STYLES:
        assert choose_style(plan, last) != last


def test_layout_avoids_the_last_three_when_it_can():
    plan = _plan("flow", 3, (CODE, CHECKS, STATS))
    first = choose_style(plan)
    second = choose_style(plan, [first])
    third = choose_style(plan, [first, second])
    assert len({first, second, third}) == 3
    # Only three layouts fit five steps with stats; once all were used, only the last is avoided.
    five = _plan("flow", 5, (CHECKS, STEPS, STATS))
    assert choose_style(five, ["stack", "guide", "timeline"]) == "guide"


def test_a_forced_layout_that_does_not_suit_the_content_is_replaced():
    svg = _svg(_plan("flow", 3), style="comparison", theme="ocean")
    assert _style(svg) == "code_focus"
    assert _style(_svg(_plan("flow", 5), style="spotlight", theme="ocean")) == "timeline"


def test_code_focus_skips_a_row_too_narrow_for_stats():
    plan = _plan("flow", 3, (CODE, CHECKS, STEPS, STATS))
    assert choose_style(plan) == "dashboard"
    assert "code_focus" not in _style_candidates(plan)


def test_long_titles_skip_the_sidebar():
    plan = _plan("flow", 3, (CHECKS, STEPS, CHECKS), title="Internationalization done right")
    assert "sidebar" not in _style_candidates(plan)
    many = _plan("flow", 3, (CHECKS, STEPS, CHECKS), title="Alpha bravo delta gamma omega sigma kappa theta zeta lambda")
    assert "sidebar" not in _style_candidates(many)


def test_every_layout_has_a_hint_for_the_planner():
    assert set(LAYOUT_HINTS) == set(STYLES)
    assert "bug_fix" in POST_TYPES


# --- Choosing a colour theme ---

def test_the_planners_theme_is_used():
    svg = _svg(_plan(theme="Midnight"))
    assert _theme(svg) == "midnight" and THEMES["midnight"]["bg"] in svg


def test_theme_never_repeats_the_last_one():
    for last in THEMES:
        assert choose_theme(_plan(theme=last), last) != last
        assert choose_theme(_plan(), last) != last


def test_theme_avoids_the_last_two():
    assert choose_theme(_plan(theme="forest"), ["forest", "ocean"]) not in ("forest", "ocean")
    assert choose_theme(_plan(theme="forest"), ["forest", "ocean", "grape"]) not in ("ocean", "grape")


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


def test_code_focus_shows_at_most_six_code_lines():
    lines = [f"step{i}()" for i in range(9)]
    svg = _svg(_plan("flow", 3, ({**CODE, "lines": lines}, CHECKS, STEPS)), style="code_focus",
               theme="ocean")
    assert "step5()" in svg and "step6()" not in svg
    assert svg_checks(svg) + design_quality_checks(svg) == []


def test_concept_posts_prefer_the_sidebar_then_the_stack():
    plan = _plan("flow", 3, (CHECKS, STEPS, CHECKS), post_type="concept", title="Native APIs")
    assert _style_candidates(plan)[:2] == ["sidebar", "stack"]



# --- Layouts drawn from extra planner content ---

@pytest.mark.parametrize("extra, expected", [
    ({"cards": CARDS}, "matrix"), ({"table": TABLE}, "versus"), ({"layers": LAYERS}, "architecture"),
    ({"stages": STAGES}, "progression"),
])
def test_extra_content_picks_its_layout(extra, expected):
    assert choose_style(_plan("flow", 3, (CODE, CHECKS, STATS), **extra)) == expected


def test_hub_is_used_for_plain_content_when_the_sidebar_was_just_used():
    plan = _plan("flow", 3, (CHECKS, STEPS, CHECKS), title="Agentic RAG")
    assert choose_style(plan) == "sidebar" and choose_style(plan, ["sidebar"]) == "hub"


@pytest.mark.parametrize("cards", [None, "x", CARDS[:5], [{"title": ""}] * 9, [1, 2, 3, 4, 5, 6]])
def test_matrix_needs_six_titled_cards(cards):
    assert _cards(_plan(cards=cards)) == []


def test_matrix_uses_six_or_nine_cards():
    assert len(_cards(_plan(cards=CARDS[:8]))) == 6
    assert len(_cards(_plan(cards=CARDS + CARDS))) == 9


@pytest.mark.parametrize("table", [None, [], {**TABLE, "left": ""}, {**TABLE, "rows": TABLE["rows"][:2]},
                                   {**TABLE, "rows": [{"aspect": ""}] * 4}])
def test_versus_needs_two_sides_and_three_rows(table):
    assert _table(_plan(table=table)) is None


def test_versus_lists_at_most_five_lines_of_when_items():
    long = ["You need a very long reason that wraps across two lines"] * 4
    svg = _svg(_plan(table={**TABLE, "left_when": long}), style="versus", theme="ocean")
    assert svg.count("• You need a very long reason") == 2


@pytest.mark.parametrize("layers", [None, LAYERS[:1], [{"name": "A", "items": []}] * 3,
                                    [{"name": "", "items": LAYERS[0]["items"]}] * 3])
def test_architecture_needs_two_layers_with_items(layers):
    assert _layers(_plan(layers=layers)) == []


@pytest.mark.parametrize("stages", [None, STAGES[:2], [{"label": ""}] * 4,
                                    STAGES[:4] + [{"label": "Hyperautomation", "detail": "x"}]])
def test_progression_needs_three_stages_with_short_words(stages):
    assert _stages(_plan(stages=stages)) == []


@pytest.mark.parametrize("title, hub", [("Observability pipelines", ""), ("", ""),
                                        ("A b c d e f g h i j k l m n o p q r s t", "")])
def test_hub_needs_a_short_label(title, hub):
    plan = _plan(title=title, hero={**_plan()["hero"], "hub": hub})
    assert _hub_label(plan, "") == []


def test_hub_falls_back_to_the_headline():
    plan = _plan(title="", hero={**_plan()["hero"], "hub": ""})
    assert _hub_label(plan, "Agent loop") == ["Agent loop"]
