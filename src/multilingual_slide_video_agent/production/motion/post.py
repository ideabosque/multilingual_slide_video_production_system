"""The shared motion post-pass (motion-engines-and-hardening-plan B2):
burn ASS captions and mux the narration onto any engine's silent video.

Why audio and captions are here and NOT inside the engines (B2):
- narration bytes and caption timing stay identical across all three
  engines and with `slideshow.mp4` - only the visual track differs, which
  keeps B6's cross-engine parity checks honest;
- caption burn-in already handles CJK fonts and wrapping (wrap_style: 0)
  through the exact `captions` config render_slideshow.py uses;
- each engine only has to produce an exact-length silent video, the
  easiest contract to verify (B6 check 1).

This was factored out of the earlier monolithic animation renderer, with
one deliberate mechanical change: captions are burned with **absolute** cue times over the
whole concatenated silent video instead of one single-cue ASS file per
clip. The old per-clip cues were each `[0, clip_duration]`; since per-item
cues partition the timeline exactly at the cut points, burning
`[start, end]` cues over the concatenated video is the same visual result
without needing one ASS file per clip.

In-composition (styled/animated) captions are a later option - Open
decision D2 stays deferred.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from multilingual_slide_video_agent.media import ffprobe_duration
from multilingual_slide_video_agent.production.captions import ass_escape
from multilingual_slide_video_agent.production.motion.context import MotionRenderContext
from multilingual_slide_video_agent.production.motion.errors import MotionError
from multilingual_slide_video_agent.production.render_slideshow import _ass_time, _srt_time


class MotionPostError(MotionError):
    pass


def _load_json(path: str | Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def captions_by_slide_id(localization_path: str | Path | None) -> dict[str, str]:
    if not localization_path:
        return {}
    doc = _load_json(localization_path)
    return {seg["slide_id"]: seg.get("caption", "") for seg in doc.get("segments", [])}


def _ass_header(caption_cfg: dict[str, Any]) -> str:
    """The ASS style header - the exact styles the previous renderer wrote
    per clip (Default for slide captions, Title for the title card), now
    emitted once per video with absolute cue times."""
    return (
        "[Script Info]\nScriptType: v4.00+\n"
        f"PlayResX: {caption_cfg['resolution']['width']}\nPlayResY: {caption_cfg['resolution']['height']}\n"
        f"WrapStyle: {caption_cfg.get('wrap_style', 0)}\n\n"
        "[V4+ Styles]\n"
        "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,"
        "Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,"
        "Alignment,MarginL,MarginR,MarginV,Encoding\n"
        f"Style: Default,{caption_cfg['font']},{caption_cfg.get('font_size', 30)},&H00FFFFFF,&H000000FF,&H00000000,"
        f"&HB0000000,0,0,0,0,100,100,0,0,3,1,0,{caption_cfg.get('alignment', 2)},"
        f"{caption_cfg.get('margin_left', 50)},{caption_cfg.get('margin_right', 50)},{caption_cfg.get('margin_vertical', 30)},1\n"
        f"Style: Title,{caption_cfg['font']},{caption_cfg.get('title_font_size', 56)},&H00FFFFFF,&H000000FF,&H00000000,"
        f"&HB0000000,{1 if caption_cfg.get('title_bold', True) else 0},0,0,0,100,100,0,0,3,1,0,"
        f"{caption_cfg.get('title_alignment', 8)},{caption_cfg.get('margin_left', 50)},{caption_cfg.get('margin_right', 50)},"
        f"{caption_cfg.get('margin_vertical', 30)},1\n\n"
        "[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"
    )


def build_cues(
    ctx: MotionRenderContext, captions_by_slide_id: dict[str, str]
) -> list[tuple[float, float, str, str]]:
    """The whole video's (layer, start, end, style, text) caption cues - one
    per timing item with non-empty text. Matches the previous renderer's
    behavior: a slide with no caption text gets no cue (nothing burned),
    and the title card gets the Title style."""
    cues: list[tuple[int, float, float, str, str]] = []
    for item in ctx.timing:
        if item.get("kind") == "title":
            text = ctx.title or ""
            style = "Title"
            layer = 1
        else:
            text = captions_by_slide_id.get(item.get("slide_id"), "")
            style = "Default"
            layer = 0
        if not text:
            continue
        cues.append((layer, item["start_time"], item["end_time"], style, text))
    return cues


def _cue_line(cue: tuple[int, float, float, str, str]) -> str:
    layer, start, end, style, text = cue
    return f"Dialogue: {layer},{_ass_time(start)},{_ass_time(end)},{style},,0,0,0,,{ass_escape(text)}\n"


def write_ass_from_timing(
    ctx: MotionRenderContext, captions_by_slide_id: dict[str, str], path: Path
) -> list[tuple[float, float, str, str]]:
    """Write the whole-video ASS caption file; returns the cues it contains
    (empty text items are skipped, matching the previous per-clip behavior)."""
    profile = _profile(ctx)
    cap_cfg = ctx.video_config.get("captions", {})
    title_cfg = ctx.video_config.get("title_card", {})
    header_cfg = {
        "resolution": ctx.resolution,
        "wrap_style": cap_cfg.get("wrap_style", 0),
        "font": profile.get("caption_font", "Noto Sans"),
        "font_size": cap_cfg.get("font_size", 30),
        "margin_left": cap_cfg.get("margin_left", 50),
        "margin_right": cap_cfg.get("margin_right", 50),
        "margin_vertical": cap_cfg.get("margin_vertical", 30),
        "alignment": cap_cfg.get("alignment", 2),
        "title_font_size": title_cfg.get("font_size", 56),
        "title_bold": title_cfg.get("bold", True),
        "title_alignment": title_cfg.get("alignment", 8),
    }
    cues = build_cues(ctx, captions_by_slide_id)
    content = _ass_header(header_cfg) + "".join(_cue_line(c) for c in cues)
    path.write_text(content, encoding="utf-8")
    return cues


def write_srt_from_timing(
    ctx: MotionRenderContext, captions_by_slide_id: dict[str, str], path: Path
) -> int:
    lines = []
    counter = 1
    for item in ctx.timing:
        text = ctx.title if item["kind"] == "title" else captions_by_slide_id.get(item.get("slide_id"), "")
        if not text:
            continue
        lines.append(str(counter))
        lines.append(f"{_srt_time(item['start_time'])} --> {_srt_time(item['end_time'])}")
        lines.append(text)
        lines.append("")
        counter += 1
    path.write_text("\n".join(lines), encoding="utf-8")
    return counter - 1


def _profile(ctx: MotionRenderContext) -> dict[str, Any]:
    from multilingual_slide_video_agent import config as cfg

    try:
        return cfg.language_profile(ctx.language)
    except ValueError:
        return {}


def _pad_or_trim_to_wav(src: Path | None, duration: float, dest: Path) -> None:
    """Build exactly `duration` seconds of audio at `dest` as 44.1kHz stereo
    PCM WAV: `src` (a slide's narration clip) padded with trailing silence
    if shorter, or silence throughout if `src` is None (the title card has
    no narration; a missing segment mp3 falls back to silence - the same
    fallback the previous renderer had).

    Normalizing every item to the same rate/channels here is what makes the
    concat filter's inputs match deterministically, whatever the TTS source
    clips' own formats are."""
    if src is None:
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
             f"anullsrc=r=44100:cl=stereo:d={duration:.3f}", str(dest)],
            check=True, capture_output=True,
        )
    else:
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-af", f"apad=whole_dur={duration:.3f}",
             "-t", f"{duration:.3f}", "-ar", "44100", "-ac", "2", str(dest)],
            check=True, capture_output=True,
        )


