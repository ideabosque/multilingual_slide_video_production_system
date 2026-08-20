"""Agent 2 core engine: assemble one language's rendered slideshow video
from Agent 2's own translated+rendered slide images plus Agent 1's
localization JSON (slideshow_video_production SKILL.md).

Unlike the video-source sibling project, there is no pre-existing footage
or timeline to composite onto, anchor against, or pad - each slide's
on-screen duration is derived entirely from its own narration's length
plus a short fixed pause (see `compute_slide_timeline` and SKILL.md's
"Slide duration is narration-driven"). The pipeline is:

  1. Generate (or reuse) each slide's narration clip via OpenAI TTS and
     measure its real duration.
  2. Lay out a purely sequential timeline: an optional title card first,
     then every slide in order, each held for its own narration length
     plus a pause.
  3. Build a silent, caption-burned-in video by concatenating each
     slide's still image for its computed duration (ffmpeg's image
     concat demuxer), then build a matching audio track (silence for the
     title window and pauses, real narration for each slide) and mux the
     two together.
"""
from __future__ import annotations

import json
import statistics
import subprocess
import time
from pathlib import Path

from multilingual_slide_video_agent import config as cfg
from multilingual_slide_video_agent import schemas
from multilingual_slide_video_agent import terminology
from multilingual_slide_video_agent.logging_utils import RunLogger
from multilingual_slide_video_agent.media import ffprobe_duration
from multilingual_slide_video_agent.state import directory_fingerprint


class ProductionError(Exception):
    pass


def _load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _srt_time(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _ass_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def compute_slide_timeline(
    segments_with_duration: list[tuple[dict, float]],
    *,
    title_duration: float,
    slide_pause_seconds: float,
) -> tuple[list[dict], float]:
    """Lay out the purely sequential slideshow timeline: an optional title
    card, then every slide in order, each held for its own narration
    duration plus `slide_pause_seconds`. Returns (segment_timing, total_duration).
    Unlike the video-source sibling project's `compute_anchored_timeline`,
    there's nothing to anchor against or overrun - this is a plain
    running sum."""
    cursor = 0.0
    timing: list[dict] = []
    if title_duration > 0:
        timing.append({"kind": "title", "start_time": 0.0, "end_time": round(title_duration, 3)})
        cursor = title_duration
    for seg, narration_duration in segments_with_duration:
        slide_duration = narration_duration + slide_pause_seconds
        start = cursor
        end = start + slide_duration
        timing.append(
            {
                "kind": "slide",
                "slide_index": seg["slide_index"],
                "slide_id": seg["slide_id"],
                "start_time": round(start, 3),
                "end_time": round(end, 3),
                "narration_duration": round(narration_duration, 3),
            }
        )
        cursor = end
    return timing, cursor


def _write_srt(timing: list[dict], captions_by_slide_id: dict, title: str | None, path: Path) -> None:
    lines = []
    counter = 1
    for item in timing:
        text = title if item["kind"] == "title" else captions_by_slide_id[item["slide_id"]]
        lines.append(str(counter))
        lines.append(f"{_srt_time(item['start_time'])} --> {_srt_time(item['end_time'])}")
        lines.append(text)
        lines.append("")
        counter += 1
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_ass(
    timing: list[dict],
    captions_by_slide_id: dict,
    title: str | None,
    profile: dict,
    video_cfg: dict,
    resolution: dict,
    path: Path,
) -> None:
    cap_cfg = video_cfg.get("captions", {})
    title_cfg = video_cfg.get("title_card", {})
    font = profile.get("caption_font", "Noto Sans")
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
    lines = [header]
    for item in timing:
        start, end = _ass_time(item["start_time"]), _ass_time(item["end_time"])
        if item["kind"] == "title":
            text = (title or "").replace("\n", "\\N")
            lines.append(f"Dialogue: 1,{start},{end},Title,,0,0,0,,{text}\n")
        else:
            text = captions_by_slide_id[item["slide_id"]].replace("\n", "\\N")
            lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}\n")
    path.write_text("".join(lines), encoding="utf-8")


def _generate_segment_tts(text: str, output: Path, profile: dict, model: str, extra_instructions: str) -> None:
    from openai import OpenAI

    api_key = cfg.require_env("OPENAI_API_KEY")
    client = OpenAI(api_key=api_key)
    instructions = profile.get("tts_instructions", "").strip()
    if extra_instructions:
        instructions = f"{instructions}\n{extra_instructions}".strip()
    with client.audio.speech.with_streaming_response.create(
        model=model, voice=profile.get("voice", "marin"), input=text, instructions=instructions,
    ) as response:
        response.stream_to_file(str(output))


