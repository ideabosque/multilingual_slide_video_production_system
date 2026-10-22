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

# ---------- per-slide checks: the problem is in the MIDDLE slide ----------
# (A problem in the last slide is the one case the old whole-video
# last-frame comparison happened to catch.)

THREE_SLIDES = ("slide_001", "slide_002", "slide_003")


def _ctx3(tmp_path, *, fps=30):
    production = write_production(tmp_path / "out", list(THREE_SLIDES), slide_seconds=(1.5, 1.5, 1.5))
    deck = tmp_path / "deck"
    write_deck(deck, {sid: f"<h1>{sid}</h1>" for sid in THREE_SLIDES})
    make_minimal_animation_bundle(tmp_path / "anim", {sid: "feature_callout" for sid in THREE_SLIDES})
    slides_dir = tmp_path / "slides"
    render_source_images(slides_dir, {"slide_001": "navy"})
    return MotionRenderContext_from_production(
        production_path=production, translated_deck_dir=deck,
        animation_dir=tmp_path / "anim", slides_dir=slides_dir, fps=fps,
    )


def _validate_three(tmp_path, ctx, middle_src):
    moving_a, moving_b = tmp_path / "a.mp4", tmp_path / "b.mp4"
    _lavfi_video(moving_a, SRC_A)
    _lavfi_video(moving_b, SRC_B)
    segments = [
        {"kind": "title", "src": ctx.slides_dir / "slide_001.png",
         "duration": ctx.title_item["end_time"] - ctx.title_item["start_time"]},
        {"kind": "slide", "slide_id": "slide_001", "src": moving_a, "duration": ctx.slide_by_id("slide_001").duration},
        {"kind": "slide", "slide_id": "slide_002", "src": middle_src, "duration": ctx.slide_by_id("slide_002").duration},
        {"kind": "slide", "slide_id": "slide_003", "src": moving_b, "duration": ctx.slide_by_id("slide_003").duration},
    ]
    silent = tmp_path / "silent.mp4"
    assemble_silent_video(ctx=ctx, segments=segments, work_dir=tmp_path / "assembly", dest=silent)
    final = tmp_path / "final.mp4"
    post.burn_and_mux(silent, ctx, tmp_path / "post", {}, final)
    return motion_validate.validate_motion(
        silent_video=silent, final_video=final, ctx=ctx, work_dir=tmp_path / "validation",
    )


def test_static_middle_slide_fails_the_animation_check(tmp_path, monkeypatch):
    monkeypatch.setenv("MSV_LOGS_DIR", str(tmp_path / "logs"))
    ctx = _ctx3(tmp_path)
    static = tmp_path / "static.mp4"
    _lavfi_video(static, "testsrc=s=1280x720:d=2.0,trim=end_frame=1,tpad=stop_mode=clone:stop_duration=3")
    validation = _validate_three(tmp_path, ctx, static)
    checks = {c["slide_id"]: c["ok"] for c in validation["animation_checks"]}
    assert checks == {"slide_001": True, "slide_002": False, "slide_003": True}
    assert validation["ok"] is False and "slide_002" in " ".join(validation["errors"])


def test_sentinel_frame_in_middle_slide_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("MSV_LOGS_DIR", str(tmp_path / "logs"))
    ctx = _ctx3(tmp_path)
    magenta = tmp_path / "magenta.mp4"
    _lavfi_video(magenta, "color=c=0xFF00FF:s=1280x720:d=2.0")
    validation = _validate_three(tmp_path, ctx, magenta)
    bad = [c for c in validation["boundary_checks"] if not c["ok"]]
    assert {c["slide_id"] for c in bad} == {"slide_002"}
    assert all(c["sentinel"] for c in bad)
    assert "capture-sentinel" in " ".join(validation["errors"])


def test_white_deck_entrance_from_its_own_background_passes(tmp_path, monkeypatch):
    """A white slide whose content appears after the first frame starts on a
    blank-white frame - that's its own background, not a flash."""
    monkeypatch.setenv("MSV_LOGS_DIR", str(tmp_path / "logs"))
    ctx = _ctx3(tmp_path)
    white_entrance = tmp_path / "white_entrance.mp4"
    _lavfi_video(white_entrance, "color=c=white:s=1280x720:d=2.0,"
                                 "drawbox=x=100:y=100:w=400:h=80:color=black:t=fill:enable='gte(t,0.4)'")
    validation = _validate_three(tmp_path, ctx, white_entrance)
    assert validation["ok"] is True, validation["errors"]
    start = next(c for c in validation["boundary_checks"]
                 if c["slide_id"] == "slide_002" and c["boundary"] == "start")
    assert start["mean"] > 244 and start["ok"] is True