def build_narration_track(ctx: MotionRenderContext, work_dir: Path) -> Path:
    """Concatenate every timing item's (padded/trimmed) narration clip into
    one full-length silence-padded track, in `segment_timing` order. Only
    the title card is silent.

    A slide whose narration clip is missing fails the render, naming the
    slide and where it looked. The previous renderer substituted silence,
    which once produced a complete-looking video with no sound at all
    (narrate had used an --audio-dir the render didn't know about)."""
    track_dir = work_dir / "narration"
    track_dir.mkdir(parents=True, exist_ok=True)
    missing = [
        item["slide_id"] for item in ctx.timing
        if item.get("kind") == "slide" and not (ctx.segment_audio_dir / f"{item['slide_id']}.mp3").exists()
    ]
    if missing:
        raise MotionPostError(
            f"narration clip(s) missing for slide(s) {missing} in {ctx.segment_audio_dir} - "
            "refusing to render a video with silent slides"
        )
    parts: list[Path] = []
    for i, item in enumerate(ctx.timing):
        duration = item["end_time"] - item["start_time"]
        part = track_dir / f"_track_{i:03d}.wav"
        src = ctx.segment_audio_dir / f"{item['slide_id']}.mp3" if item.get("kind") == "slide" else None
        _pad_or_trim_to_wav(src, duration, part)
        parts.append(part)

    inputs: list[str] = []
    for part in parts:
        inputs += ["-i", str(part)]
    filter_complex = "".join(f"[{i}:a]" for i in range(len(parts))) + f"concat=n={len(parts)}:v=0:a=1[aout]"
    track = track_dir / "narration_for_mux.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", filter_complex,
         "-map", "[aout]", "-ar", "44100", "-ac", "2", str(track)],
        check=True, capture_output=True,
    )
    return track