def _write_image_concat_list(items: list[tuple[Path, float]], path: Path) -> None:
    """ffmpeg's concat demuxer for images: `file`/`duration` pairs, plus a
    final repeat of the last file with no duration - a well-known ffmpeg
    quirk where the last `duration` directive is otherwise ignored."""
    lines = []
    for image_path, duration in items:
        lines.append(f"file '{image_path.as_posix()}'")
        lines.append(f"duration {duration:.3f}")
    if items:
        lines.append(f"file '{items[-1][0].as_posix()}'")
    path.write_text("\n".join(lines), encoding="utf-8")


def _build_silent_captioned_video(
    image_items: list[tuple[Path, float]],
    ass_path: Path | None,
    resolution: dict,
    video_cfg: dict,
    output: Path,
) -> None:
    render_cfg = video_cfg.get("render", {})
    concat_list = output.parent / "_slides_concat.txt"
    _write_image_concat_list(image_items, concat_list)

    # Concat demuxer reads one PNG per slide, each held for its `duration`
    # line. When the libass subtitle filter is applied (burn-in), its output
    # timestamps don't align with the concat demuxer's VFR timing, which
    # causes ffmpeg to silently drop frames and produce a truncated video
    # (observed: 14 images -> 10 frames / 202s instead of 345s). Rendering
    # at a constant frame rate fixes this: every slide image is emitted at
    # a fixed fps for its full duration before the subtitle filter runs.
    # Default 5fps — slides are static images with static burned-in
    # captions, nothing animates, so low fps is ~5x smaller/faster with no
    # perceptible loss. See SKILL.md "Burn-in requires CFR".
    fps = render_cfg.get("fps", 5)
    video_filter = f"scale={resolution['width']}:{resolution['height']}"
    if ass_path is not None:
        ass_safe = str(ass_path).replace("\\", "/").replace(":", "\\:")
        video_filter += f",ass='{ass_safe}'"

    # At 5fps with static slide images, H.264 encodes consecutive
    # identical frames as near-zero-bit P/B frames, producing ~20-30kbps
    # video that blurs text. YouTube's re-encoding makes it worse.
    # Fix: force every frame to be a keyframe (-g 1 -bf 0) with CRF
    # quality. Each frame is independently encoded at full quality, so
    # text stays sharp. File size is larger but fine for YouTube upload.
    crf = render_cfg.get("crf", 18)
    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
        "-fps_mode", "cfr", "-r", str(fps), "-pix_fmt", "yuv420p", "-vf", video_filter,
        "-c:v", render_cfg.get("video_codec", "libx264"),
        "-preset", render_cfg.get("preset", "medium"),
        "-crf", str(crf),
        "-g", "1", "-bf", "0",
        str(output),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    subprocess.run(cmd, check=True, capture_output=True)
    concat_list.unlink(missing_ok=True)


def _build_audio_track(items: list[tuple[str, object]], output: Path, sample_rate: int = 44100) -> None:
    """items: list of ("silence", duration_seconds) or ("file", Path)."""
    inputs: list[str] = []
    filter_parts: list[str] = []
    concat_labels: list[str] = []
    file_input_idx = 0
    for i, (kind, value) in enumerate(items):
        if kind == "silence":
            label = f"sil{i}"
            filter_parts.append(f"anullsrc=r={sample_rate}:cl=stereo:d={float(value):.3f}[{label}]")
        else:
            inputs += ["-i", str(value)]
            label = f"a{i}"
            filter_parts.append(f"[{file_input_idx}:a]aformat=sample_rates={sample_rate}:channel_layouts=stereo[{label}]")
            file_input_idx += 1
        concat_labels.append(f"[{label}]")
    filter_parts.append("".join(concat_labels) + f"concat=n={len(concat_labels)}:v=0:a=1[aout]")
    filter_complex = ";".join(filter_parts)
    cmd = ["ffmpeg", "-y", *inputs, "-filter_complex", filter_complex, "-map", "[aout]", str(output)]
    subprocess.run(cmd, check=True, capture_output=True)


