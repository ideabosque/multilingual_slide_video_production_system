"""Loads config/design_system.yaml and exposes it as CSS custom properties
for injection into an animated slide's <head> (marketing_animation_pipeline_plan
§4.2). Kept separate from config.py's language/terminology/video config
loaders since this one is animation-specific and not used by the rest of
the pipeline."""
from __future__ import annotations

from functools import lru_cache
from typing import Any

from multilingual_slide_video_agent.config import load_yaml

# design_system.yaml key -> CSS custom property name. Only values a GSAP
# timeline actually reads at runtime need to be here (see
# .claude/skills/gsap_animation_authoring/SKILL.md "Design system binding") -
# not every key in the YAML file needs a CSS property (e.g. `radius.lg` has
# no animation use yet).
_CSS_PROPERTY_MAP: dict[str, tuple[str, ...]] = {
    "color": ("bg_page", "bg_surface", "bg_muted", "text_primary", "text_secondary",
              "text_inverse", "brand_primary", "brand_primary_hover", "brand_forest",
              "accent_signal", "accent_signal_soft", "border_default", "border_strong",
              "label_accent"),
    "typography": (),  # font stacks injected separately, not per-color-style
    "motion": ("duration_fast_ms", "duration_base_ms", "duration_slow_ms",
               "slide_enter_ms", "slide_exit_ms"),
}


@lru_cache(maxsize=None)
def load_design_system() -> dict[str, Any]:
    return load_yaml("design_system.yaml")


def _kebab(key: str) -> str:
    return key.replace("_", "-")


def build_css_custom_properties() -> str:
    """A `:root { --ds-... }` block covering every token a GSAP timeline
    might read via getComputedStyle. Idempotent/pure - callers inject this
    same string into every slide's <head>."""
    ds = load_design_system()
    lines = [":root {"]

    typography = ds.get("typography", {})
    if typography.get("font_sans"):
        lines.append(f"  --ds-font-sans: {typography['font_sans']};")
    if typography.get("font_mono"):
        lines.append(f"  --ds-font-mono: {typography['font_mono']};")

    for section, keys in _CSS_PROPERTY_MAP.items():
        section_data = ds.get(section, {})
        for key in keys:
            value = section_data.get(key)
            if value is None:
                continue
            prop = f"--ds-{_kebab(section)}-{_kebab(key)}"
            css_value = f"{value}ms" if key.endswith("_ms") else str(value)
            lines.append(f"  {prop}: {css_value};")

    lines.append("  --ds-motion-easing: cubic-bezier(0.16, 1, 0.3, 1);")  # power2.out approximation
    lines.append("}")
    return "\n".join(lines)
