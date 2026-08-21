"""Animated marketing-video rebuild from an existing production render
(marketing_animation_pipeline_plan §4, replacing the earlier PIL/numpy
procedural renderer entirely - see that plan's §5 Decision 1).

This is intentionally separate from `render_slideshow.py`: the slideshow
renderer preserves the localized deck visuals as static frames, while this
renderer captures the SAME translated deck's GSAP-animated presentation
(slides/generate_animation.py + slides/render.py's
`render_deck_animation_clips`) and assembles it with the narration/captions
this run already produced. It never re-runs TTS or re-decides slide timing
- per plan §5 Decision 0, it stays sequentially dependent on
`render_slideshow.py`'s production.json for narration audio and
`segment_timing`.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from multilingual_slide_video_agent import config as cfg
from multilingual_slide_video_agent.logging_utils import RunLogger
from multilingual_slide_video_agent.media import ffprobe_duration
from multilingual_slide_video_agent.production.render_slideshow import _ass_time, _srt_time
from multilingual_slide_video_agent.slides.render import AnimationCaptureError, render_deck_animation_clips


class MarketingAnimationError(Exception):
    pass


def _load_json(path: str | Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _captions_by_slide_id(localization_path: str | Path | None) -> dict[str, str]:
    if not localization_path:
        return {}
    doc = _load_json(localization_path)
    return {seg["slide_id"]: seg.get("caption", "") for seg in doc.get("segments", [])}


def _write_clip_ass(text: str, duration: float, style: str, profile: dict, video_cfg: dict, resolution: dict, path: Path) -> None:
    """A single-cue ASS file covering [0, duration] - one per captured
    clip, so no absolute-timeline offset math is needed (each clip is
    muxed and captioned independently, then concatenated)."""
    cap_cfg = video_cfg.get("captions", {})
    title_cfg = video_cfg.get("title_card", {})
    font = profile.get("caption_font", "Noto Sans") if profile else "Noto Sans"
    header = (
        "[Script Info]\nScriptType: v4.00+\n"
        f"PlayResX: {resolution['width']}\nPlayResY: {resolution['height']}\n"
        f"WrapStyle: {cap_cfg.get('wrap_style', 0)}\n\n"
        "[V4+ Styles]\n"
        "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,"
        "Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,"
        "Alignment,MarginL,MarginR,MarginV,Encoding\n"
        f"Style: Default,{font},{cap_cfg.get('font_size', 30)},&H00FFFFFF,&H000000FF,&H00000000,"
        f"&HB0000000,0,0,0,0,100,100,0,0,3,1,0,{cap_cfg.get('alignment', 2)},"
        f"{cap_cfg.get('margin_left', 50)},{cap_cfg.get('margin_right', 50)},{cap_cfg.get('margin_vertical', 30)},1\n"
        f"Style: Title,{font},{title_cfg.get('font_size', 56)},&H00FFFFFF,&H000000FF,&H00000000,"
        f"&HB0000000,{1 if title_cfg.get('bold', True) else 0},0,0,0,100,100,0,0,3,1,0,"
        f"{title_cfg.get('alignment', 8)},{cap_cfg.get('margin_left', 50)},{cap_cfg.get('margin_right', 50)},"
        f"{cap_cfg.get('margin_vertical', 30)},1\n\n"
        "[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"
    )
    layer = 1 if style == "Title" else 0
    dialogue = f"Dialogue: {layer},{_ass_time(0.0)},{_ass_time(duration)},{style},,0,0,0,,{text.replace(chr(10), '\\N')}\n"
    path.write_text(header + dialogue, encoding="utf-8")


def _pad_or_trim_audio(src: Path | None, duration: float, dest: Path) -> None:
    """Build exactly `duration` seconds of audio at `dest`: `src` (a
    slide's narration clip) padded with trailing silence if shorter, or
    silence throughout if `src` is None (the title card has no narration)."""
    if src is None:
        cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo:d={duration:.3f}", str(dest)]
    else:
        cmd = [
            "ffmpeg", "-y", "-i", str(src),
            "-af", f"apad=whole_dur={duration:.3f}",
            "-t", f"{duration:.3f}",
            str(dest),
        ]
    subprocess.run(cmd, check=True, capture_output=True)


def _mux_clip(
    video_path: Path, audio_src: Path | None, duration: float, caption_text: str | None,
    style: str, profile: dict, video_cfg: dict, resolution: dict, work_dir: Path, index: int,
) -> Path:
    """One captured (silent) video clip + its own audio + its own caption,
    muxed and re-encoded to a consistent H.264/AAC format so the final
    concat step can rely on every clip matching."""
    audio_path = work_dir / f"_clip{index:03d}_audio.m4a"
    _pad_or_trim_audio(audio_src, duration, audio_path)

    render_cfg = video_cfg.get("render", {})
    video_filter = f"scale={resolution['width']}:{resolution['height']}"
    ass_path = None
    if caption_text and video_cfg.get("captions", {}).get("burn_in", True):
        ass_path = work_dir / f"_clip{index:03d}_captions.ass"
        _write_clip_ass(caption_text, duration, style, profile, video_cfg, resolution, ass_path)
        ass_safe = str(ass_path).replace("\\", "/").replace(":", "\\:")
        video_filter += f",ass='{ass_safe}'"

    dest = work_dir / f"_clip{index:03d}_muxed.mp4"
    cmd = [
        "ffmpeg", "-y", "-i", str(video_path), "-i", str(audio_path),
        "-map", "0:v", "-map", "1:a",
        "-vf", video_filter,
        "-c:v", render_cfg.get("video_codec", "libx264"),
        "-preset", render_cfg.get("preset", "medium"),
        "-crf", str(render_cfg.get("crf", 19)),
        "-pix_fmt", "yuv420p",
        "-c:a", render_cfg.get("audio_codec", "aac"),
        "-b:a", render_cfg.get("audio_bitrate", "192k"),
        "-t", f"{duration:.3f}",
        str(dest),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return dest


def _build_title_clip(
    slides_dir: Path, title: str, duration: float, profile: dict, video_cfg: dict,
    resolution: dict, work_dir: Path,
) -> Path:
    """A static title card (slide 1's rendered image + the Title caption
    style) - not GSAP-animated, matching render_slideshow.py's own title
    card treatment. Reuses the already-rendered slide_001.png from the
    same run's static slideshow render (`--slides-dir`)."""
    slide_one = slides_dir / "slide_001.png"
    if not slide_one.exists():
        raise MarketingAnimationError(f"expected slide_001.png in --slides-dir for the title card: {slide_one}")

    silent_video = work_dir / "_title_silent.mp4"
    render_cfg = video_cfg.get("render", {})
    video_filter = f"scale={resolution['width']}:{resolution['height']}"
    ass_path = work_dir / "_title_captions.ass"
    _write_clip_ass(title, duration, "Title", profile, video_cfg, resolution, ass_path)
    ass_safe = str(ass_path).replace("\\", "/").replace(":", "\\:")
    video_filter += f",ass='{ass_safe}'"

    cmd = [
        "ffmpeg", "-y", "-loop", "1", "-i", str(slide_one), "-t", f"{duration:.3f}",
        "-vf", video_filter,
        "-c:v", render_cfg.get("video_codec", "libx264"),
        "-preset", render_cfg.get("preset", "medium"),
        "-crf", str(render_cfg.get("crf", 19)),
        "-pix_fmt", "yuv420p",
        str(silent_video),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return silent_video


def _concat_clips(clip_paths: list[Path], output: Path) -> None:
    inputs = []
    filter_parts = []
    for i, path in enumerate(clip_paths):
        inputs += ["-i", str(path)]
        filter_parts.append(f"[{i}:v][{i}:a]")
    filter_complex = "".join(filter_parts) + f"concat=n={len(clip_paths)}:v=1:a=1[v][a]"
    cmd = ["ffmpeg", "-y", *inputs, "-filter_complex", filter_complex, "-map", "[v]", "-map", "[a]", str(output)]
    subprocess.run(cmd, check=True, capture_output=True)


def _write_srt_from_timing(timing: list[dict], captions_by_slide_id: dict, title: str | None, path: Path) -> None:
    lines = []
    counter = 1
    for item in timing:
        text = title if item["kind"] == "title" else captions_by_slide_id.get(item.get("slide_id"), "")
        if not text:
            continue
        lines.append(str(counter))
        lines.append(f"{_srt_time(item['start_time'])} --> {_srt_time(item['end_time'])}")
        lines.append(text)
        lines.append("")
        counter += 1
    path.write_text("\n".join(lines), encoding="utf-8")


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
    production_file = Path(production_path).resolve()
    production = _load_json(production_file)

    run_id = production.get("run_id", "unknown-run")
    project_id = production.get("project_id", "unknown-project")
    language = production.get("language", "unknown")
    logger = RunLogger(run_id, project_id)

    timing = production.get("segment_timing") or []
    if not timing:
        raise MarketingAnimationError("production.json has no segment_timing")
    title = production.get("title")

    narration_audio = Path(production.get("narration_audio", "")).resolve()
    if not narration_audio.parent.exists():
        raise MarketingAnimationError(f"narration_audio's directory not found: {narration_audio.parent}")
    seg_audio_dir = narration_audio.parent / "segments"

    slides_path = Path(slides_dir).resolve()
    out_dir = Path(output_dir).resolve() if output_dir else production_file.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    work_dir = out_dir / "_marketing_animation_work"
    work_dir.mkdir(parents=True, exist_ok=True)

    video_cfg = cfg.video_config()
    profile = cfg.language_profile(language)
    resolution_name = os.getenv("VIDEO_RESOLUTION", "1080p")
    resolution = video_cfg.get("resolutions", {}).get(resolution_name, {"width": 1920, "height": 1080})

    captions_by_slide_id = _captions_by_slide_id(localization_path)

    slide_items = [item for item in timing if item.get("kind") == "slide"]
    title_item = next((item for item in timing if item.get("kind") == "title"), None)
    durations_by_slide_id = {item["slide_id"]: item["end_time"] - item["start_time"] for item in slide_items}

    t0 = time.time()
    try:
        capture_manifest = render_deck_animation_clips(
            translated_deck_dir=translated_deck_dir,
            animation_dir=animation_dir,
            out_dir=str(work_dir / "clips"),
            durations_by_slide_id=durations_by_slide_id,
            viewport=viewport,
        )
    except AnimationCaptureError as e:
        logger.log(agent="slideshow_production_agent", skill="slideshow_video_production",
                   stage="rendering", language=language, event="animation_capture_failed",
                   status="failed", errors=[str(e)])
        raise MarketingAnimationError(str(e)) from e
    clip_by_slide = {c["slide_id"]: Path(c["clip"]) for c in capture_manifest["clips"]}

    muxed_clips: list[Path] = []
    clip_index = 0
    if title_item and title:
        title_duration = title_item["end_time"] - title_item["start_time"]
        title_video = _build_title_clip(slides_path, title, title_duration, profile, video_cfg, resolution, work_dir)
        title_audio = work_dir / "_title_audio.m4a"
        _pad_or_trim_audio(None, title_duration, title_audio)
        title_mux_cmd_dest = work_dir / f"_clip{clip_index:03d}_titlecard.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(title_video), "-i", str(title_audio),
             "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-t", f"{title_duration:.3f}",
             str(title_mux_cmd_dest)],
            check=True, capture_output=True,
        )
        muxed_clips.append(title_mux_cmd_dest)
        clip_index += 1

    for item in slide_items:
        slide_id = item["slide_id"]
        duration = item["end_time"] - item["start_time"]
        video_path = clip_by_slide.get(slide_id)
        if video_path is None:
            raise MarketingAnimationError(f"no captured animation clip for slide '{slide_id}'")
        audio_src = seg_audio_dir / f"{slide_id}.mp3"
        muxed = _mux_clip(
            video_path, audio_src if audio_src.exists() else None, duration,
            captions_by_slide_id.get(slide_id), "Default", profile, video_cfg, resolution, work_dir, clip_index,
        )
        muxed_clips.append(muxed)
        clip_index += 1

    output_video = out_dir / output_name
    _concat_clips(muxed_clips, output_video)

    srt_path = out_dir / "marketing_animation_captions.srt"
    _write_srt_from_timing(timing, captions_by_slide_id, title, srt_path)

    shutil.rmtree(work_dir, ignore_errors=True)

    out_duration = ffprobe_duration(str(output_video))
    total_duration = timing[-1]["end_time"] if timing else 0.0

    result = {
        "run_id": run_id,
        "project_id": project_id,
        "language": language,
        "source_production": str(production_file),
        "narration_audio": str(narration_audio),
        "captions": str(srt_path),
        "output_video": str(output_video),
        "style": "gsap_animated",
        "resolution": resolution,
        "duration_seconds": out_duration,
        "total_duration_seconds": round(total_duration, 3),
        "slides": [item["slide_id"] for item in slide_items],
        "templates": {s["slide_id"]: s["template"] for s in _load_json(Path(animation_dir) / "spec.json")["slides"]},
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    manifest_path = out_dir / "marketing_animation.json"
    manifest_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    envelope = logger.status_envelope(
        agent="slideshow_production_agent", language=language, status="completed",
        outputs=result, warnings=[],
    )
    logger.log(
        agent="slideshow_production_agent", skill="slideshow_video_production",
        stage="rendering", language=language, event="marketing_animation_completed", status="completed",
        duration_seconds=time.time() - t0,
        artifacts=[str(output_video), str(manifest_path)],
    )
    return envelope
