"""Assembly + validation over real ffmpeg output (requires_ffmpeg): the
exact-length contract, and B6 checks catching a deliberately blank
boundary segment / a no-op animation - the same failure classes the
plan's flash bugs needed frame extraction to find. Moving sources
(testsrc2) so check 3 passes when animation genuinely happened."""
import pytest

pytestmark = pytest.mark.requires_ffmpeg

from multilingual_slide_video_agent.media import ffprobe_duration
from multilingual_slide_video_agent.production.motion import post
from multilingual_slide_video_agent.production.motion import validate as motion_validate
from multilingual_slide_video_agent.production.motion.context import MotionRenderContext_from_production
from multilingual_slide_video_agent.production.motion.playwright_engine import assemble_silent_video

from motion_fixture_helpers import (
    make_minimal_animation_bundle,
    render_source_images,
    write_deck,
    write_production,
)


def _lavfi_video(path, lavfi_expr):
    import subprocess
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", lavfi_expr,
                    "-pix_fmt", "yuv420p", str(path)], check=True, capture_output=True)


def _ctx(tmp_path, *, fps=30):
    production = write_production(tmp_path / "out", ["slide_001", "slide_002"])
    deck = tmp_path / "deck"
    write_deck(deck, {
        "slide_001": "<h1>Alpha</h1><ul><li>one</li><li>two</li><li>three</li><li>four</li></ul>",
        "slide_002": "<h2>Beta</h2><p>body text here</p>",
    })
    make_minimal_animation_bundle(tmp_path / "anim", {"slide_001": "title_reveal", "slide_002": "feature_callout"})
    slides_dir = tmp_path / "slides"
    render_source_images(slides_dir, {"slide_001": "navy", "slide_002": "teal"})
    return MotionRenderContext_from_production(
        production_path=production, translated_deck_dir=deck,
        animation_dir=tmp_path / "anim", slides_dir=slides_dir, fps=fps,
    )


SRC_A = "testsrc2=s=1280x720:d=2.0"   # visibly changes over time
SRC_B = "testsrc=s=1280x720:d=2.0"    # different moving source


def test_silent_video_is_exact_length(tmp_path, monkeypatch):
    monkeypatch.setenv("MSV_LOGS_DIR", str(tmp_path / "logs"))
    ctx = _ctx(tmp_path)
    src_a, src_b = tmp_path / "capture_a.mp4", tmp_path / "capture_b.mp4"
    _lavfi_video(src_a, SRC_A)
    _lavfi_video(src_b, SRC_B)

    segments = [
        {"kind": "title", "src": ctx.slides_dir / "slide_001.png",
         "duration": ctx.title_item["end_time"] - ctx.title_item["start_time"]},
        {"kind": "slide", "src": src_a, "duration": ctx.slide_by_id("slide_001").duration,
         "video_lead_in_seconds": 0.05},
        {"kind": "slide", "src": src_b, "duration": ctx.slide_by_id("slide_002").duration},
    ]
    silent = tmp_path / "silent.mp4"
    assemble_silent_video(ctx=ctx, segments=segments, work_dir=tmp_path / "assembly", dest=silent)

    # B6 check 1: within one frame of segment_timing's total
    assert abs(ffprobe_duration(str(silent)) - ctx.total_duration) <= 1.0 / ctx.fps


def test_validation_catches_blank_boundary_and_no_op_animation(tmp_path, monkeypatch):
    monkeypatch.setenv("MSV_LOGS_DIR", str(tmp_path / "logs"))
    ctx = _ctx(tmp_path)
    src_a, blank = tmp_path / "capture_a.mp4", tmp_path / "capture_blank.mp4"
    _lavfi_video(src_a, SRC_A)
    _lavfi_video(blank, "color=c=white:s=1280x720:d=2.0")  # the deliberate regression

    segments = [
        {"kind": "title", "src": ctx.slides_dir / "slide_001.png",
         "duration": ctx.title_item["end_time"] - ctx.title_item["start_time"]},
        {"kind": "slide", "src": src_a, "duration": ctx.slide_by_id("slide_001").duration},
        {"kind": "slide", "src": blank, "duration": ctx.slide_by_id("slide_002").duration},  # the deliberate regression
    ]
    silent = tmp_path / "silent.mp4"
    assemble_silent_video(ctx=ctx, segments=segments, work_dir=tmp_path / "assembly", dest=silent)

    final = tmp_path / "marketing_playwright.mp4"
    post.burn_and_mux(silent, ctx, tmp_path / "post", {}, final)

    validation = motion_validate.validate_motion(
        silent_video=silent, final_video=final, ctx=ctx, work_dir=tmp_path / "validation",
    )
    assert validation["ok"] is False
    joined = " ".join(validation["errors"])
    assert "slide_002" in joined          # the blank boundary is named
    checks_by_slide = {c["slide_id"]: c for c in validation["animation_checks"]}
    assert checks_by_slide["slide_001"]["ok"] is True    # real motion happened
    assert checks_by_slide["slide_002"]["ok"] is False   # "never visibly happened"


def test_validation_passes_on_clean_two_slide_render(tmp_path, monkeypatch):
    monkeypatch.setenv("MSV_LOGS_DIR", str(tmp_path / "logs"))
    ctx = _ctx(tmp_path)
    src_a, src_b = tmp_path / "a.mp4", tmp_path / "b.mp4"
    _lavfi_video(src_a, SRC_A)
    _lavfi_video(src_b, SRC_B)
    segments = [
        {"kind": "title", "src": ctx.slides_dir / "slide_001.png",
         "duration": ctx.title_item["end_time"] - ctx.title_item["start_time"]},
        {"kind": "slide", "src": src_a, "duration": ctx.slide_by_id("slide_001").duration},
        {"kind": "slide", "src": src_b, "duration": ctx.slide_by_id("slide_002").duration},
    ]
    silent = tmp_path / "silent.mp4"
    assemble_silent_video(ctx=ctx, segments=segments, work_dir=tmp_path / "assembly", dest=silent)
    final = tmp_path / "marketing_playwright.mp4"
    post_info = post.burn_and_mux(silent, ctx, tmp_path / "post", {"slide_001": "First", "slide_002": "Second"}, final)

    validation = motion_validate.validate_motion(
        silent_video=silent, final_video=final, ctx=ctx, work_dir=tmp_path / "validation",
    )
    assert validation["ok"] is True, validation["errors"]
    assert post_info["srt_cue_count"] == 3  # title cue + 2 slide captions
    assert final.with_name(final.stem + "_captions.srt").exists()