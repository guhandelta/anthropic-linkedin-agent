"""Extra colour themes built from short brand palettes (3-5 colours each).

A poster needs about 35 colour tokens (page, cards, text, banners, five accents, code panel,
warning strip...). Each palette below names only a few colours, so build_theme() derives the
rest and nudges every text colour darker or lighter until it meets WCAG contrast on whatever it
sits on: 4.5:1 for body text, 3:1 for bold accents. The palette's own colours stay recognisable.
"""
from __future__ import annotations

# name: (colours, "light" or "dark" page, what the palette suits; the planner sees the hint)
PALETTES: dict[str, tuple[tuple[str, ...], str, str]] = {
    "tangerine": (("#008080", "#FF6B35", "#F4F1EA"), "light", "friendly how-tos and practical tips"),
    "sage": (("#8A9A86", "#2C4C3B", "#F9F8F6"), "light", "calm best practices and maintainability"),
    "prussian": (("#003153", "#E07A5F", "#F4A261"), "light", "data engineering and analytics"),
    "charcoal": (("#2B2D42", "#EF233C", "#8D99AE"), "light", "warnings, hard truths and myths busted"),
    "violet": (("#3A0CA3", "#4361EE", "#E0AAFF"), "light", "AI research and LLM internals"),
    "emerald": (("#06D6A0", "#073B4C", "#FFD166"), "dark", "observability, metrics and dashboards"),
    "crimson": (("#D90429", "#EDF2F4", "#2B2D42"), "light", "breaking changes and deprecations"),
    "indigo": (("#1E1B4B", "#FFEDD5", "#C2410C"), "light", "career, leadership and opinion pieces"),
    "mint": (("#A7F3D0", "#064E3B", "#FFFBEB"), "light", "performance wins and cost savings"),
    "cyber": (("#00F5D4", "#7B2CBF", "#240046"), "dark", "AI agents and futuristic tech"),
    "seafoam": (("#A2D2FF", "#84A98C", "#E9D8A6", "#1D3557"), "light", "cloud and platform explainers"),
    "rosegold": (("#C14953", "#E0A96D", "#581845", "#B76E79"), "light", "design, UX and frontend craft"),
    "neonpop": (("#FF007F", "#0077FF", "#FFD60A", "#2B2D42"), "light", "bold launches and hot takes"),
    "plum": (("#4A0E4E", "#8F9779", "#DCD6CD", "#D4AF37"), "light", "enterprise, strategy and premium tools"),
    "rust": (("#A63A50", "#F0A202", "#F8F4E3", "#0C1618"), "light", "lessons learned and post-mortems"),
    "slate": (("#475569", "#BAE6FD", "#F59E0B", "#F8FAFC"), "light", "developer tooling and productivity"),
    "eggplant": (("#31112C", "#7D0633", "#F2A154", "#F7E2B5"), "light", "storytelling and deep dives"),
    "lagoon": (("#0077B6", "#90E0EF", "#CAF0F8", "#03045E"), "light", "networking, data flow and streaming"),
    "steel": (("#778DA9", "#415A77", "#E0E1DD", "#1B263B"), "light", "backends, databases and architecture"),
    "salmon": (("#FFA69E", "#AAFCB8", "#1D4E89", "#FAF3DD"), "light", "beginner-friendly tutorials"),
    "mystic": (("#FF4900", "#020001", "#B2D5E9", "#D9A5CD", "#CCA800"), "light",
               "creative and experimental ideas"),
    "woodland": (("#1B4332", "#52B788", "#74C69D", "#3D2314", "#F5F5F0"), "light",
                 "green computing, efficiency and scaling"),
    "desert": (("#E9C46A", "#F4A261", "#264653", "#2A9D8F", "#E76F51"), "light",
               "data science and visual analytics"),
    "orchid": (("#240046", "#5A189A", "#7B2CBF", "#9D4EDD", "#C77DFF"), "dark",
               "generative AI and creative coding"),
    "coastal": (("#006D77", "#83C5BE", "#EDF6F9", "#FFDDD2", "#E29578"), "light",
                "people, teams and ways of working"),
    "denim": (("#0B3C5D", "#D9B310", "#328CC1", "#1D2731", "#F5F7FA"), "light",
              "business metrics and benchmarks"),
    "berry": (("#6B2D5C", "#F1A7B1", "#F6E8EA", "#221E22", "#90A955"), "light",
              "community, culture and open source"),
    "pastel": (("#D8E2DC", "#FFE5D9", "#FFCAD4", "#B388EB", "#8093F1"), "light",
               "gentle introductions to new concepts"),
    "volcano": (("#1A1A24", "#C3073F", "#950740", "#4E4E50", "#6F2232"), "dark",
                "security threats, outages and critical bugs"),
}

WHITE, BLACK = "#FFFFFF", "#000000"
_LIGHT_WARN = {"warn_bg": "#FFF3DD", "warn_stroke": "#E5B967", "warn_icon": "#B46A16",
               "warn_head": "#8A4C0B", "warn_text": "#5B421E"}
_DARK_WARN = {"warn_bg": "#3A2A10", "warn_stroke": "#8A6A2A", "warn_icon": "#FFC56B",
              "warn_head": "#FFD58F", "warn_text": "#F3E2C2"}
# Used when a palette has fewer than five distinct accent colours.
_SPARE = ("#2E6F8E", "#2F7D5B", "#8B5A12", "#6B4FA8", "#B33A2A")


