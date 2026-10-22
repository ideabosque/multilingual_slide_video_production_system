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

Exact length: each segment is encoded to an exact whole number of frames at
`ctx.fps` (CFR - the ASS burn-in filter requires CFR output, see
config/video.yaml's fps note), with boundaries rounded from the absolute
timeline (`segment_frame_counts`), so every slide starts on the frame
nearest its narration-driven start and the assembled silent video's
duration equals `ctx.total_duration` within one frame (B6 check 1), which
the assembler verifies loudly. (Encoding by seconds instead let a segment
come out a frame short or long depending on how the 25fps webm's frames
lined up, shifting slide boundaries by a frame at random.)
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


# How far past the wall-clock lead-in the sentinel search looks. The webm
# timeline is never longer than wall-clock (sparse static frames only ever
# compress it), so lead-in + this margin always covers the transition.
_LEAD_PROBE_MARGIN_SECONDS = 2.0
_LEAD_PROBE_WIDTH = 160


def _detect_content_lead(webm: Path, ctx: MotionRenderContext, wall_clock_lead: float) -> float | None:
    """Find where the slide's content starts ON THE WEBM'S OWN TIMELINE.

    Live capture shows a solid magenta sentinel (slides/render.py,
    CAPTURE_SENTINEL_MS) between `about:blank` and the revealed page, and
    the timeline only starts playing when the sentinel goes away. Content
    therefore starts at the first sampled frame after a sentinel frame that
    isn't a sentinel itself. Keying on the sentinel - rather than on "first
    non-blank frame" - works whatever the deck's background is: on a white
    deck the first content frames (everything still at opacity 0) look
    exactly like `about:blank`, so a blank-frame heuristic trimmed into the
    entrance animation.

    Only the first `wall_clock_lead + margin` seconds are decoded, at
    `ctx.fps`, downscaled - the transition is always in there, and decoding
    the whole clip at full resolution was wasted work.

    Returns the trim position: the first content sample's time. The fps
    filter samples the input frame *nearest* each output time, so the
    sentinel frame before that content frame always has an earlier
    timestamp, and an accurate `-ss` (which drops frames before the seek
    point) can never start the segment on a sentinel frame. Trimming any
    later only throws away entrance animation, of which live screencast
    capture already records few frames.

    When no sentinel frame was recorded at all, returns 0.0 (trim nothing):
    the screencast only started after the reveal, so the webm already
    begins on content and there is no lead-in to remove - trimming the
    wall-clock lead-in there cut off the entrance animation (observed).
    None only when the probe itself failed; the caller then falls back to
    the wall-clock lead-in, and validation's sentinel check has the final
    word either way."""
    from multilingual_slide_video_agent.production.motion import validate as mv

    probe_dir = webm.parent / f"_lead_probe_{webm.stem}"
    window = wall_clock_lead + _LEAD_PROBE_MARGIN_SECONDS
    try:
        probe_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-t", f"{window:.3f}", "-i", str(webm),
             "-vf", f"fps={ctx.fps},scale={_LEAD_PROBE_WIDTH}:-2", str(probe_dir / "f_%05d.png")],
            check=True, capture_output=True,
        )
        seen_sentinel = False
        for i, png in enumerate(sorted(probe_dir.glob("f_*.png"))):
            if mv.is_sentinel_frame(png):
                seen_sentinel = True
            elif seen_sentinel:
                return i / ctx.fps
        return None if seen_sentinel else 0.0
    except Exception:  # noqa: BLE001 - fall back to wall-clock on any probe failure
        return None
    finally:
        shutil.rmtree(probe_dir, ignore_errors=True)


def _ffmpeg_encode_args(ctx: MotionRenderContext, frames: int) -> list[str]:
    encode = ctx.motion_config.get("encode", {})
    hold_seconds = frames / ctx.fps + 1.0
    return [
        "-vf", (
            f"scale={ctx.resolution['width']}:{ctx.resolution['height']},"
            f"fps={ctx.fps},"
            # Hold-extend: Playwright's recorded webm timeline is not
            # guaranteed wall-clock (sparse static content compresses it),
            # so a segment's input can exhaust before its narration-driven
            # target length. Cloning the last frame is exactly the
            # runtime's own visual semantics - "plays once, then holds its
            # final state" (gsap_animation_authoring SKILL.md). The pad
            # covers the whole segment, so even an input that ends right
            # after the trim still fills it; `-frames:v` bounds the output.
            f"tpad=stop_mode=clone:stop_duration={hold_seconds:.3f}"
        ),
        "-frames:v", str(frames),
        "-c:v", "libx264",
        "-preset", str(encode.get("preset", "medium")),
        "-crf", str(encode.get("crf", 19)),
        "-pix_fmt", str(encode.get("pix_fmt", "yuv420p")),
        "-an",
    ]


