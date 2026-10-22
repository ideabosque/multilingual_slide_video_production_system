"""End-to-end render of a tiny 2-slide deck through the real ffmpeg path,
with TTS stubbed (no API key or network needed)."""
import json
import subprocess

import pytest

from multilingual_slide_video_agent.media import ffprobe_duration
from multilingual_slide_video_agent.production import render_slideshow

pytestmark = pytest.mark.requires_ffmpeg

NARRATION_SECONDS = 1.0


def _ffmpeg(*args):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


@pytest.fixture
def render_inputs(tmp_path, monkeypatch):
    monkeypatch.setenv("MSV_LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("VIDEO_RESOLUTION", "720p")

    deck = tmp_path / "deck"
    deck.mkdir()
    slides_dir = tmp_path / "rendered_en-US"
    slides_dir.mkdir()
    for i, color in enumerate(["navy", "teal"], start=1):
        (deck / f"slide_{i:03d}.html").write_text(f"<html><body><h1>Slide {i}</h1></body></html>", encoding="utf-8")
        _ffmpeg("-f", "lavfi", "-i", f"color=c={color}:s=1280x720:d=1", "-frames:v", "1",
                str(slides_dir / f"slide_{i:03d}.png"))

    localization = {
        "language": "en-US", "run_id": "run-smoke", "title": "Smoke {test} title",
        "segments": [
            {"slide_index": i, "slide_id": f"slide_{i:03d}", "slide_description": "d",
             "narration": f"Narration for slide {i}.", "caption": f"Caption {i}"}
            for i in (1, 2)
        ],
    }
    localization_path = tmp_path / "localization_en-US.json"
    localization_path.write_text(json.dumps(localization), encoding="utf-8")

    def fake_tts(text, output, voice, model, instructions):
        _ffmpeg("-f", "lavfi", "-i", f"sine=frequency=440:duration={NARRATION_SECONDS}", str(output))

    monkeypatch.setattr(render_slideshow, "_generate_segment_tts", fake_tts)

    encodes = []
    real_run = subprocess.run

    def counting_run(cmd, *args, **kwargs):
        if "-fps_mode" in cmd:  # the silent slide-video encode
            encodes.append(cmd)
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(render_slideshow.subprocess, "run", counting_run)
    return {"deck": deck, "slides_dir": slides_dir, "localization": localization_path,
            "out": tmp_path / "out", "encodes": encodes}


def test_render_language_produces_a_correct_video(render_inputs):
    envelope = render_slideshow.render_language(
        run_id="run-smoke", project_id="proj", language="en-US",
        source_deck=str(render_inputs["deck"]), slides_dir=str(render_inputs["slides_dir"]),
        localization_path=str(render_inputs["localization"]), output_dir=str(render_inputs["out"]),
    )
    assert envelope["status"] == "completed"

    out = render_inputs["out"]
    production = json.loads((out / "production.json").read_text(encoding="utf-8"))
    # Title card (3.0s) + 2 x (1.0s narration + 0.5s pause).
    assert production["total_duration_seconds"] == pytest.approx(6.0, abs=0.1)
    assert production["duration_check_ok"] is True
    assert ffprobe_duration(str(out / "slideshow.mp4")) == pytest.approx(6.0, abs=0.75)

    # A1: the expensive slide-video encode runs exactly once.
    assert len(render_inputs["encodes"]) == 1

    srt = (out / "captions.srt").read_text(encoding="utf-8")
    assert srt.count(" --> ") == 3
    # A7: the title's braces reach libass escaped, not as an override block.
    assert "Smoke \\{test\\} title" in (out / "captions.ass").read_text(encoding="utf-8")

    assert set(production["segment_audio_keys"]) == {"slide_001", "slide_002"}
    assert production["regenerated_segments"] == ["slide_001", "slide_002"]


def test_rerender_reuses_audio_and_regenerates_only_edited_slide(render_inputs):
    kwargs = dict(
        run_id="run-smoke", project_id="proj", language="en-US",
        source_deck=str(render_inputs["deck"]), slides_dir=str(render_inputs["slides_dir"]),
        localization_path=str(render_inputs["localization"]), output_dir=str(render_inputs["out"]),
    )
    render_slideshow.render_language(**kwargs)

    loc = json.loads(render_inputs["localization"].read_text(encoding="utf-8"))
    loc["segments"][1]["narration"] = "Edited narration for slide 2."
    render_inputs["localization"].write_text(json.dumps(loc), encoding="utf-8")
    render_slideshow.render_language(**kwargs)

    production = json.loads((render_inputs["out"] / "production.json").read_text(encoding="utf-8"))
    assert production["regenerated_segments"] == ["slide_002"]


def test_narrate_language_writes_timing_and_audio_without_a_video(render_inputs):
    """Animation-first production's `tts` stage: narration, timing and
    captions in production.json, no video rendered (render-motion does that)."""
    envelope = render_slideshow.narrate_language(
        run_id="run-smoke", project_id="proj", language="en-US",
        source_deck=str(render_inputs["deck"]), localization_path=str(render_inputs["localization"]),
        output_dir=str(render_inputs["out"]),
    )
    assert envelope["status"] == "completed"
    out = render_inputs["out"]
    production = json.loads((out / "production.json").read_text(encoding="utf-8"))
    assert production["output_video"] is None
    assert not (out / "slideshow.mp4").exists()
    assert (out / "narration.mp3").exists() and (out / "captions.srt").exists()
    assert [t["kind"] for t in production["segment_timing"]] == ["title", "slide", "slide"]
    assert production["total_duration_seconds"] == pytest.approx(6.0, abs=0.1)
    assert production["source_deck_fingerprint_algo"]
    assert render_inputs["encodes"] == []   # no slide-video encode at all
