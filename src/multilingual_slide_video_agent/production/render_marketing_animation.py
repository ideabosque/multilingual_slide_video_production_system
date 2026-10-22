"""Back-compat wrapper over the new engine-seam path
(motion-engines-and-hardening-plan B3 #5): `render-marketing-animation`
stays as an alias for `render-motion --engine playwright`, so existing
skills, agent docs and run artifacts keep working. The visual mechanics
moved to `production/motion/` (playwright_engine.py + post.py); this module
keeps only the old public API surface:

- `render_marketing_animation(...)` - same signature, same envelope, and
  it still writes `marketing_animation.json` (the legacy manifest; the new
  canonical manifest is `motion.json`);
- `MarketingAnimationError` - still raised, still caught by the CLI.

The original GSAP+Playwright rebuild was implemented entirely in this file
(marketing-animation-pipeline-plan §4); that implementation now lives
behind the engine seam so HyperFrames/Remotion (Phases 2b/3) can reuse it.
"""
from __future__ import annotations

import json
from pathlib import Path

from multilingual_slide_video_agent.production.motion.errors import MotionError
from multilingual_slide_video_agent.production.motion.render import render_motion


class MarketingAnimationError(MotionError):
    """Raised by `render_marketing_animation` (and its CLI command). A
    direct subclass of the motion path's `MotionError`, so callers catching
    either name keep working."""


def render_marketing_animation(
    *,
    production_path: str,
    translated_deck_dir: str,
    animation_dir: str,
    slides_dir: str,
    localization_path: str | None = None,
    output_dir: str | None = None,
    output_name: str = "marketing_animation.mp4",
    viewport: str = "1920x1080",
) -> dict:
    """The legacy entry point, now pinned to the `playwright` engine
    regardless of motion.yaml's default_engine (the alias's contract), and
    pinned to the legacy `marketing_animation.mp4` default output name."""
    envelope = render_motion(
        production_path=production_path,
        translated_deck_dir=translated_deck_dir,
        animation_dir=animation_dir,
        slides_dir=slides_dir,
        localization_path=localization_path,
        output_dir=output_dir,
        output_name=output_name,
        engine_name="playwright",
        viewport=viewport,
    )
    # Legacy manifest: the previous renderer wrote envelope["outputs"]'s
    # precursor `result` dict to marketing_animation.json at the same point.
    out_dir = Path(output_dir).resolve() if output_dir else Path(production_path).resolve().parent
    manifest_path = out_dir / "marketing_animation.json"
    manifest_path.write_text(
        json.dumps(envelope["outputs"], indent=2, ensure_ascii=False), encoding="utf-8"
    )
    if envelope.get("status") == "completed":
        envelope["outputs"]["legacy_manifest"] = str(manifest_path)
    return envelope