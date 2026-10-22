"""The `playwright` engine (motion-engines-and-hardening-plan B2, the
reference engine): wraps today's wall-clock capture
(slides/render.py's `render_deck_animation_clips`, unchanged) and assembles
the exact-length silent video the shared post-pass expects.

What deliberately survives here, because it exists only because live
recording isn't frame-addressable (plan B4):
- the per-slide `video_lead_in_seconds` measurement and trim - the
  `about:blank`/not-yet-revealed frames Playwright records before the page
  appears;
- GSAP timelines built live (default `__MOTION_MODE__`) whose play/hold
  rhythm is narration-driven per slide.

The lead-in trim is applied here, inside the engine, on the way to the
silent video - it used to happen inside `_mux_clip` in the old monolithic
`render_marketing_animation.py`, alongside the caption/audio muxing that
now belongs to post.py.

Exact length: each segment is encoded to whole frames at `ctx.fps` (CFR -
the ASS burn-in filter requires CFR output, see config/video.yaml's fps
note). Timing durations are rounded to whole frames with the rounding
remainder carried forward into the next segment's target - the same
convention plan B5 documents for Remotion's frame rounding ("carrying the
remainder forward so cumulative drift stays under one frame") - so the
assembled silent video's duration equals `ctx.total_duration` within one
frame (B6 check 1), which the assembler verifies loudly.
"""
from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from multilingual_slide_video_agent.logging_utils import RunLogger
from multilingual_slide_video_agent.media import ffprobe_duration
from multilingual_slide_video_agent.production.motion.context import MotionRenderContext
from multilingual_slide_video_agent.production.motion.errors import MotionError
from multilingual_slide_video_agent.production.captions import concat_quote


