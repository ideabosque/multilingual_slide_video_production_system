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
2. **No flash frames at boundaries** - each slide's OWN first and last
   frame. A surviving magenta capture sentinel
   always fails; a near-uniform white/black frame fails, naming the slide,
   unless it's a start frame that simply matches the slide's own background
   (a white deck before its elements fade in). Guards both regression
   classes of the flash bugs documented in the earlier plan (intra-slide
   FOUC and the inter-slide blank lead-in). Runs on the *silent* video, so
   cue/burn-in content can't mask a blank background.
3. **Animation actually happened** - each slide's own first and last
   frames must differ by more than a threshold. Catches selectors that
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
    """A frame's grayscale mean/stddev/median - the B6 check-2 inputs. The
    median approximates the slide's background (most pixels are
    background). Exposed for unit tests (and `motion doctor` diagnostics
    later)."""
    arr = _gray_array(png_path)
    median = float(numpy.median(arr))
    return {
        "mean": float(arr.mean()), "stddev": float(arr.std()), "median": median,
        # Share of pixels clearly different from the background (the
        # median): ~0 for an empty frame, well above it for any real text.
        "content_fraction": float((numpy.abs(arr - median) > CONTENT_PIXEL_DELTA).mean()),
    }


# A pixel counts as content when it differs from the frame's background by
# more than this many gray levels (encoder noise stays within a few).
CONTENT_PIXEL_DELTA = 24


def is_sentinel_frame(png_path: Path) -> bool:
    """Whether a frame is the live-capture magenta sentinel
    (slides/render.py's SENTINEL_RGB). Used both to find where captured
    content starts and to fail a render where a sentinel frame survived the
    trim - it would be a visible magenta flash."""
    with Image.open(png_path) as im:
        rgb = numpy.asarray(im.convert("RGB"), dtype=numpy.float32)
    r, g, b = (float(rgb[..., c].mean()) for c in range(3))
    return r >= 200 and b >= 200 and g <= 60


def frame_delta(png_a: Path, png_b: Path) -> float:
    """Mean grayscale difference between two frames - B6 check 3's signal."""
    a, b = _gray_array(png_a), _gray_array(png_b)
    if a.shape != b.shape:
        raise MotionError(f"frame sizes differ, cannot compare: {png_a} {a.shape} vs {png_b} {b.shape}")
    return float(numpy.abs(a - b).mean())


