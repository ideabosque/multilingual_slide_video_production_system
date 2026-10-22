"""Per-render motion validation (motion-engines-and-hardening-plan B6,
items 1-4 for Phase 1; item 5's cross-engine compare is tooling in Phases
4/7). Runs automatically after every `render-motion` and writes its results
into `motion.json`; failures fail the render loudly - the same "fail
loudly, not silently" standard as the capture step's console-error rule,
because a blank boundary frame or an animation that never visibly happened
is exactly the failure mode nothing about the output otherwise reveals.

Checks:
1. **Duration** - the silent video's duration equals `ctx.total_duration`
   within one frame (the engine's own contract, re-verified here), and the
   final video's within `sync.max_duration_drift_seconds`.
2. **No blank boundary frames** - frames at each slide's start + 1 frame
   and end - 1 frame; a near-uniform white or black frame (mean + stddev
   pair) fails, naming the slide. Guards both regression classes of the
   flash bugs documented in the earlier plan (intra-slide FOUC and the
   inter-slide blank lead-in). Runs on the *silent* video, so cue/burn-in
   content can't mask a blank background.
3. **Animation actually happened** - the frames at the slide's entrance and
   settle must differ by more than a threshold. Catches selectors that
   silently resolve to nothing (the runtime skips an unresolved beat rather
   than throwing - by design - so nothing else would catch it). Also from
   the silent video.
4. **Engine errors** - the capture step already fails loudly on browser
   console errors; the validation record carries the post-render list
   (post-render errors only, e.g. from a lint future engines expose).

Frame analysis uses Pillow + numpy on grayscale frames (both in
pyproject.toml - the earlier plan's Decision 1 trade-off note).
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import numpy
from PIL import Image

from multilingual_slide_video_agent.media import ffprobe_duration
from multilingual_slide_video_agent.production.motion.context import MotionRenderContext
from multilingual_slide_video_agent.production.motion.errors import MotionError


def _gray_array(png_path: Path) -> numpy.ndarray:
    with Image.open(png_path) as im:
        return numpy.asarray(im.convert("L"), dtype=numpy.float32)


def frame_stats(png_path: Path) -> dict[str, float]:
    """A frame's grayscale mean/stddev - the B6 check-2 pair. Exposed for
    unit tests (and `motion doctor` diagnostics later)."""
    arr = _gray_array(png_path)
    return {"mean": float(arr.mean()), "stddev": float(arr.std())}


def frame_delta(png_a: Path, png_b: Path) -> float:
    """Mean grayscale difference between two frames - B6 check 3's signal."""
    a, b = _gray_array(png_a), _gray_array(png_b)
    if a.shape != b.shape:
        raise MotionError(f"frame sizes differ, cannot compare: {png_a} {a.shape} vs {png_b} {b.shape}")
    return float(numpy.abs(a - b).mean())


def _require_frame(png_path: Path, context: str) -> None:
    """ffmpeg exits 0 even when a frame seek decodes nothing - the empty
    result must be a loud validation failure, not a silent skip."""
    if not png_path.exists() or png_path.stat().st_size == 0:
        raise MotionError(f"no frame extracted ({context}); cannot validate")


def extract_frame(video_path: Path, t_seconds: float, out_png: Path) -> None:
    """Extract one frame at `t_seconds` (absolute timeline) as a PNG via
    ffmpeg. `-ss` input seeking decodes from the nearest keyframe and
    discards, which lands frame-accurately at `t_seconds`."""
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t_seconds:.4f}",
         "-i", str(video_path), "-frames:v", "1", str(out_png)],
        check=True, capture_output=True,
    )
    _require_frame(out_png, f"t={t_seconds:.3f}s of {video_path}")


def extract_last_frame(video_path: Path, out_png: Path) -> None:
    """The video's final frame - used for slide *end* boundaries. ffprobe's
    reported duration includes the last frame's own display time, so
    seeking at `duration - 1 frame` would land *past* the last frame's PTS
    and decode nothing; `-sseof` grabs whatever the true last frame is
    regardless of rounding."""
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-sseof", "-0.1",
         "-i", str(video_path), "-frames:v", "1", str(out_png)],
        check=True, capture_output=True,
    )
    _require_frame(out_png, f"tail of {video_path}")


def is_blank_frame(stats: dict[str, float], thresholds: dict[str, Any]) -> bool:
    """A frame is "blank" when it's near-uniform (low stddev) AND its mean
    sits at the white or black end. Brand-tinted backgrounds don't trip it:
    the brand's warm off-white page background is documented in
    config/design_system.yaml, well below `blank_white_min_mean`."""
    return (
        stats["stddev"] <= thresholds["blank_max_stddev"]
        and (stats["mean"] >= thresholds["blank_white_min_mean"] or stats["mean"] <= thresholds["blank_black_max_mean"])
    )