def check_available() -> list[str]:
    """Playwright + its Chromium binaries (`msv motion doctor` prints this;
    an empty list means ready). Never raises."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return ["playwright package not installed (pip install playwright)"]
    try:
        with sync_playwright() as p:
            exe = Path(p.chromium.executable_path)
    except Exception as e:  # noqa: BLE001 - doctor/availability checks must never raise
        return [f"playwright chromium unavailable: {e}"]
    if not exe.exists():
        return [f"playwright chromium binaries not found at {exe} (run: playwright install chromium)"]
    return []


def _detect_content_lead(webm: Path, ctx: MotionRenderContext) -> float | None:
    """Find the captured clip's content start ON ITS OWN TIMELINE.

    Playwright's raw webm recording is not guaranteed wall-clock (sparse
    static lead content compresses the timeline), so the wall-clock
    lead-in measurement used by the previous monolithic renderer can
    undertrim - white `about:blank`/hidden-page frames surviving into the
    segment, or the trim cutting into settled content. Instead, sample
    the webm on a 10fps PNG strip with ONE ffmpeg pass (frame-indexed,
    no seeking - screencast webms are sparse-keyframe and seek
    unreliably) and take the first sample whose frame is non-blank
    (B6's white/black pair) or *changes* against the previous sample.
    Returns the trim position (half a frame before that sample, so `-ss`
    decodes onto it), or None when nothing but blank was sampled (caller
    falls back to the wall-clock measure; validation has the last word)."""
    from multilingual_slide_video_agent.production.motion import validate as mv

    sample_fps = 10
    probe_dir = webm.parent / "_lead_probe"
    try:
        probe_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(webm),
             "-vf", f"fps={sample_fps}", str(probe_dir / "f_%04d.png")],
            check=True, capture_output=True,
        )
    except Exception:  # noqa: BLE001 - fall back to wall-clock on any probe failure
        return None
    blanks = {"blank_max_stddev": 6.0, "blank_white_min_mean": 244.0, "blank_black_max_mean": 12.0}
    prev_png = None
    try:
        for i, png in enumerate(sorted(probe_dir.glob("f_*.png"))):
            is_content = not mv.is_blank_frame(mv.frame_stats(png), blanks)
            if not is_content and prev_png is not None and mv.frame_delta(prev_png, png) > 0.8:
                is_content = True
            if is_content:
                timeline_t = i / sample_fps
                return max(0.0, timeline_t - (0.5 / ctx.fps))
            prev_png = png
        return None
    except Exception:  # noqa: BLE001
        return None
    finally:
        shutil.rmtree(probe_dir, ignore_errors=True)


def _ffmpeg_encode_args(ctx: MotionRenderContext) -> list[str]:
    encode = ctx.motion_config.get("encode", {})
    return [
        "-vf", (
            f"scale={ctx.resolution['width']}:{ctx.resolution['height']},"
            f"fps={ctx.fps},"
            # Hold-extend: Playwright's recorded webm timeline is not
            # guaranteed wall-clock (sparse static content compresses it),
            # so a segment's input can exhaust before its narration-driven
            # target duration. Cloning the last frame is exactly the
            # runtime's own visual semantics - "plays once, then holds its
            # final state" (gsap_animation_authoring SKILL.md) - and lets
            # `-t` keep every segment exactly target-long. 5s headroom;
            # `-t` always bounds the output.
            "tpad=stop_mode=clone:stop_duration=5"
        ),
        "-c:v", "libx264",
        "-preset", str(encode.get("preset", "medium")),
        "-crf", str(encode.get("crf", 19)),
        "-pix_fmt", str(encode.get("pix_fmt", "yuv420p")),
        "-an",
    ]


def _encode_captured_clip_segment(
    *, src: Path, dest: Path, duration: float, ctx: MotionRenderContext, lead_in: float
) -> None:
    """One slide's captured clip as a silent CFR segment, target `duration`
    seconds. `-ss` before `-i` seeks the video stream only, trimming the
    measured blank lead-in off the front."""
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        *(["-ss", f"{lead_in:.3f}"] if lead_in > 0 else []),
        "-i", str(src),
        "-t", f"{duration:.3f}",
        *_ffmpeg_encode_args(ctx),
        str(dest),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def _encode_title_card_segment(
    *, slide_one: Path, dest: Path, duration: float, ctx: MotionRenderContext
) -> None:
    """A static title-card segment from slide 1's rendered image - not
    GSAP-animated, matching render_slideshow.py's own title card treatment.
    (`-loop 1` makes the single PNG an infinite stream that `-t` bounds.)"""
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-loop", "1", "-i", str(slide_one),
        "-t", f"{duration:.3f}",
        *_ffmpeg_encode_args(ctx),
        str(dest),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def _encode_segment(seg: dict[str, Any], dest: Path, ctx: MotionRenderContext) -> None:
    if seg.get("kind") == "title":
        _encode_title_card_segment(slide_one=seg["src"], dest=dest, duration=seg["duration"], ctx=ctx)
    else:
        _encode_captured_clip_segment(
            src=seg["src"], dest=dest, duration=seg["duration"], ctx=ctx,
            lead_in=seg.get("video_lead_in_seconds", 0.0),
        )


def assemble_silent_video(
    *, ctx: MotionRenderContext, segments: list[dict[str, Any]], work_dir: Path, dest: Path
) -> Path:
    """Encode each timing item as a silent CFR segment (whole frames at
    ctx.fps), carrying each segment's rounding remainder forward into the
    next segment's target duration, then concat-copying them into one
    exact-length silent video at `dest`. Fails loudly if the result drifts
    from `ctx.total_duration` by more than one frame (B6 check 1).

    Each segment dict: {"kind": "title"|"slide", "src": Path,
    "duration": target float, "video_lead_in_seconds": float, for slides}.
    Segment encoding lives here (not per-caller) so the carry-forward
    rounding can't be duplicated inconsistently."""
    if not segments:
        raise MotionError("no segments to assemble - production.json's timing produced no renderable items")
    seg_dir = work_dir / "segments"
    seg_dir.mkdir(parents=True, exist_ok=True)

    carry = 0.0
    built: list[Path] = []
    for i, seg in enumerate(segments):
        duration = max(0.0, seg["duration"] + carry)
        enc = seg_dir / f"seg_{i:03d}.mp4"
        _encode_segment({**seg, "duration": duration}, enc, ctx)
        carry += duration - ffprobe_duration(str(enc))
        built.append(enc)

    list_path = seg_dir / "concat_list.txt"
    list_path.write_text("".join(f"file {concat_quote(p)}\n" for p in built), encoding="utf-8")
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", str(list_path),
            "-c", "copy", "-movflags", "+faststart",
            str(dest),
        ],
        check=True, capture_output=True,
    )

    actual = ffprobe_duration(str(dest))
    one_frame = 1.0 / ctx.fps
    if abs(actual - ctx.total_duration) > one_frame:
        raise MotionError(
            f"assembled silent video duration {actual:.3f}s differs from segment_timing's total "
            f"{ctx.total_duration:.3f}s by more than one frame ({abs(actual - ctx.total_duration):.4f}s "
            f"> {one_frame:.4f}s)"
        )
    return dest


