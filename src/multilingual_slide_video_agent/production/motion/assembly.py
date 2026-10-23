"""Exact-frame timing and segment assembly shared by the motion path.

`segment_frame_counts` is how every engine places slide boundaries: whole
frames rounded from the absolute timeline, so each slide starts on the frame
nearest its narration-driven start and rounding never accumulates. The
HyperFrames engine uses it for its clip timing; validation relies on the
same boundaries.

`assemble_silent_video` builds an exact-length silent video from per-slide
source videos (or a still image for the title card). It came from the
retired Playwright live-capture engine (2026-10-22); it stays as a generic
utility - the validation tests build their test videos with it, and a future
engine that renders per slide can reuse it.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from multilingual_slide_video_agent.media import ffprobe_duration
from multilingual_slide_video_agent.production.captions import concat_quote
from multilingual_slide_video_agent.production.motion.context import MotionRenderContext
from multilingual_slide_video_agent.production.motion.errors import MotionError


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


def frame_count(path: Path) -> int:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets",
         "-show_entries", "stream=nb_read_packets", "-of", "csv=p=0", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    return int(out.split(",")[0])


def _ffmpeg_encode_args(ctx: MotionRenderContext, frames: int) -> list[str]:
    encode = ctx.motion_config.get("encode", {})
    hold_seconds = frames / ctx.fps + 1.0
    return [
        "-vf", (
            f"scale={ctx.resolution['width']}:{ctx.resolution['height']},"
            f"fps={ctx.fps},"
            # Hold-extend: a source that ends early holds its last frame -
            # an animation's "plays once, then holds its final state" - and
            # `-frames:v` bounds the output to the exact frame count.
            f"tpad=stop_mode=clone:stop_duration={hold_seconds:.3f}"
        ),
        "-frames:v", str(frames),
        "-c:v", "libx264",
        "-preset", str(encode.get("preset", "medium")),
        "-crf", str(encode.get("crf", 19)),
        "-pix_fmt", str(encode.get("pix_fmt", "yuv420p")),
        "-an",
    ]


def _encode_segment(seg: dict[str, Any], dest: Path, ctx: MotionRenderContext) -> None:
    """One segment as a silent CFR video of exactly seg["frames"] frames:
    a still image looped (`kind: title`) or a source video, optionally
    trimmed by `trim_start_seconds`."""
    if seg.get("kind") == "title":
        source = ["-loop", "1", "-i", str(seg["src"])]
    else:
        trim = float(seg.get("trim_start_seconds", 0.0))
        source = [*(["-ss", f"{trim:.3f}"] if trim > 0 else []), "-i", str(seg["src"])]
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", *source, *_ffmpeg_encode_args(ctx, seg["frames"]), str(dest)],
        check=True, capture_output=True,
    )


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

    Each segment dict: {"kind": "title"|"slide", "src": Path, "duration":
    target float, optional "slide_id" and "trim_start_seconds"}."""
    if not segments:
        raise MotionError("no segments to assemble - production.json's timing produced no renderable items")
    seg_dir = work_dir / "segments"
    seg_dir.mkdir(parents=True, exist_ok=True)

    frame_counts = segment_frame_counts([seg["duration"] for seg in segments], ctx.fps)
    built: list[Path] = []
    for i, (seg, frames) in enumerate(zip(segments, frame_counts)):
        enc = seg_dir / f"seg_{i:03d}.mp4"
        _encode_segment({**seg, "frames": frames}, enc, ctx)
        actual = frame_count(enc)
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
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(list_path),
         "-c", "copy", "-movflags", "+faststart", str(dest)],
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
