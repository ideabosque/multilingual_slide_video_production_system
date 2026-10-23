"""Shared helpers for the motion tests (not collected by pytest - no
test_ prefix). Builds the same kinds of inputs the real pipeline's
`msv production render-slideshow` produces for one language: a deck, a
production.json with segment_timing, per-slide narration mp3s, and a
minimal (or real, via generate_deck_animation) animation bundle."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

TITLE_SECONDS = 1.0
SLIDE_SECONDS = (1.5, 1.5)


def _ffmpeg(*args) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True, capture_output=True)


def write_deck(deck_dir: Path, slide_bodies: dict[str, str]) -> None:
    """slide_id -> inner HTML; writes <slide_id>.html files."""
    deck_dir.mkdir(parents=True, exist_ok=True)
    for slide_id, body in slide_bodies.items():
        (deck_dir / f"{slide_id}.html").write_text(
            "<!DOCTYPE html><html><head><meta charset='utf-8'>"
            "<style>body{margin:0;background:#123030;color:#eee;"
            "font-family:sans-serif}</style></head>\n"
            f"<body>{body}</body></html>",
            encoding="utf-8",
        )


def make_segment_audio(segments_dir: Path, slide_id: str, seconds: float = 0.6) -> Path:
    """A short sine-wave mp3 standing in for that slide's narration."""
    segments_dir.mkdir(parents=True, exist_ok=True)
    out = segments_dir / f"{slide_id}.mp3"
    _ffmpeg("-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-q:a", "6", str(out))
    return out


def write_production(
    out_dir: Path,
    slide_ids: list[str],
    *,
    title: str = "Motion {test} title",
    title_seconds: float = TITLE_SECONDS,
    slide_seconds: tuple[float, ...] = SLIDE_SECONDS,
    language: str = "en-US",
) -> Path:
    """production.json with narration-segment audio present for every slide;
    timing mirrors render_slideshow.py's layout (title card first)."""
    timing = [{"kind": "title", "start_time": 0.0, "end_time": float(title_seconds)}]
    cursor = title_seconds
    for slide_id, seconds in zip(slide_ids, slide_seconds, strict=True):
        timing.append({
            "kind": "slide", "slide_id": slide_id,
            "start_time": cursor, "end_time": cursor + seconds,
        })
        cursor += seconds
    narration_dir = out_dir / "narration"
    segments_dir = narration_dir / "segments"
    for slide_id in slide_ids:
        make_segment_audio(segments_dir, slide_id)
    production = {
        "run_id": "run-motion-test", "project_id": "proj-motion-test",
        "language": language, "title": title,
        "narration_audio": str(narration_dir / "narration.wav"),
        "segment_timing": timing,
        "total_duration_seconds": round(cursor, 3),
        "segment_audio_keys": {sid: "key-" + sid for sid in slide_ids},
        "regenerated_segments": slide_ids,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "production.json"
    path.write_text(json.dumps(production, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def make_minimal_animation_bundle(animation_dir: Path, templates_by_slide: dict[str, str]) -> None:
    """spec.json etc. for path-level tests (no real bundle needed)."""
    animation_dir.mkdir(parents=True, exist_ok=True)
    (animation_dir / "spec.json").write_text(
        json.dumps({"slides": [
            {"slide_id": sid, "template": tpl, "visual_role_used": tpl}
            for sid, tpl in templates_by_slide.items()
        ]}),
        encoding="utf-8",
    )


def render_source_images(slides_dir: Path, colors: dict[str, str]) -> None:
    """slide_id -> css color; rendered slide PNGs for title-card backgrounds."""
    slides_dir.mkdir(parents=True, exist_ok=True)
    for slide_id, color in colors.items():
        _ffmpeg("-f", "lavfi", "-i", f"color=c={color}:s=1280x720", "-frames:v", "1",
                str(slides_dir / f"{slide_id}.png"))