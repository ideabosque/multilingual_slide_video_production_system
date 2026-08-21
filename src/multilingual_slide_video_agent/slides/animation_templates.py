"""Named GSAP shot templates and the heuristic that picks one per slide.

The actual GSAP code lives in assets/animation_runtime.js (identical JS
across every slide of a deck - see that file's docstring); this module is
the Python-side registry of valid template names plus the default
selection logic `generate_animation.py` uses when no explicit spec is
given. Template choice is a motion-design judgment call - see
.claude/skills/motion_design_principles/SKILL.md's role table, which this
function implements.
"""
from __future__ import annotations

TEMPLATE_NAMES = (
    "title_reveal",
    "feature_callout",
    "stat_highlight",
    "diagram_build",
    "closing",
)

DEFAULT_TEMPLATE = "feature_callout"

_STAT_HINTS = ("%", "percent", "reduction", "increase", "faster", "fewer", "x more", "x faster")
_DIAGRAM_HINTS = ("architecture", "diagram", "flow", "pipeline", "system", "topology")
_CTA_HINTS = ("contact", "get started", "learn more", "sign up", "book", "demo", "talk to")


def choose_template(
    *,
    slide_index: int,
    slide_count: int,
    slide_description: str = "",
    visual_role: str | None = None,
) -> str:
    """Pick a shot template for one slide.

    `visual_role` — an optional per-slide field `slide-analysis-agent` can
    write into `slide_analysis.json` (marketing_animation_pipeline_plan.md
    §4.1's "recommended next step") — takes priority when it's one of
    `TEMPLATE_NAMES`: Agent 1's own judgment about a slide, formed while
    already analyzing its content, is a stronger signal than keyword
    matching free text after the fact. Falls back to the position +
    keyword heuristic (see motion_design_principles SKILL.md's role table)
    for decks analyzed before this field existed, or where it's absent/
    unrecognized - this function never raises on a bad value, it just
    ignores it and falls through (the caller, `generate_deck_animation`,
    is where an invalid `visual_role` fails loudly instead, since silently
    ignoring a typo there would be a worse failure mode - see that
    module's validation).
    """
    if visual_role in TEMPLATE_NAMES:
        return visual_role
    if slide_index == 1:
        return "title_reveal"
    if slide_index == slide_count:
        return "closing"

    text = (slide_description or "").lower()
    if any(hint in text for hint in _CTA_HINTS):
        return "closing"
    if any(hint in text for hint in _STAT_HINTS):
        return "stat_highlight"
    if any(hint in text for hint in _DIAGRAM_HINTS):
        return "diagram_build"
    return DEFAULT_TEMPLATE


def build_spec(slides: list[dict]) -> dict[str, str]:
    """slides: [{"slide_index": 1, "slide_id": "slide_001", "slide_description": "...",
    "visual_role": "stat_highlight" | None}]. Returns {slide_id: template_name},
    covering every slide."""
    count = len(slides)
    return {
        s["slide_id"]: choose_template(
            slide_index=s["slide_index"],
            slide_count=count,
            slide_description=s.get("slide_description", ""),
            visual_role=s.get("visual_role"),
        )
        for s in slides
    }
