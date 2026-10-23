"""The Remotion engine (plan B5, Phase 3) in its deck-faithful mode: the
pages and input props it builds (no Node needed), an end-to-end render
through render_motion on the fixture deck, frame parity with HyperFrames,
and a broken template failing loudly (these need Node 22+, the pinned
`msv motion install` and ffmpeg)."""
import json
import subprocess

import numpy as np
import pytest

from multilingual_slide_video_agent.production.motion import hyperframes_engine as hf
from multilingual_slide_video_agent.production.motion import remotion_engine as rm

from test_hyperframes_engine import _ctx


@pytest.mark.requires_ffmpeg
def test_build_public_dir_pages_and_frame_exact_clips(tmp_path, monkeypatch):
    monkeypatch.setenv("MSV_LOGS_DIR", str(tmp_path / "logs"))
    ctx = _ctx(tmp_path)
    built = rm.build_public_dir(ctx, tmp_path / "public")
    deck = tmp_path / "public" / "deck"

    props = built["props"]
    assert (props["width"], props["height"], props["fps"]) == (1280, 720, 30)
    # the same whole-frame boundaries as HyperFrames (title 1.0s, 1.517s, 2.483s)
    assert [(c["id"], c["from"], c["durationInFrames"]) for c in props["clips"]] == [
        ("title", 0, 30), ("slide_001", 30, 46), ("slide_002", 76, 74),
    ]
    assert props["durationInFrames"] == built["total_frames"] == 150
    hf_built = hf.build_project(ctx, tmp_path / "hf")
    assert hf_built["total_frames"] == built["total_frames"]

    assert (deck / "assets" / "logo.txt").exists()                       # deck assets alongside the pages
    for name in (*rm._PAGE_ASSETS, "templates_config.js"):
        assert (deck / name).exists()
    page = (deck / "slide_002.html").read_text(encoding="utf-8")
    assert 'window.__MOTION_MODE__="seek"' in page and 'window.__ANIMATION_SLIDE_ID__="slide_002"' in page
    assert "window.__ANIMATION_SLIDE_DURATION__=2.466667" in page        # 74 frames, not the raw 2.483s
    assert "window.__motionErrors" in page
    # the title card's backdrop is slide 1's markup, blurred, with its own template
    title = (deck / rm.TITLE_PAGE_NAME).read_text(encoding="utf-8")
    assert "Alpha deck" in title and "blur(" in title and '__ANIMATION_TEMPLATE__="title_backdrop"' in title
    assert "title_backdrop" in (deck / "templates_config.js").read_text(encoding="utf-8")
    # the source deck is never modified
    assert "ANIMATION-OVERRIDE" not in (ctx.translated_deck_dir / "slide_002.html").read_text(encoding="utf-8")


def test_deck_scripts_are_dropped_from_pages(tmp_path):
    source = tmp_path / "slide_001.html"
    source.write_text("<html><head><script>window.deckNav = 1</script></head>"
                      "<body><h1>Hi</h1><SCRIPT src='nav.js'></SCRIPT></body></html>", encoding="utf-8")
    dest = tmp_path / "out.html"
    rm._prepare_page(source, dest, slide_id="slide_001", template="feature_callout", duration=2.0)
    page = dest.read_text(encoding="utf-8")
    assert "deckNav" not in page and "nav.js" not in page
    assert '<script src="animation_runtime.js" defer></script>' in page


def _skip_unless_available():
    if rm.check_available():
        pytest.skip("; ".join(rm.check_available()))


def _frame_at(video, seconds, out):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{seconds:.4f}", "-i", str(video),
                    "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-s", "320x180", str(out)],
                   check=True)
    return np.frombuffer(out.read_bytes(), dtype=np.uint8).astype(int)


@pytest.mark.requires_node
@pytest.mark.requires_ffmpeg
def test_render_motion_with_remotion_end_to_end_matches_hyperframes(tmp_path, monkeypatch):
    _skip_unless_available()
    if hf.check_available():
        pytest.skip("; ".join(hf.check_available()))
    from multilingual_slide_video_agent.production.motion.render import render_motion

    monkeypatch.setenv("MSV_LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("VIDEO_RESOLUTION", "720p")
    ctx = _ctx(tmp_path, slide_seconds=(1.5, 1.5))
    _embed_font(ctx.translated_deck_dir)
    common = dict(production_path=str(ctx.production_path), translated_deck_dir=str(ctx.translated_deck_dir),
                  animation_dir=str(ctx.animation_dir), viewport="1280x720")

    envelope = render_motion(**common, engine_name="remotion", output_name="remotion.mp4")
    assert envelope["status"] == "completed"
    out = ctx.production_path.parent
    motion = json.loads((out / "remotion.motion.json").read_text(encoding="utf-8"))
    assert motion["engine"] == {"name": "remotion", "version": rm.remotion_version()}
    assert motion["validation"]["ok"] is True, motion["validation"]["errors"]
    production = json.loads(ctx.production_path.read_text(encoding="utf-8"))
    assert production["motion_engine"] == "remotion" and production["duration_check_ok"] is True
    assert not (out / "_motion_remotion_work").exists()

    # Same pages, same timelines, same frame boundaries: the two engines'
    # frames match, apart from encoder noise. Sampled mid-entrance and
    # settled, on both slides.
    render_motion(**common, engine_name="hyperframes", output_name="hyperframes.mp4", record_in_production=False)
    for t in (1.1, 1.35, 2.4, 2.6, 3.1, 3.9):
        a = _frame_at(out / "remotion.mp4", t, tmp_path / "a.raw")
        b = _frame_at(out / "hyperframes.mp4", t, tmp_path / "b.raw")
        changed = float(np.mean(np.abs(a - b) > 24))
        assert changed < 0.002, f"engines differ at t={t}s: {changed:.2%} of pixels"


def _embed_font(deck):
    """Give the fixture deck an embedded font. HyperFrames swaps system and
    generic families for its own bundled fonts (`sans-serif` renders as
    Inter there, Arial in Remotion's Chrome); an embedded face renders the
    same in both, so the comparison measures motion, not font choice."""
    from multilingual_slide_video_agent.slides.cjk_fonts import _find_font_file, _font_format, _get_font_b64

    font = _find_font_file(["DejaVuSans.ttf", "arial.ttf", "Arial.ttf", "NotoSans-Regular.ttf",
                            "LiberationSans-Regular.ttf"])
    if font is None:
        pytest.skip("no TrueType font found to embed in the fixture deck")
    face = (f"@font-face{{font-family:'Fixture Sans';src:url(data:font/{_font_format(font)};base64,"
            f"{_get_font_b64(font)})}}")
    for slide in deck.glob("slide_*.html"):
        html = slide.read_text(encoding="utf-8")
        html = html.replace("font-family:sans-serif", "font-family:'Fixture Sans'")
        slide.write_text(html.replace("</head>", f"<style>{face}</style></head>", 1), encoding="utf-8")


SAMPLE_DESIGN = {
    "schema": "motion-design/v1",
    "deck_fingerprint": "fixture",
    "style": {"energy": "lively", "notes": "fixture design exercising every engine-side feature"},
    "transitions": {"default": {"type": "crossfade", "duration": 0.4}},
    "slides": [
        {"slide_id": "slide_001", "preset": "title_reveal",
         "steps": [
             {"id": "hdr", "target": {"role": "title"}, "effect": "text_split", "by": "word", "stagger": 0.06},
             {"id": "items", "target": {"group": "ul > li"}, "effect": "pop", "stagger": 0.08, "position": "hdr+=0.2"},
             {"target": {"node": "slide_001#n2"}, "effect": "highlight", "beat_at": 0.5, "duration": 0.3},
         ],
         "camera": {"effect": "push_in", "scale": 1.05},
         "transition_out": {"type": "push", "direction": "left", "duration": 0.4}},
        {"slide_id": "slide_002", "preset": "stat_highlight",
         "steps": [
             {"target": {"role": "title"}, "effect": "reveal", "from": {"y": 30, "blur": 6}},
             {"target": {"role": "stat"}, "effect": "count_up", "pop": True, "position": 0.2},
             {"target": {"role": "stat"}, "effect": "emphasis", "scale": 1.1, "beat_at": 0.6},
         ]},
    ],
}


@pytest.mark.requires_node
@pytest.mark.requires_ffmpeg
def test_a_motion_design_renders_identically_in_both_engines(tmp_path, monkeypatch):
    """Phase 4's exit criterion: a hand-written design (custom steps, a
    camera move, a crossfade and a push) renders in every engine. Both
    engines' frames match, including mid-transition."""
    _skip_unless_available()
    if hf.check_available():
        pytest.skip("; ".join(hf.check_available()))
    from multilingual_slide_video_agent.production.motion.render import render_motion

    monkeypatch.setenv("MSV_LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("VIDEO_RESOLUTION", "720p")
    ctx = _ctx(tmp_path, slide_seconds=(2.0, 2.0))
    _embed_font(ctx.translated_deck_dir)
    design = tmp_path / "motion_design.json"
    design.write_text(json.dumps(SAMPLE_DESIGN), encoding="utf-8")
    common = dict(production_path=str(ctx.production_path), translated_deck_dir=str(ctx.translated_deck_dir),
                  animation_dir=str(ctx.animation_dir), viewport="1280x720", motion_design_path=str(design),
                  record_in_production=False)
    out = ctx.production_path.parent
    for engine in ("hyperframes", "remotion"):
        render_motion(**common, engine_name=engine, output_name=f"{engine}.mp4")
        motion = json.loads((out / f"{engine}.motion.json").read_text(encoding="utf-8"))
        assert motion["validation"]["ok"] is True, (engine, motion["validation"]["errors"])
        assert motion["motion_design"]["sha256"]

    # title -> slide_001 crossfades over 0.8-1.2s; slide_001 -> slide_002
    # pushes over 2.8-3.2s.
    for t in (0.9, 1.1, 1.6, 2.2, 2.9, 3.05, 3.5, 4.6):
        a = _frame_at(out / "remotion.mp4", t, tmp_path / "a.raw")
        b = _frame_at(out / "hyperframes.mp4", t, tmp_path / "b.raw")
        changed = float(np.mean(np.abs(a - b) > 24))
        assert changed < 0.002, f"engines differ at t={t}s: {changed:.2%} of pixels"
    # the transitions really happen: mid-push differs from both slides' own
    # frames (the fixture is mostly flat background, so the fractions are small)
    mid = _frame_at(out / "remotion.mp4", 3.0, tmp_path / "m.raw")
    before = _frame_at(out / "remotion.mp4", 2.6, tmp_path / "p.raw")
    after = _frame_at(out / "remotion.mp4", 3.4, tmp_path / "n.raw")
    assert np.mean(np.abs(mid - before) > 24) > 0.005 and np.mean(np.abs(mid - after) > 24) > 0.005


@pytest.mark.requires_node
@pytest.mark.requires_ffmpeg
def test_a_broken_template_fails_the_remotion_render_naming_the_slide(tmp_path, monkeypatch):
    _skip_unless_available()
    from multilingual_slide_video_agent.production.motion.errors import MotionError
    from multilingual_slide_video_agent.slides.animation_templates import load_template_config

    monkeypatch.setenv("MSV_LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("VIDEO_RESOLUTION", "720p")
    ctx = _ctx(tmp_path, slide_seconds=(1.5, 1.5))
    broken = {name: {"steps": [{"role": "title", "effect": "bogus_effect"}]} for name in load_template_config("calm")}
    monkeypatch.setattr(rm, "load_template_config", lambda style: broken)
    with pytest.raises(MotionError, match=r"slide_00[12].*bogus_effect"):
        rm.RemotionEngine().render(ctx, tmp_path / "engine")