def render_language(
    *,
    run_id: str,
    project_id: str,
    language: str,
    source_deck: str,
    slides_dir: str,
    localization_path: str,
    output_dir: str,
    audio_dir: str | None = None,
    burn_in_override: bool | None = None,
) -> dict:
    """Render one language's localized slideshow video. Returns the status
    envelope dict (also written, plus production.json, to output_dir)."""
    logger = RunLogger(run_id, project_id)
    slides_path = Path(slides_dir).resolve()
    if not slides_path.is_dir():
        raise ProductionError(f"Rendered slides directory not found: {slides_path}")

    localization = _load_json(localization_path)
    validation = schemas.validate_localization(localization, language=language)
    if not validation.ok:
        logger.log(agent="slideshow_production_agent", skill="slideshow_video_production",
                   stage="tts", language=language, event="localization_invalid",
                   status="failed", errors=validation.errors)
        raise ProductionError("Localization input failed validation: " + "; ".join(validation.errors))

    profile = cfg.language_profile(language)
    model = cfg.languages_config().get("default_tts", {}).get("model", "gpt-4o-mini-tts")
    video_cfg = cfg.video_config()
    import os

    resolution_name = os.getenv("VIDEO_RESOLUTION", "1080p")
    resolution = video_cfg.get("resolutions", {}).get(resolution_name, {"width": 1920, "height": 1080})

    segments = sorted(localization["segments"], key=lambda s: s["slide_index"])
    title = str(localization.get("title", "")).strip() or None

    term_errors = []
    texts_to_check = [(seg["narration"], "narration", seg) for seg in segments] + [
        (seg["caption"], "caption", seg) for seg in segments
    ]
    if title:
        texts_to_check.append((title, "title", {"slide_id": "title", "terminology": []}))
    for text, label, seg in texts_to_check:
        report = terminology.check_text(
            text, language=language,
            required_preserved_terms=seg.get("terminology", []),
            context=f"slide {seg['slide_id']} {label}",
        )
        if not report.ok:
            term_errors.extend(f"{v.kind}:{v.term} ({v.context})" for v in report.violations)
    if term_errors:
        logger.log(agent="slideshow_production_agent", skill="slideshow_video_production",
                   stage="tts", language=language, event="terminology_check_failed",
                   status="failed", errors=term_errors)
        raise ProductionError("Terminology validation failed: " + "; ".join(term_errors))

    output_path = Path(output_dir).resolve()
    output_path.mkdir(parents=True, exist_ok=True)
    seg_audio_dir = Path(audio_dir).resolve() if audio_dir else output_path / "segments"
    seg_audio_dir.mkdir(parents=True, exist_ok=True)

    pronunciation = terminology.pronunciation_hints()
    extra_instructions = " ".join(f'Pronounce "{term}" as "{hint}".' for term, hint in pronunciation.items())

    t0 = time.time()
    segment_files: list[tuple[dict, Path, float, Path]] = []
    for seg in segments:
        slide_id = seg["slide_id"]
        seg_audio = seg_audio_dir / f"{slide_id}.mp3"
        if not seg_audio.exists():
            _generate_segment_tts(seg["narration"], seg_audio, profile, model, extra_instructions)
        dur = ffprobe_duration(str(seg_audio))
        image_path = slides_path / f"{slide_id}.png"
        if not image_path.exists():
            raise ProductionError(f"missing rendered slide image for '{slide_id}': {image_path}")
        segment_files.append((seg, seg_audio, dur, image_path))

    pacing_cfg = video_cfg.get("pacing", {})
    slide_pause_seconds = float(pacing_cfg.get("slide_pause_seconds", 0.5))

    title_cfg = video_cfg.get("title_card", {})
    title_duration = float(title_cfg.get("duration_seconds", 3.0)) if title and title_cfg.get("enabled", True) else 0.0

    segments_with_duration = [(seg, dur) for seg, _p, dur, _i in segment_files]
    timing, total_duration = compute_slide_timeline(
        segments_with_duration, title_duration=title_duration, slide_pause_seconds=slide_pause_seconds
    )

    durations_only = [dur for _s, dur in segments_with_duration]
    pacing_warnings: list[str] = []
    if len(durations_only) >= 2:
        median_dur = statistics.median(durations_only)
        for seg, dur in segments_with_duration:
            if dur > median_dur * 2.5 and dur - median_dur > 8.0:
                pacing_warnings.append(
                    f"slide {seg['slide_id']}: narration is {dur:.1f}s, well beyond the deck's median "
                    f"({median_dur:.1f}s) - consider splitting this slide's content upstream rather than "
                    "trimming its narration (see slide_deck_localization SKILL.md 'Narration pacing')"
                )

    captions_by_slide_id = {seg["slide_id"]: seg["caption"] for seg in segments}

    srt_path = output_path / "captions.srt"
    _write_srt(timing, captions_by_slide_id, title, srt_path)

    burn_in_cfg = video_cfg.get("captions", {}).get("burn_in", True)
    burn_in = burn_in_cfg if burn_in_override is None else burn_in_override
    ass_path = None
    if burn_in:
        ass_path = output_path / "captions.ass"
        _write_ass(timing, captions_by_slide_id, title, profile, video_cfg, resolution, ass_path)

    # ---------- video: title card (reuses slide 1's image) + every slide's image, each held for its computed duration ----------
    image_items: list[tuple[Path, float]] = []
    if title_duration > 0 and segment_files:
        image_items.append((segment_files[0][3], title_duration))
    for _seg, _audio, dur, image_path in segment_files:
        image_items.append((image_path, dur + slide_pause_seconds))

    silent_video = output_path / "_silent.mp4"
    _build_silent_captioned_video(image_items, ass_path, resolution, video_cfg, silent_video)

    # ---------- audio: silence for the title window, then each slide's narration + a trailing pause ----------
    audio_items: list[tuple[str, object]] = []
    if title_duration > 0:
        audio_items.append(("silence", title_duration))
    for _seg, seg_audio, _dur, _image in segment_files:
        audio_items.append(("file", seg_audio))
        if slide_pause_seconds > 0:
            audio_items.append(("silence", slide_pause_seconds))

    full_audio_track = output_path / "_full_audio.m4a"
    _build_audio_track(audio_items, full_audio_track)

    render_cfg = video_cfg.get("render", {})
    output_video = output_path / "slideshow.mp4"
    mux_cmd = [
        "ffmpeg", "-y", "-i", str(silent_video), "-i", str(full_audio_track),
        "-map", "0:v", "-map", "1:a",
        "-c:v", "copy",
        "-c:a", render_cfg.get("audio_codec", "aac"),
        "-b:a", render_cfg.get("audio_bitrate", "192k"),
        "-shortest",
    ]
    if render_cfg.get("faststart", True):
        mux_cmd += ["-movflags", "+faststart"]
    mux_cmd.append(str(output_video))
    subprocess.run(mux_cmd, check=True, capture_output=True)
    silent_video.unlink(missing_ok=True)
    full_audio_track.unlink(missing_ok=True)

    narration_mp3 = output_path / "narration.mp3"
    concat_list = output_path / "_narration_concat.txt"
    concat_list.write_text(
        "\n".join(f"file '{p.as_posix()}'" for _s, p, _d, _i in segment_files), encoding="utf-8"
    )
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list), "-c", "copy", str(narration_mp3)],
        check=True, capture_output=True,
    )
    concat_list.unlink(missing_ok=True)

    out_duration = ffprobe_duration(str(output_video))
    tolerance = float(video_cfg.get("sync", {}).get("max_duration_drift_seconds", 0.75))
    duration_ok = abs(out_duration - total_duration) <= tolerance

    production = {
        "run_id": run_id,
        "project_id": project_id,
        "language": language,
        "title": title,
        "source_deck": str(Path(source_deck).resolve()),
        "source_deck_fingerprint": directory_fingerprint(source_deck),
        "narration_audio": str(narration_mp3),
        "captions": str(srt_path),
        "captions_ass": str(ass_path) if ass_path else None,
        "output_video": str(output_video),
        "voice": profile.get("voice"),
        "tts_model": model,
        "total_duration_seconds": round(total_duration, 3),
        "output_duration_seconds": out_duration,
        "slides": [s["slide_id"] for s in segments],
        "segment_timing": timing,
        "burn_in": burn_in,
        "pacing_warnings": pacing_warnings,
        "duration_check_ok": duration_ok,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    (output_path / "production.json").write_text(
        json.dumps(production, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    envelope = logger.status_envelope(
        agent="slideshow_production_agent", language=language, status="completed",
        outputs=production, warnings=pacing_warnings,
    )
    logger.log(
        agent="slideshow_production_agent", skill="slideshow_video_production",
        stage="tts", language=language, event="render_completed", status="completed",
        duration_seconds=time.time() - t0,
        artifacts=[str(output_video), str(srt_path), str(narration_mp3)],
        warnings=pacing_warnings,
    )
    return envelope