def test_assembly_refuses_a_segment_off_by_more_than_one_frame(tmp_path, monkeypatch):
    """A short segment must fail loudly, not be carried into the next
    slide (which would shift every later slide against its narration)."""
    from multilingual_slide_video_agent.production.motion import playwright_engine
    from multilingual_slide_video_agent.production.motion.errors import MotionError

    monkeypatch.setenv("MSV_LOGS_DIR", str(tmp_path / "logs"))
    ctx = _ctx3(tmp_path)
    real_encode = playwright_engine._encode_segment

    def short_middle(seg, dest, ctx_):
        if seg.get("slide_id") == "slide_002":
            seg = {**seg, "frames": seg["frames"] - 12}
        real_encode(seg, dest, ctx_)

    monkeypatch.setattr(playwright_engine, "_encode_segment", short_middle)
    src = tmp_path / "a.mp4"
    _lavfi_video(src, SRC_A)
    segments = [
        {"kind": "slide", "slide_id": sid, "src": src, "duration": ctx.slide_by_id(sid).duration}
        for sid in THREE_SLIDES
    ]
    with pytest.raises(MotionError, match="slide_002"):
        assemble_silent_video(ctx=ctx, segments=segments, work_dir=tmp_path / "assembly",
                              dest=tmp_path / "silent.mp4")


def test_segment_frame_counts_round_from_the_absolute_timeline():
    from multilingual_slide_video_agent.production.motion.playwright_engine import segment_frame_counts

    # 1.0s title then slides of irregular narration-driven lengths
    durations = [1.0, 1.517, 2.483, 0.75, 3.333]
    counts = segment_frame_counts(durations, 30)
    assert counts == [30, 46, 74, 22, 100]
    # boundaries land on the frame nearest each absolute start, so the total
    # never drifts however many slides there are
    assert sum(segment_frame_counts([1.0 / 7] * 700, 30)) == round(100 * 30)


# ---------- narration audio: never silently missing ----------

def test_missing_narration_clip_fails_instead_of_rendering_silence(tmp_path, monkeypatch):
    """A one-pass demo once rendered a complete-looking video with no sound:
    the clips weren't where the render looked, and silence was substituted."""
    from multilingual_slide_video_agent.production.motion.post import MotionPostError

    monkeypatch.setenv("MSV_LOGS_DIR", str(tmp_path / "logs"))
    ctx = _ctx(tmp_path)
    (ctx.segment_audio_dir / "slide_002.mp3").unlink()
    with pytest.raises(MotionPostError, match="slide_002"):
        post.build_narration_track(ctx, tmp_path / "post")


def test_context_uses_the_recorded_segment_audio_dir(tmp_path, monkeypatch):
    """narrate --audio-dir records where the clips are; the render uses it."""
    import json as _json

    monkeypatch.setenv("MSV_LOGS_DIR", str(tmp_path / "logs"))
    ctx = _ctx(tmp_path)
    elsewhere = tmp_path / "shared_clips"
    ctx.segment_audio_dir.rename(elsewhere)
    production = _json.loads(ctx.production_path.read_text(encoding="utf-8"))
    production["segment_audio_dir"] = str(elsewhere)
    ctx.production_path.write_text(_json.dumps(production), encoding="utf-8")

    reloaded = MotionRenderContext_from_production(
        production_path=ctx.production_path, translated_deck_dir=ctx.translated_deck_dir,
        animation_dir=ctx.animation_dir, slides_dir=ctx.slides_dir, fps=30,
    )
    assert reloaded.segment_audio_dir == elsewhere.resolve()
    post.build_narration_track(reloaded, tmp_path / "post")   # finds every clip


def test_validation_catches_a_silent_slide(tmp_path, monkeypatch):
    import subprocess

    monkeypatch.setenv("MSV_LOGS_DIR", str(tmp_path / "logs"))
    ctx = _ctx(tmp_path)
    # slide_002's clip is pure silence: everything else about the video is fine
    silent_clip = ctx.segment_audio_dir / "slide_002.mp3"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    "anullsrc=r=44100:cl=stereo:d=0.6", str(silent_clip)], check=True)
    src_a, src_b = tmp_path / "a.mp4", tmp_path / "b.mp4"
    _lavfi_video(src_a, SRC_A)
    _lavfi_video(src_b, SRC_B)
    segments = [
        {"kind": "title", "src": ctx.slides_dir / "slide_001.png",
         "duration": ctx.title_item["end_time"] - ctx.title_item["start_time"]},
        {"kind": "slide", "slide_id": "slide_001", "src": src_a, "duration": ctx.slide_by_id("slide_001").duration},
        {"kind": "slide", "slide_id": "slide_002", "src": src_b, "duration": ctx.slide_by_id("slide_002").duration},
    ]
    silent = tmp_path / "silent.mp4"
    assemble_silent_video(ctx=ctx, segments=segments, work_dir=tmp_path / "assembly", dest=silent)
    final = tmp_path / "video.mp4"
    post.burn_and_mux(silent, ctx, tmp_path / "post", {}, final)
    validation = motion_validate.validate_motion(
        silent_video=silent, final_video=final, ctx=ctx, work_dir=tmp_path / "validation",
    )
    checks = {c["slide_id"]: c["ok"] for c in validation["audio_checks"]}
    assert checks == {"slide_001": True, "slide_002": False}
    assert validation["ok"] is False and "no audible narration" in " ".join(validation["errors"])
