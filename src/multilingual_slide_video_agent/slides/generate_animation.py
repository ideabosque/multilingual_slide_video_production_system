"""Agent 1: generate one deck's GSAP animation bundle, once, at analysis
time (marketing_animation_pipeline_plan §4.1). Reused unmodified across
every language's translated deck and every future render - never
regenerated per language or per run unless the deck itself changes.

Deliberately does NOT touch the deck's HTML - it only decides which named
shot template (animation_templates.TEMPLATE_NAMES) applies to each slide
and writes that decision plus the runtime assets. Injecting the actual
<script>/<style> tags into a translated deck happens later, in the
video-capture step (slides/render.py), the same separation
apply_translations.py already has from render.py's static screenshot step.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from multilingual_slide_video_agent.slides.animation_templates import (
    TEMPLATE_NAMES,
    build_spec,
)
from multilingual_slide_video_agent.slides.design_system import build_css_custom_properties
from multilingual_slide_video_agent.slides.extract_text import list_slide_files

_ASSETS_DIR = Path(__file__).parent / "assets"
_VENDOR_DIR = Path(__file__).parent / "vendor"

ANIMATION_JS_NAME = "animation_runtime.js"
GSAP_JS_NAME = "gsap.min.js"
DESIGN_TOKENS_CSS_NAME = "design_tokens.css"
SPEC_FILE_NAME = "spec.json"


class GenerateAnimationError(Exception):
    pass


def _load_slide_analysis(path: str | Path | None) -> dict[str, dict[str, Any]]:
    """slide_id -> {"slide_description": ..., "visual_role": ... | None},
    from slide_analysis.json if given. `visual_role` is an optional field
    (marketing_animation_pipeline_plan.md §4.1's "recommended next step") -
    absent entirely on decks analyzed before it existed."""
    if not path:
        return {}
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    return {
        s["slide_id"]: {"slide_description": s.get("slide_description", ""), "visual_role": s.get("visual_role")}
        for s in doc.get("slides", [])
    }


def generate_deck_animation(
    *,
    deck_dir: str | Path,
    out_dir: str | Path,
    slide_analysis_path: str | Path | None = None,
    spec_override: dict[str, str] | None = None,
) -> dict[str, Any]:
    deck_path = Path(deck_dir).resolve()
    out_path = Path(out_dir).resolve()
    out_path.mkdir(parents=True, exist_ok=True)

    slide_files = list_slide_files(deck_path)
    analysis_by_slide = _load_slide_analysis(slide_analysis_path)
    slides = [
        {
            "slide_index": i + 1,
            "slide_id": f.stem,
            "slide_description": analysis_by_slide.get(f.stem, {}).get("slide_description", ""),
            "visual_role": analysis_by_slide.get(f.stem, {}).get("visual_role"),
        }
        for i, f in enumerate(slide_files)
    ]

    bad_roles = [
        (s["slide_id"], s["visual_role"]) for s in slides
        if s["visual_role"] is not None and s["visual_role"] not in TEMPLATE_NAMES
    ]
    if bad_roles:
        raise GenerateAnimationError(
            f"slide_analysis.json has invalid visual_role value(s): {bad_roles}. "
            f"Valid names: {list(TEMPLATE_NAMES)}"
        )

    if spec_override:
        unknown = set(spec_override.values()) - set(TEMPLATE_NAMES)
        if unknown:
            raise GenerateAnimationError(
                f"--spec references unknown template name(s): {sorted(unknown)}. "
                f"Valid names: {list(TEMPLATE_NAMES)}"
            )
        missing = {s["slide_id"] for s in slides} - set(spec_override)
        if missing:
            raise GenerateAnimationError(f"--spec is missing slide(s): {sorted(missing)}")
        spec = dict(spec_override)
    else:
        spec = build_spec(slides)

    shutil.copy2(_ASSETS_DIR / ANIMATION_JS_NAME, out_path / ANIMATION_JS_NAME)
    shutil.copy2(_VENDOR_DIR / GSAP_JS_NAME, out_path / GSAP_JS_NAME)
    (out_path / DESIGN_TOKENS_CSS_NAME).write_text(build_css_custom_properties(), encoding="utf-8")

    manifest = {
        "source_deck": str(deck_path),
        "animation_dir": str(out_path),
        "template_names": list(TEMPLATE_NAMES),
        "slides": [
            {
                "slide_id": s["slide_id"],
                "slide_index": s["slide_index"],
                "template": spec[s["slide_id"]],
                # True when slide_analysis.json's visual_role actually drove
                # this slide's template (vs. the position/keyword heuristic
                # or a --spec override) - useful for spot-checking how much
                # of a deck's selection came from Agent 1's own judgment.
                "visual_role_used": bool(not spec_override and s["visual_role"] in TEMPLATE_NAMES),
            }
            for s in slides
        ],
    }
    (out_path / SPEC_FILE_NAME).write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest
