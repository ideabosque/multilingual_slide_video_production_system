"""`render_motion` - the engine-seam orchestrator (motion-engines-and-
hardening-plan B2/B3): builds the MotionRenderContext, picks an engine
(`config/motion.yaml`'s `default_engine` unless overridden), runs it to an
exact-length silent video, then applies the one shared post-pass (captions
+ narration) and B6 validation, writing `motion.json`.

`msv production render-marketing-animation` stays as an alias for
`render-motion --engine playwright` (B3) - see render_marketing_animation.py,
now a thin compat wrapper over this module.
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any

from multilingual_slide_video_agent.logging_utils import RunLogger
from multilingual_slide_video_agent.production.motion.base import MotionEngine
from multilingual_slide_video_agent.production.motion.context import MotionRenderContext_from_production
from multilingual_slide_video_agent.production.motion.errors import MotionError
from multilingual_slide_video_agent.production.motion import post


KNOWN_ENGINE_NAMES = ("playwright", "hyperframes", "remotion")


def motion_manifest_path(out_dir: Path, output_name: str) -> Path:
    """`<output stem>.motion.json` next to the video it describes, e.g.
    marketing_playwright.mp4 -> marketing_playwright.motion.json."""
    return out_dir / f"{Path(output_name).stem}.motion.json"


def get_engine(name: str) -> MotionEngine:
    """Resolve an engine name to an instance. `remotion` is built in Phase 3
    and says so loudly here rather than pretending to be selectable."""
    if name == "playwright":
        from multilingual_slide_video_agent.production.motion.playwright_engine import PlaywrightEngine

        return PlaywrightEngine()
    if name == "hyperframes":
        from multilingual_slide_video_agent.production.motion.hyperframes_engine import HyperFramesEngine

        return HyperFramesEngine()
    if name == "remotion":
        raise MotionError("engine 'remotion' is implemented in this plan's Phase 3")
    raise MotionError(
        f"unknown motion engine '{name}' - known engines: {', '.join(KNOWN_ENGINE_NAMES)}"
    )


def _record_in_production(
    production_file: Path, final: Path, motion_path: Path, engine_name: str, post_info: dict[str, Any],
    ctx: Any,
) -> None:
    """Make the animated video this language's production video: the fields
    `msv production validate` and publishing read."""
    production = json.loads(production_file.read_text(encoding="utf-8"))
    duration = post_info["final_duration_seconds"]
    production.update({
        "output_video": str(final),
        "video_kind": "animated",
        "motion_engine": engine_name,
        "animation_style": ctx.motion_config.get("animation_style", "calm"),
        "motion_manifest": str(motion_path),
        "captions_motion": post_info["captions_srt"],
        "output_duration_seconds": duration,
        "duration_check_ok": abs(duration - ctx.total_duration) <= ctx.max_duration_drift_seconds,
        "burn_in": post_info["burn_in"],
        "rendered_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })
    production_file.write_text(json.dumps(production, indent=2, ensure_ascii=False), encoding="utf-8")


def render_motion(
    *,
    production_path: str,
    translated_deck_dir: str,
    animation_dir: str,
    slides_dir: str | None = None,
    localization_path: str | None = None,
    roles_path: str | None = None,
    output_dir: str | None = None,
    output_name: str | None = None,
    engine_name: str | None = None,
    viewport: str = "1920x1080",
    record_in_production: bool = True,
) -> dict[str, Any]:
    """Render one language's animated video (default `video.mp4`) against
    the narration timing in its `production.json` - the `rendering` stage
    of animation-first production (plan Part D2), which runs after
    `msv production narrate`.

    With `record_in_production` (the default), the finished video is
    recorded back into that production.json (`output_video`, duration
    check, engine, manifest), so `msv production validate` and publishing
    use it. The legacy `render-marketing-animation` alias passes False: it
    renders a side artifact next to an existing static slideshow.

    Returns a status envelope whose `outputs` carries the manifest keys the
    previous monolithic renderer produced, plus the engine/motion.json
    additions - so the `render-marketing-animation` alias (and every
    skill/doc reading its output) keeps working unchanged. Raises
    MotionError (after `motion.json` + logs are written, when validation is
    what failed) - the caller turns that into the standard {"ok": false,
    "errors": [...]} shape.

    Scratch cleanup: `work_dir` is removed on success, kept on failure -
    the inspectable-failure contract."""
    from multilingual_slide_video_agent.production.motion.validate import validate_motion

    t0 = time.time()
    ctx = MotionRenderContext_from_production(
        production_path=production_path, translated_deck_dir=translated_deck_dir,
        animation_dir=animation_dir, slides_dir=slides_dir, localization_path=localization_path,
        roles_path=roles_path, viewport=viewport,
    )
    language, run_id, project_id = ctx.language, ctx.run_id, ctx.project_id
    logger = RunLogger(run_id, project_id)

    engine_name = engine_name or str(ctx.motion_config.get("default_engine", "playwright"))
    engine = get_engine(engine_name)
    missing = engine.check_available()
    if missing:
        raise MotionError(f"motion engine '{engine_name}' is missing prerequisites: {'; '.join(missing)}")

    production_file = Path(production_path).resolve()
    out_dir = Path(output_dir).resolve() if output_dir else production_file.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    output_name = output_name or "video.mp4"
    work_dir = out_dir / f"_motion_{engine_name}_work"
    work_dir.mkdir(parents=True, exist_ok=True)

    motion_manifest: dict[str, Any] = {
        "run_id": run_id,
        "project_id": project_id,
        "language": language,
        "engine": {"name": engine_name, "version": engine.version() if hasattr(engine, "version") else None},
        "fps": ctx.fps,
        "resolution": ctx.resolution,
        "encode": ctx.motion_config.get("encode", {}),
        "timing": ctx.timing,
        "per_slide": [
            {"slide_id": s.slide_id, "template": s.template,
             "start": round(s.start, 4), "end": round(s.end, 4)}
            for s in ctx.slides
        ],
        "templates": {s.slide_id: s.template for s in ctx.slides},
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    def _write_motion_manifest(validation: dict[str, Any]) -> Path:
        motion_manifest["validation"] = validation
        # Named after the video it describes, so renders by different
        # engines (or to different output names) in one language directory
        # never overwrite each other's record - B6 #5 compares them.
        motion_path = motion_manifest_path(out_dir, output_name)
        motion_path.write_text(json.dumps(motion_manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        return motion_path

    try:
        silent = engine.render(ctx, work_dir / "engine")
        cap_by_slide = post.captions_by_slide_id(localization_path)
        final = out_dir / output_name
        post_info = post.burn_and_mux(silent, ctx, work_dir / "post", cap_by_slide, final)
        validation = validate_motion(
            silent_video=silent, final_video=final, ctx=ctx, work_dir=work_dir / "validation",
            engine_errors=[],
        )
        motion_path = _write_motion_manifest(validation)
        if not validation["ok"]:
            logger.log(
                agent="slideshow_production_agent", skill="slideshow_video_production",
                stage="rendering", language=language, event="motion_validation_failed",
                status="failed", errors=validation["errors"],
            )
            raise MotionError("motion validation failed: " + " | ".join(validation["errors"]))
    except MotionError:
        raise
    except Exception as e:  # noqa: BLE001 - unexpected failures still get named loudly + logged
        logger.log(
            agent="slideshow_production_agent", skill="slideshow_video_production",
            stage="rendering", language=language, event="motion_render_failed",
            status="failed", errors=[str(e)],
        )
        raise MotionError(str(e)) from e

    shutil.rmtree(work_dir, ignore_errors=True)

    result = {
        "run_id": run_id,
        "project_id": project_id,
        "language": language,
        "source_production": str(production_file),
        "narration_audio": str(ctx.narration_audio),
        "captions": post_info["captions_srt"],
        "output_video": str(final),
        "motion_json": str(motion_path),
        "engine": engine_name,
        "style": "gsap_animated",
        "resolution": ctx.resolution,
        "fps": ctx.fps,
        "duration_seconds": post_info["final_duration_seconds"],
        "total_duration_seconds": round(ctx.total_duration, 3),
        "slides": [s.slide_id for s in ctx.slides],
        "templates": motion_manifest["templates"],
        "validation_ok": True,
        "generated_at": motion_manifest["generated_at"],
    }

    if record_in_production:
        _record_in_production(production_file, final, motion_path, engine_name, post_info, ctx)
        result["recorded_in_production"] = str(production_file)

    envelope = logger.status_envelope(
        agent="slideshow_production_agent", language=language, status="completed",
        outputs=result, warnings=[],
    )
    logger.log(
        agent="slideshow_production_agent", skill="slideshow_video_production",
        stage="rendering", language=language, event="motion_render_completed", status="completed",
        duration_seconds=time.time() - t0,
        artifacts=[str(final), str(motion_path), post_info["captions_srt"]],
    )
    return envelope