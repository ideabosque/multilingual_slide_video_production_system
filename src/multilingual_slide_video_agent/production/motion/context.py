"""MotionRenderContext - the single input contract every motion engine
renders from (motion-engines-and-hardening-plan B2). Built from one
language's already-completed `production.json` (the sequential dependency,
marketing-animation-pipeline-plan §5 Decision 0), the deck's animation
bundle, and the design system - never from fresh TTS or timing decisions.

`production.json`'s `segment_timing` remains the single source of truth for
every slide's start and end (B1's unchanged list) - engines do not
re-derive it.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from multilingual_slide_video_agent import config as cfg
from multilingual_slide_video_agent.production.motion.errors import MotionContextError
from multilingual_slide_video_agent.slides.design_system import load_design_system


@dataclass
class MotionSlide:
    """One timing item with its template (spec.json) and, when
    `roles_<language>.json` was produced by `msv slides extract-roles`,
    its resolved per-language roles (B3 #2 - the content contract the
    Remotion engine consumes, and a validation aid everywhere else)."""

    slide_id: str
    template: str
    start: float
    end: float
    roles: dict[str, Any] | None = None

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class MotionRenderContext:
    run_id: str
    project_id: str
    language: str
    resolution: dict[str, int]
    fps: int
    viewport: str
    timing: list[dict[str, Any]]                      # production.json's segment_timing, verbatim
    slides: list[MotionSlide]
    title: str | None
    title_item: dict[str, Any] | None                 # timing item for the title card, if any
    production_path: Path
    translated_deck_dir: Path
    animation_dir: Path
    slides_dir: Path | None                           # rendered slide PNGs; optional, no current engine needs them
    segment_audio_dir: Path
    narration_audio: Path
    design_tokens: dict[str, Any]
    max_duration_drift_seconds: float
    video_config: dict[str, Any] = field(default_factory=dict)
    motion_config: dict[str, Any] = field(default_factory=dict)
    # A validated motion-design/v1 document (plan C3), when the deck has
    # one; None plays each slide's template.
    motion_design: dict[str, Any] | None = None

    @property
    def total_duration(self) -> float:
        """The whole video's length - the last timing item's end time."""
        return self.timing[-1]["end_time"]

    def slide_by_id(self, slide_id: str) -> MotionSlide:
        for slide in self.slides:
            if slide.slide_id == slide_id:
                return slide
        raise MotionContextError(f"no motion slide timing for '{slide_id}'")


def _load_json(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _resolution_from_video_config(video_cfg: dict[str, Any]) -> dict[str, int]:
    resolution_name = os.getenv("VIDEO_RESOLUTION", "1080p")
    resolutions = video_cfg.get("resolutions", {})
    if resolution_name not in resolutions:
        raise MotionContextError(
            f"VIDEO_RESOLUTION '{resolution_name}' is not in video.yaml's resolutions ({sorted(resolutions)})"
        )
    return {"width": resolutions[resolution_name]["width"], "height": resolutions[resolution_name]["height"]}


def MotionRenderContext_from_production(
    *,
    production_path: str | Path,
    translated_deck_dir: str | Path,
    animation_dir: str | Path,
    slides_dir: str | Path | None,
    localization_path: str | Path | None = None,
    roles_path: str | Path | None = None,
    viewport: str = "1920x1080",
    fps: int | None = None,
    resolution: dict[str, int] | None = None,
    motion_config: dict[str, Any] | None = None,
    video_config: dict[str, Any] | None = None,
) -> "MotionRenderContext":
    """Build a MotionRenderContext from one already-rendered language's
    `production.json` (written by `msv production narrate`) plus its
    animation bundle.

    `roles_path` (from `msv slides extract-roles`; conventionally named
    `roles_<language>.json`) is optional: engines that don't need the
    content contract yet render without it, and a missing file never makes
    a render fail.

    `localization_path` is accepted here (the context is where a caller
    would expect caption text to live) but captions are resolved by the
    shared post-pass from production.json's `segment_timing` +
    `localization_<language>.json` - see post.py's module docstring for
    why they are not part of the context itself."""

    production_file = Path(production_path).resolve()
    production = _load_json(production_file)

    timing = production.get("segment_timing") or []
    if not timing:
        raise MotionContextError("production.json has no segment_timing")

    video_cfg = video_config if video_config is not None else cfg.video_config()
    motion_cfg = motion_config if motion_config is not None else cfg.motion_config()

    narration_audio = Path(production.get("narration_audio", "")).resolve()
    if not narration_audio.parent.exists():
        raise MotionContextError(f"narration_audio's directory not found: {narration_audio.parent}")
    # Where narrate actually put (or found) the per-slide clips - it can be
    # an explicit --audio-dir elsewhere. Older production.json files predate
    # the field; their clips sit in segments/ next to narration.mp3.
    seg_audio_dir = (
        Path(production["segment_audio_dir"]).resolve() if production.get("segment_audio_dir")
        else narration_audio.parent / "segments"
    )

    animation_path = Path(animation_dir).resolve()
    spec = _load_json(animation_path / "spec.json")
    template_by_slide = {s["slide_id"]: s["template"] for s in spec.get("slides", [])}

    roles_by_slide: dict[str, dict[str, Any]] = {}
    if roles_path is not None:
        roles_doc = _load_json(Path(roles_path).resolve())
        roles_by_slide = {r.get("slide_id"): r.get("roles") for r in roles_doc.get("slides", [])}

    slides: list[MotionSlide] = []
    for item in timing:
        if item.get("kind") != "slide":
            continue
        slide_id = item["slide_id"]
        if slide_id not in template_by_slide:
            raise MotionContextError(
                f"no animation template assigned for slide '{slide_id}' - the "
                f"animation bundle at {animation_path} doesn't match this deck's slides"
            )
        slides.append(
            MotionSlide(
                slide_id=slide_id,
                template=template_by_slide[slide_id],
                start=item["start_time"],
                end=item["end_time"],
                roles=roles_by_slide.get(slide_id),
            )
        )
    if not slides:
        raise MotionContextError("production.json's segment_timing contains no slide items")

    title_item = next((item for item in timing if item.get("kind") == "title"), None)
    title = production.get("title") if title_item is not None else None

    try:
        tokens = load_design_system()
    except FileNotFoundError as e:
        raise MotionContextError(f"design system not found (B2 resolves tokens for every engine): {e}") from e

    return MotionRenderContext(
        run_id=production.get("run_id", "unknown-run"),
        project_id=production.get("project_id", "unknown-project"),
        language=production.get("language", "unknown"),
        resolution=resolution or _resolution_from_video_config(video_cfg),
        fps=int(fps if fps is not None else motion_cfg.get("fps", 30)),
        viewport=viewport,
        timing=timing,
        slides=slides,
        title=title,
        title_item=title_item,
        production_path=production_file,
        translated_deck_dir=Path(translated_deck_dir).resolve(),
        animation_dir=animation_path,
        slides_dir=Path(slides_dir).resolve() if slides_dir else None,
        segment_audio_dir=seg_audio_dir,
        narration_audio=narration_audio,
        design_tokens=tokens,
        max_duration_drift_seconds=float(
            video_cfg.get("sync", {}).get("max_duration_drift_seconds", 0.75)
        ),
        video_config=video_cfg,
        motion_config=motion_cfg,
    )