"""Named GSAP shot templates, loaded from config/animation_templates.yaml,
and the heuristic that picks one per slide.

The templates themselves are declarative data (which role, which effect,
what timing/position) - see that YAML file's header comment for the
schema. `slides/assets/animation_runtime.js` has a small, fixed registry
of reusable effect primitives (reveal/accent_line/count_up) and one
generic engine that plays a template's steps into a gsap.timeline();
adding or tuning a template is normally a YAML edit, not a JS change (see
.claude/skills/gsap_animation_authoring/SKILL.md). This module is the
Python-side loader/validator for that config, plus the selection logic
`generate_animation.py` uses when no explicit spec is given. Template
choice is a motion-design judgment call - see
.claude/skills/motion_design_principles/SKILL.md's role table, which this
function implements.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any

from multilingual_slide_video_agent.config import load_yaml

DEFAULT_TEMPLATE = "feature_callout"

_STAT_HINTS = ("%", "percent", "reduction", "increase", "faster", "fewer", "x more", "x faster")
_DIAGRAM_HINTS = ("architecture", "diagram", "flow", "pipeline", "system", "topology")
_CTA_HINTS = ("contact", "get started", "learn more", "sign up", "book", "demo", "talk to")
_QUOTE_HINTS = ("quote", "testimonial", "customer says", "review")
_COMPARISON_HINTS = ("vs.", " vs ", "versus", "compared to", "comparison")
_TIMELINE_HINTS = ("roadmap", "timeline", "milestone", "rollout plan", "phase 1")

_KNOWN_ROLES = {"title", "subtitle", "body", "diagram", "stat", "cta", "nodes"}
_KNOWN_EFFECTS = {"reveal", "accent_line", "count_up"}
_KNOWN_DURATION_TOKENS = {"fast", "base", "slow", "slide_enter", "slide_exit"}


class AnimationTemplateConfigError(Exception):
    """config/animation_templates.yaml is malformed - a config typo should
    fail loudly at load time, not surface as a silent no-op or a browser
    console error discovered later during capture."""


def _validate_step(where: str, step: dict[str, Any], earlier_ids: set[str]) -> None:
    role = step.get("role")
    roles = role if isinstance(role, list) else [role]
    if not roles or any(r not in _KNOWN_ROLES for r in roles):
        raise AnimationTemplateConfigError(f"{where}: 'role' must be one of {sorted(_KNOWN_ROLES)}, got {role!r}")

    effect = step.get("effect")
    if effect not in _KNOWN_EFFECTS:
        raise AnimationTemplateConfigError(f"{where}: 'effect' must be one of {sorted(_KNOWN_EFFECTS)}, got {effect!r}")

    duration = step.get("duration")
    if duration is not None and duration not in _KNOWN_DURATION_TOKENS:
        raise AnimationTemplateConfigError(
            f"{where}: 'duration' must be one of {sorted(_KNOWN_DURATION_TOKENS)}, got {duration!r}"
        )

    stagger = (step.get("params") or {}).get("stagger")
    if isinstance(stagger, str) and stagger not in _KNOWN_DURATION_TOKENS:
        raise AnimationTemplateConfigError(
            f"{where}: params.stagger string must be one of {sorted(_KNOWN_DURATION_TOKENS)}, got {stagger!r}"
        )

    skip_if_ran = step.get("skip_if_ran")
    if skip_if_ran is not None and skip_if_ran not in earlier_ids:
        raise AnimationTemplateConfigError(
            f"{where}: skip_if_ran={skip_if_ran!r} does not match any earlier step's 'id' in the same template"
        )


def _validate_template_config(config: dict[str, Any]) -> None:
    if not config:
        raise AnimationTemplateConfigError("animation_templates.yaml is empty - at least one template is required")
    for template_name, template in config.items():
        steps = template.get("steps") if isinstance(template, dict) else None
        if not isinstance(steps, list) or not steps:
            raise AnimationTemplateConfigError(f"animation_templates.yaml: {template_name!r} needs a non-empty 'steps' list")
        # skip_if_ran may only reference a step earlier in the same list,
        # so ids accumulate as we walk forward rather than being collected
        # up front.
        seen_ids: set[str] = set()
        for i, step in enumerate(steps):
            _validate_step(f"animation_templates.yaml: {template_name}.steps[{i}]", step, seen_ids)
            if step.get("id"):
                seen_ids.add(step["id"])


@lru_cache(maxsize=None)
def load_template_config() -> dict[str, Any]:
    config = load_yaml("animation_templates.yaml")
    _validate_template_config(config)
    return config


@lru_cache(maxsize=None)
def _template_names() -> tuple[str, ...]:
    return tuple(load_template_config().keys())


def __getattr__(name: str) -> Any:
    # TEMPLATE_NAMES is derived from config/animation_templates.yaml (so
    # adding a template there makes it valid here automatically) but kept
    # as a plain module attribute for callers/tests that do
    # `from ... import TEMPLATE_NAMES`.
    if name == "TEMPLATE_NAMES":
        return _template_names()
    raise AttributeError(name)


def choose_template(
    *,
    slide_index: int,
    slide_count: int,
    slide_description: str = "",
    visual_role: str | None = None,
) -> str:
    """Pick a shot template for one slide.

    `visual_role` — an optional per-slide field `slide-analysis-agent` can
    write into `slide_analysis.json` — takes priority when it's one of
    TEMPLATE_NAMES: Agent 1's own judgment about a slide, formed while
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
    names = _template_names()
    if visual_role in names:
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
    if any(hint in text for hint in _QUOTE_HINTS):
        return "quote_testimonial"
    if any(hint in text for hint in _COMPARISON_HINTS):
        return "comparison_versus"
    if any(hint in text for hint in _TIMELINE_HINTS):
        return "timeline_roadmap"
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