def burn_and_mux(
    silent_video: Path,
    ctx: MotionRenderContext,
    work_dir: Path,
    captions_by_slide_id: dict[str, str],
    out_video: Path,
) -> dict[str, Any]:
    """Burn the whole-video ASS captions onto the engine's silent video and
    mux `build_narration_track`'s narration onto it - the B2 shared
    post-pass. Single final encode; `silent_video`'s exact length is
    preserved by the burn/mux (the ASS filter doesn't alter timing)."""
    burn_cfg = ctx.video_config.get("captions", {})
    burn_in = burn_cfg.get("burn_in", True)
    cues = build_cues(ctx, captions_by_slide_id)

    narration = build_narration_track(ctx, work_dir)

    audio_codec = ctx.video_config.get("render", {}).get("audio_codec", "aac")
    audio_bitrate = ctx.video_config.get("render", {}).get("audio_bitrate", "192k")

    cmd: list[str] = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(silent_video), "-i", str(narration)]
    if burn_in and cues:
        # Burning needs a re-encode (same settings the engine's segments
        # used, so the final encode is the video's second generation - no
        # more than the previous monolithic renderer's own concat step).
        ass_path = work_dir / "captions_full.ass"
        write_ass_from_timing(ctx, captions_by_slide_id, ass_path)
        ass_safe = str(ass_path).replace("\\", "/").replace(":", "\\:")
        encode = ctx.motion_config.get("encode", {})
        cmd += [
            "-vf", f"ass='{ass_safe}'",
            "-c:v", "libx264",
            "-preset", str(encode.get("preset", "medium")),
            "-crf", str(encode.get("crf", 19)),
            "-pix_fmt", str(encode.get("pix_fmt", "yuv420p")),
        ]
    else:
        # Nothing to burn (captions off, or no non-empty cues): keep the
        # engine's silent video bytes untouched.
        cmd += ["-c:v", "copy"]
    cmd += [
        "-map", "0:v",
        "-map", "1:a",
        "-c:a", audio_codec,
        "-b:a", audio_bitrate,
        "-ar", "44100",
        "-ac", "2",
        "-movflags", "+faststart",
        str(out_video),
    ]
    subprocess.run(cmd, check=True, capture_output=True)

    srt_path = out_video.with_name(f"{out_video.stem}_captions.srt")
    cue_count = write_srt_from_timing(ctx, captions_by_slide_id, srt_path)

    return {
        "captions_srt": str(srt_path),
        "srt_cue_count": cue_count,
        "burn_in": bool(burn_in and cues),
        "final_duration_seconds": ffprobe_duration(str(out_video)),
    }