class PlaywrightEngine:
    """Plays the translated deck's GSAP bundle live and records it
    (wall-clock) - today's behavior, kept working unchanged behind the
    engine seam. This is the reference engine the HyperFrames/Remotion
    engines (Phases 2b/3) must match output-wise."""

    name = "playwright"

    def check_available(self) -> list[str]:
        return check_available()

    def render(self, ctx: MotionRenderContext, work_dir: Path) -> Path:
        from multilingual_slide_video_agent.slides.render import (
            AnimationCaptureError,
            render_deck_animation_clips,
        )

        durations_by_slide_id = {s.slide_id: s.duration for s in ctx.slides}
        t0 = time.time()
        try:
            capture_manifest = render_deck_animation_clips(
                translated_deck_dir=ctx.translated_deck_dir,
                animation_dir=ctx.animation_dir,
                out_dir=str(work_dir / "capture"),
                durations_by_slide_id=durations_by_slide_id,
                viewport=ctx.viewport,
            )
        except AnimationCaptureError as e:
            # Same event name the previous monolithic renderer logged, so
            # log-driven troubleshooting keeps working.
            RunLogger(ctx.run_id, ctx.project_id).log(
                agent="slideshow_production_agent", skill="slideshow_video_production",
                stage="rendering", language=ctx.language, event="animation_capture_failed",
                status="failed", errors=[str(e)],
            )
            raise MotionError(str(e)) from e
        clip_by_slide = {c["slide_id"]: Path(c["clip"]) for c in capture_manifest["clips"]}
        # Content-lead detection per clip (see _detect_content_lead): the
        # wall-clock `video_lead_in_seconds` is only a fallback here,
        # because webm timelines are not wall-clock. This whole trim
        # mechanism is live-capture's own fragility (plan D1) - it exists
        # only in this engine and phase, and the boundary validation below
        # has the final word on whether the trim worked.
        lead_in_by_slide = {}
        for c in capture_manifest["clips"]:
            detected = _detect_content_lead(Path(c["clip"]), ctx)
            lead_in_by_slide[c["slide_id"]] = (
                detected if detected is not None
                else c.get("video_lead_in_seconds", 0.0)
            )

        segments: list[dict[str, Any]] = []
        for item in ctx.timing:
            duration = item["end_time"] - item["start_time"]
            if item.get("kind") == "title":
                slide_one = ctx.slides_dir / "slide_001.png"
                if not slide_one.exists():
                    raise MotionError(
                        f"expected slide_001.png in --slides-dir for the title card: {slide_one}"
                    )
                segments.append({"kind": "title", "src": slide_one, "duration": duration})
            else:
                video_path = clip_by_slide.get(item["slide_id"])
                if video_path is None:
                    raise MotionError(f"no captured animation clip for slide '{item['slide_id']}'")
                segments.append({
                    "kind": "slide", "src": video_path, "duration": duration,
                    "video_lead_in_seconds": lead_in_by_slide.get(item["slide_id"], 0.0),
                })

        assembly_dir = work_dir / "assembly"
        assembly_dir.mkdir(parents=True, exist_ok=True)
        silent = work_dir / "silent.mp4"
        try:
            assemble_silent_video(ctx=ctx, segments=segments, work_dir=assembly_dir, dest=silent)
        finally:
            shutil.rmtree(assembly_dir / "segments", ignore_errors=True)
        shutil.rmtree(assembly_dir, ignore_errors=True)
        return silent