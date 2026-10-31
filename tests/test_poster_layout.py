import json

from PIL import Image, ImageChops

from infographic import design_quality_checks, finalize_svg, render_svg_to_gif, svg_checks
from poster_layout import MARKER, poster_from_brief


def test_structured_poster_passes_readability_checks(tmp_path):
    plan = {
        "title": "Built-in Web APIs for leaner apps",
        "subtitle": "A practical path through browser capabilities",
        "tagline": "Less dependency code, with a compatibility check",
        "hero": {"caption": "Replace one library with a native capability", "nodes": [
            {"label": "Find usage", "detail": "Inspect one library's calls", "icon": "search"},
            {"label": "Select API", "detail": "Check support and permissions", "icon": "code"},
            {"label": "Measure", "detail": "Compare bundle size", "icon": "check"},
        ]},
        "modules": [
            {"kind": "code", "heading": "Clipboard API", "icon": "code",
             "lines": ["await navigator.clipboard.writeText(text)"]},
            {"kind": "checklist", "heading": "Compatibility", "icon": "check",
             "lines": ["Check browser support", "Check secure context", "Keep a fallback"]},
            {"kind": "steps", "heading": "Rollout", "icon": "layers",
             "lines": ["Replace one call", "Test in browsers", "Measure bundle size"]},
            {"kind": "steps", "heading": "Tradeoff", "icon": "warning",
             "lines": ["Permissions vary", "Fallback may remain"]},
        ],
        "gotcha": {"heading": "Watch out", "text": "Browser support and permissions vary."},
        "takeaway": "Try one native API and measure its impact.",
    }
    svg = finalize_svg(poster_from_brief(MARKER + "\n" + json.dumps(plan), "Heading", "Author"))
    assert svg_checks(svg) == []
    assert design_quality_checks(svg) == []
    assert svg.count('data-motion-step=') == 3
    gif = render_svg_to_gif(svg, tmp_path / "motion.gif", n_frames=3, fps=3)
    with Image.open(gif) as image:
        assert image.n_frames == 3
        image.seek(0)
        first = image.convert("RGB")
        image.seek(1)
        assert ImageChops.difference(first, image.convert("RGB")).getbbox() is not None


def test_incomplete_blueprint_uses_designer_fallback():
    assert poster_from_brief(MARKER + "\n{}", "Heading", "Author") is None