def frame_changed_fraction(png_a: Path, png_b: Path, pixel_delta: float) -> float:
    """Fraction of pixels whose grayscale value differs by more than
    `pixel_delta` between two frames - B6 check 3's signal. Unlike a
    whole-frame mean, this doesn't shrink with how much of the frame the
    animated content covers: a small headline fading in fully is a real
    animation, while encoder noise only moves pixels by a few levels."""
    a, b = _gray_array(png_a), _gray_array(png_b)
    if a.shape != b.shape:
        raise MotionError(f"frame sizes differ, cannot compare: {png_a} {a.shape} vs {png_b} {b.shape}")
    return float((numpy.abs(a - b) > pixel_delta).mean())


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
    """A frame is "blank" when its mean sits at the white or black end AND it
    has (almost) no content. Brand-tinted backgrounds don't trip it: the
    brand's warm off-white page background is documented in
    config/design_system.yaml, well below `blank_white_min_mean`.

    "No content" is a near-zero `content_fraction` when available: a stddev
    threshold alone misreads a white slide with a little small text (stddev
    ~5-7, observed) as empty. Without it, the stddev rule applies."""
    extreme = stats["mean"] >= thresholds["blank_white_min_mean"] or stats["mean"] <= thresholds["blank_black_max_mean"]
    if "content_fraction" in stats:
        return extreme and stats["content_fraction"] < thresholds.get("blank_max_content_fraction", 0.0002)
    return extreme and stats["stddev"] <= thresholds["blank_max_stddev"]


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
        "animation_pixel_delta": 24,
        "animation_min_changed_fraction": 0.0002,
        "background_match_max_delta": 12.0,
        "settle_before_end_seconds": 0.6,
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

    # --- 2 + 3. per-slide boundary frames (on the silent video) -------------
    # Each slide's own first and last frame. Engines cut slides on whole
    # frames rounded from the absolute timeline (round(t * fps), see
    # playwright_engine.segment_frame_counts), so those frame indices are
    # known exactly; `-ss` outputs the first frame at or after the seek
    # point, hence the tiny epsilon below each frame's timestamp. Only the
    # video's very last slide uses -sseof for its end, because seeking that
    # close to the end of the file can decode nothing.
    boundary_checks: list[dict[str, Any]] = []
    animation_checks: list[dict[str, Any]] = []
    last_frame_index = round(ctx.total_duration * ctx.fps) - 1
    epsilon = one_frame / 100
    for slide in ctx.slides:
        start_png = frames_dir / f"boundary_{slide.slide_id}_start.png"
        end_png = frames_dir / f"boundary_{slide.slide_id}_end.png"
        first_frame = round(slide.start * ctx.fps)
        end_frame = round(slide.end * ctx.fps) - 1
        start_at = first_frame / ctx.fps
        end_at = end_frame / ctx.fps
        extract_frame(silent_video, max(0.0, start_at - epsilon), start_png)
        if end_frame >= last_frame_index:
            extract_last_frame(silent_video, end_png)
        else:
            extract_frame(silent_video, end_at - epsilon, end_png)
        # The "settled" frame: the slide with everything in, just before any
        # exit animation (the playful style fades each slide out before its
        # cut, so its literal last frame is legitimately empty).
        settle_frame = end_frame - round(thresholds["settle_before_end_seconds"] * ctx.fps)
        if settle_frame - first_frame >= 2:
            settle_png = frames_dir / f"boundary_{slide.slide_id}_settled.png"
            extract_frame(silent_video, settle_frame / ctx.fps - epsilon, settle_png)
        else:
            settle_frame, settle_png = end_frame, end_png
        start_stats, settle_stats = frame_stats(start_png), frame_stats(settle_png)
        end_stats = frame_stats(end_png)

        # Check 2: a surviving capture sentinel (first or last frame) is
        # always a flash. A blank (near-uniform white/black) START frame is
        # only a flash when it isn't simply the slide's own background with
        # every element still at opacity 0 - on a white deck that is exactly
        # what a correct entrance looks like; the settled frame's median
        # stands in for the background. A blank SETTLED frame means nothing
        # is visible once the slide has played in, which is always wrong.
        start_sentinel, end_sentinel = is_sentinel_frame(start_png), is_sentinel_frame(end_png)
        start_matches_background = (
            abs(start_stats["mean"] - settle_stats["median"]) <= thresholds["background_match_max_delta"]
        )
        start_bad = start_sentinel or (is_blank_frame(start_stats, thresholds) and not start_matches_background)
        settle_blank = is_blank_frame(settle_stats, thresholds)
        end_bad = end_sentinel or settle_blank
        boundary_checks.append({"slide_id": slide.slide_id, "boundary": "start",
                                "at_seconds": round(start_at, 4), "sentinel": start_sentinel,
                                **start_stats, "ok": not start_bad})
        boundary_checks.append({"slide_id": slide.slide_id, "boundary": "end",
                                "at_seconds": round(end_at, 4), "sentinel": end_sentinel,
                                "settled_at_seconds": round(settle_frame / ctx.fps, 4),
                                **settle_stats, "ok": not end_bad})
        for bad, sentinel, stats, where, at in (
            (start_bad, start_sentinel, start_stats, "start", start_at),
            (end_bad, end_sentinel, end_stats if end_sentinel else settle_stats, "end",
             end_at if end_sentinel else settle_frame / ctx.fps),
        ):
            if not bad:
                continue
            kind = "capture-sentinel (magenta)" if sentinel else (
                f"blank {stats['mean']:.0f}-mean/{stats['stddev']:.1f}-stddev"
            )
            errors.append(
                f"{kind} frame at slide '{slide.slide_id}''s {where} boundary (t={at:.3f}s) - the "
                "flash-bug regression classes from the earlier plan"
            )

        # Check 3: the slide's own entrance and settled frames must differ.
        if settle_frame - first_frame < 2:
            warnings.append(
                f"slide '{slide.slide_id}' is shorter than 3 frames; skipping the animation-happened check"
            )
            continue
        changed = frame_changed_fraction(start_png, settle_png, thresholds["animation_pixel_delta"])
        ok = changed >= thresholds["animation_min_changed_fraction"]
        animation_checks.append({
            "slide_id": slide.slide_id, "changed_fraction": round(changed, 6),
            "entrance_delta": frame_delta(start_png, settle_png), "ok": ok,
        })
        if not ok:
            errors.append(
                f"slide '{slide.slide_id}' looks identical at its entrance and settle frames "
                f"({changed:.4%} of pixels changed by more than {thresholds['animation_pixel_delta']} levels, "
                f"< {thresholds['animation_min_changed_fraction']:.4%}) - the slide's animation never "
                "visibly happened (e.g. every template step resolved to nothing)"
            )

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