def _encode_captured_clip_segment(
    *, src: Path, dest: Path, frames: int, ctx: MotionRenderContext, lead_in: float
) -> None:
    """One slide's captured clip as a silent CFR segment of exactly
    `frames` frames. `-ss` before `-i` seeks the video stream only,
    trimming the lead-in off the front."""
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        *(["-ss", f"{lead_in:.3f}"] if lead_in > 0 else []),
        "-i", str(src),
        *_ffmpeg_encode_args(ctx, frames),
        str(dest),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def _encode_title_card_segment(
    *, slide_one: Path, dest: Path, frames: int, ctx: MotionRenderContext
) -> None:
    """A static title-card segment from slide 1's rendered image - not
    GSAP-animated, matching render_slideshow.py's own title card treatment.
    (`-loop 1` makes the single PNG an infinite stream that `-frames:v`
    bounds.)"""
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-loop", "1", "-i", str(slide_one),
        *_ffmpeg_encode_args(ctx, frames),
        str(dest),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def _encode_segment(seg: dict[str, Any], dest: Path, ctx: MotionRenderContext) -> None:
    if seg.get("kind") == "title":
        _encode_title_card_segment(slide_one=seg["src"], dest=dest, frames=seg["frames"], ctx=ctx)
    else:
        _encode_captured_clip_segment(
            src=seg["src"], dest=dest, frames=seg["frames"], ctx=ctx,
            lead_in=seg.get("video_lead_in_seconds", 0.0),
        )


def _frame_count(path: Path) -> int:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets",
         "-show_entries", "stream=nb_read_packets", "-of", "csv=p=0", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    return int(out.split(",")[0])


def segment_frame_counts(durations: list[float], fps: int) -> list[int]:
    """Whole-frame length of each consecutive segment. Boundaries are
    rounded from the absolute timeline (round(t * fps)), not per segment,
    so every slide starts on the frame nearest its narration-driven start
    and rounding never accumulates - the same idea as plan B5's Remotion
    frame rounding."""
    counts = []
    t = 0.0
    for duration in durations:
        start_frame = round(t * fps)
        t += duration
        counts.append(round(t * fps) - start_frame)
    return counts


def assemble_silent_video(
    *, ctx: MotionRenderContext, segments: list[dict[str, Any]], work_dir: Path, dest: Path
) -> Path:
    """Encode each timing item as a silent CFR segment of an exact whole
    number of frames (see `segment_frame_counts`), then concat-copy them
    into one silent video at `dest`. Fails loudly if any segment doesn't
    come out at its frame count - a short segment would otherwise shift
    every later slide's visuals against its narration and captions - or if
    the result drifts from `ctx.total_duration` by more than one frame (B6
    check 1).

    Each segment dict: {"kind": "title"|"slide", "src": Path,
    "duration": target float, "slide_id"/"video_lead_in_seconds" for
    slides}. Segment encoding lives here (not per-caller) so the frame
    rounding can't be duplicated inconsistently."""
    if not segments:
        raise MotionError("no segments to assemble - production.json's timing produced no renderable items")
    seg_dir = work_dir / "segments"
    seg_dir.mkdir(parents=True, exist_ok=True)

    frame_counts = segment_frame_counts([seg["duration"] for seg in segments], ctx.fps)
    built: list[Path] = []
    for i, (seg, frames) in enumerate(zip(segments, frame_counts)):
        enc = seg_dir / f"seg_{i:03d}.mp4"
        _encode_segment({**seg, "frames": frames}, enc, ctx)
        actual = _frame_count(enc)
        if actual != frames:
            label = seg.get("slide_id") or seg.get("kind", f"segment {i}")
            raise MotionError(
                f"segment '{label}' encoded to {actual} frames instead of {frames} - refusing to "
                "shift later slides out of sync with their narration"
            )
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
                animation_style=str(ctx.motion_config.get("animation_style", "calm")),
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
        # Sentinel-based lead-in detection per clip (see
        # _detect_content_lead): the wall-clock `video_lead_in_seconds` is
        # only its search window and fallback, because webm timelines are
        # not wall-clock. This whole trim mechanism is live-capture's own
        # fragility (plan D1) - it exists only in this engine, and the
        # validation pass's sentinel/blank checks have the final word.
        lead_in_by_slide = {}
        for c in capture_manifest["clips"]:
            wall_clock_lead = float(c.get("video_lead_in_seconds", 0.0))
            detected = _detect_content_lead(Path(c["clip"]), ctx, wall_clock_lead)
            lead_in_by_slide[c["slide_id"]] = detected if detected is not None else wall_clock_lead

        segments: list[dict[str, Any]] = []
        for item in ctx.timing:
            duration = item["end_time"] - item["start_time"]
            if item.get("kind") == "title":
                if ctx.slides_dir is None:
                    raise MotionError(
                        "the playwright engine needs --slides-dir (rendered slide PNGs) for its title card"
                    )
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
                    "kind": "slide", "slide_id": item["slide_id"], "src": video_path, "duration": duration,
                    "video_lead_in_seconds": lead_in_by_slide.get(item["slide_id"], 0.0),
                })

        assembly_dir = work_dir / "assembly"
        assembly_dir.mkdir(parents=True, exist_ok=True)
        silent = work_dir / "silent.mp4"
        try:
            assemble_silent_video(ctx=ctx, segments=segments, work_dir=assembly_dir, dest=silent)
        finally:
            shutil.rmtree(assembly_dir, ignore_errors=True)
        return silent