def _rgb(colour: str) -> tuple[int, int, int]:
    return tuple(int(colour[i:i + 2], 16) for i in (1, 3, 5))


def _hex(rgb) -> str:
    return "#" + "".join(f"{max(0, min(255, round(v))):02X}" for v in rgb)


def mix(a: str, b: str, share_b: float) -> str:
    """a blended with share_b of b."""
    return _hex(x + (y - x) * share_b for x, y in zip(_rgb(a), _rgb(b)))


def luminance(colour: str) -> float:
    def channel(v: int) -> float:
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(v) for v in _rgb(colour))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _chroma(colour: str) -> int:
    rgb = _rgb(colour)
    return max(rgb) - min(rgb)


def fit(colour: str, backgrounds: list[str], ratio: float, toward: str) -> str:
    """Darken (toward black) or lighten (toward white) a colour until it reads on every background."""
    for _ in range(60):
        if all(contrast(colour, bg) >= ratio + 0.05 for bg in backgrounds):
            return colour
        colour = mix(colour, toward, 0.06)
    return toward


def _distinct(colours: list[str], min_gap: int = 60) -> list[str]:
    out: list[str] = []
    for colour in colours:
        if all(sum(abs(x - y) for x, y in zip(_rgb(colour), _rgb(o))) >= min_gap for o in out):
            out.append(colour)
    return out


def build_theme(colours: tuple[str, ...], mode: str) -> dict[str, str]:
    """Every poster colour token from a few brand colours, with readable text everywhere."""
    by_light = sorted(colours, key=luminance)
    darkest, lightest = by_light[0], by_light[-1]
    # The brand colour: the most vivid colour that is not a pale background tone.
    # On a dark page a bright neon is the brand colour; on a light page pale tones are not.
    pool = [c for c in colours if c != darkest] if mode == "dark" else [
        c for c in colours if luminance(c) < 0.6] or list(colours)
    vivid = sorted(pool, key=_chroma, reverse=True)
    brand = vivid[0]
    if mode == "dark":
        bg = mix(darkest, BLACK, 0.45)
        card, node = mix(bg, WHITE, 0.07), mix(bg, WHITE, 0.11)
        soft, soft2 = mix(bg, brand, 0.22), mix(bg, brand, 0.14)
        surfaces = [bg, card, node, soft, soft2]
        towards = WHITE
        ink = fit(mix(lightest, WHITE, 0.8), surfaces, 7, WHITE)
        warn = _DARK_WARN
        good_soft, bad_soft = mix(bg, "#5FD3A5", 0.14), mix(bg, "#FF8A6B", 0.14)
        good, bad = fit("#5FD3A5", [good_soft], 3, WHITE), fit("#FF8A6B", [bad_soft], 3, WHITE)
        soft_stroke, card_stroke = mix(bg, brand, 0.45), mix(bg, WHITE, 0.2)
        code_bg = mix(bg, BLACK, 0.5)
    else:
        bg = lightest if luminance(lightest) >= 0.85 else mix(lightest, WHITE, 0.75)
        card, node = WHITE, mix(bg, WHITE, 0.4)
        soft, soft2 = mix(brand, WHITE, 0.87), mix(brand, WHITE, 0.93)
        surfaces = [bg, card, node, soft, soft2]
        towards = BLACK
        ink = fit(mix(darkest, BLACK, 0.35), surfaces, 7, BLACK)
        warn = _LIGHT_WARN
        good_soft, bad_soft = "#EAF6F0", "#FCEDE8"
        good, bad = fit("#1D9369", [good_soft, card], 3, BLACK), fit("#C2412D", [bad_soft, card], 3, BLACK)
        soft_stroke, card_stroke = mix(brand, WHITE, 0.68), mix(ink, WHITE, 0.86)
        code_bg = fit(mix(darkest, BLACK, 0.45), [WHITE], 12, BLACK)

    primary = fit(brand, surfaces, 4.5, towards)
    accents = [fit(c, surfaces, 3, towards) for c in vivid + [c for c in colours if c not in vivid]]
    accents = _distinct([primary] + accents + [fit(c, surfaces, 3, towards) for c in _SPARE])[:5]
    strong = fit(brand, [WHITE], 4.5, BLACK)
    rule = mix(ink, bg, 0.8)
    theme = {
        "bg": bg, "card": card, "node": node, "soft": soft, "soft2": soft2,
        "soft_stroke": soft_stroke, "card_stroke": card_stroke,
        "soft_ink": fit(primary, [soft, soft2], 4.5, towards),
        "strong": strong, "on_strong": WHITE, "ink": ink,
        "muted": fit(mix(ink, bg, 0.3), surfaces, 4.5, towards), "primary": primary,
        **{f"a{i + 1}": colour for i, colour in enumerate(accents)},
        "good": good, "bad": bad, "good_soft": good_soft, "bad_soft": bad_soft,
        "code_bg": code_bg, "code_ink": WHITE,
        "code_muted": fit(mix(WHITE, brand, 0.12), [code_bg], 7, WHITE),
        "code_icon": fit(mix(brand, WHITE, 0.4), [code_bg], 3, WHITE),
        **warn, "rule": rule,
        "footer": fit(mix(ink, bg, 0.45), [bg], 4.5, towards),
    }
    return {k: v.upper() for k, v in theme.items()}


EXTRA_THEMES = {name: build_theme(colours, mode) for name, (colours, mode, _) in PALETTES.items()}
EXTRA_HINTS = {name: hint for name, (_, _, hint) in PALETTES.items()}