def validate_motion(
    *,
    silent_video: Path,
    final_video: Path,
    ctx: MotionRenderContext,
    work_dir: Path,
    engine_errors: list[str] | None = None,
) -> dict[str, Any]:
    """Run B6 checks 1-4 against one rendered motion video and return the
    motion.json `validation` block. `ok is False` means the render must
    fail - the caller raises with this dict's errors, and `motion.json` is
    written first so the failure state is inspectable."""
    thresholds = {**{
        "blank_max_stddev": 6.0,
        "blank_white_min_mean": 244.0,
        "blank_black_max_mean": 12.0,
        "animation_min_mean_delta": 1.5,
    }, **(ctx.motion_config.get("validation", {}) or {})}
    one_frame = 1.0 / ctx.fps
    frames_dir = work_dir / "validation_frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    errors: list[str] = []
    warnings: list[str] = []

    # --- 1. duration -------------------------------------------------------
    silent_actual = ffprobe_duration(str(silent_video))
    final_actual = ffprobe_duration(str(final_video))
    expected = ctx.total_duration
    silent_drift = abs(silent_actual - expected)
    final_drift = abs(final_actual - expected)
    duration_ok = silent_drift <= one_frame
    if not duration_ok:
        errors.append(
            f"silent video duration {silent_actual:.3f}s differs from segment_timing's total "
            f"{expected:.3f}s by more than one frame ({silent_drift:.4f}s > {one_frame:.4f}s)"
        )
    if final_drift > ctx.max_duration_drift_seconds:
        # Same tolerance as slideshow.mp4's sync.max_duration_drift_seconds
        # (video.yaml: covers rounding/encoding drift only).
        errors.append(
            f"final video duration {final_actual:.3f}s drifted from {expected:.3f}s by "
            f"{final_drift:.3f}s > sync.max_duration_drift_seconds={ctx.max_duration_drift_seconds}"
        )

    # --- 2. no blank frames at boundaries (on the silent video) ------------
    boundary_checks: list[dict[str, Any]] = []
    for slide in ctx.slides:
        png = frames_dir / f"boundary_{slide.slide_id}_start.png"
        extract_frame(silent_video, slide.start + one_frame, png)
        stats = frame_stats(png)
        blank = is_blank_frame(stats, thresholds)
        record = {"slide_id": slide.slide_id, "boundary": "start",
                  "at_seconds": round(slide.start + one_frame, 4), **stats}
        if blank:
            record["ok"] = False
        else:
            record["ok"] = True
        boundary_checks.append(record)
        if blank:
            errors.append(
                f"blank {stats['mean']:.0f}-mean/({stats['stddev']:.1f}-stddev) frame at slide "
                f"'{slide.slide_id}''s start boundary (t={slide.start + one_frame:.3f}s) - the "
                "flash-bug regression classes from the earlier plan"
            )
        png = frames_dir / f"boundary_{slide.slide_id}_end.png"
        extract_last_frame(silent_video, png)
        stats = frame_stats(png)
        blank = is_blank_frame(stats, thresholds)
        record = {"slide_id": slide.slide_id, "boundary": "end",
                  "at_seconds": round(slide.end, 4), "extracted_from_tail": True, **stats}
        record["ok"] = not blank
        boundary_checks.append(record)
        if blank:
            errors.append(
                f"blank frame at slide '{slide.slide_id}''s end boundary (tail of its segment) - the "
                "flash-bug regression classes from the earlier plan"
            )

    # --- 3. animation actually happened (on the silent video) --------------
    animation_checks: list[dict[str, Any]] = []
    entrance_t = lambda s: s.start + one_frame  # noqa: E731
    settle_t = lambda s: s.end - one_frame      # noqa: E731
    for slide in ctx.slides:
        if slide.end - slide.start <= 2 * one_frame:
            warnings.append(
                f"slide '{slide.slide_id}' is shorter than 2 frames; skipping the animation-happened check"
            )
            continue
        entrance = frames_dir / f"animation_in_{slide.slide_id}.png"
        settle = frames_dir / f"animation_out_{slide.slide_id}.png"
        extract_frame(silent_video, entrance_t(slide), entrance)
        extract_last_frame(silent_video, settle)
        delta = frame_delta(entrance, settle)
        record = {"slide_id": slide.slide_id, "entrance_delta": delta}
        if delta < thresholds["animation_min_mean_delta"]:
            record["ok"] = False
            animation_checks.append(record)
            errors.append(
                f"slide '{slide.slide_id}' looks identical at its entrance and settle frames "
                f"(mean delta {delta:.2f} < {thresholds['animation_min_mean_delta']}) - the slide's "
                "animation never visibly happened (e.g. every template step resolved to nothing)"
            )
        else:
            record["ok"] = True
            animation_checks.append(record)

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "duration": {
            "expected_seconds": round(expected, 4),
            "silent_actual_seconds": round(silent_actual, 4),
            "final_actual_seconds": round(final_actual, 4),
            "silent_drift_seconds": round(silent_drift, 4),
            "final_drift_seconds": round(final_drift, 4),
            "one_frame_seconds": round(one_frame, 4),
            "ok": duration_ok,
        },
        "boundary_checks": boundary_checks,
        "animation_checks": animation_checks,
        "engine_errors": list(engine_errors or []),
    }