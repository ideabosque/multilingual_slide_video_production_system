"""The HyperFrames engine (plan B4, Phase 2b): slide -> sub-composition
conversion and project layout (no Node needed), plus an end-to-end render
through render_motion on the fixture deck (requires Node 22+, the pinned
HyperFrames install, and ffmpeg)."""
import json
import re
import shutil

import pytest

from multilingual_slide_video_agent.production.motion import hyperframes_engine as hf
from multilingual_slide_video_agent.production.motion.context import MotionRenderContext_from_production

from motion_fixture_helpers import make_minimal_animation_bundle, render_source_images, write_deck, write_production

REAL_SHAPED_SLIDE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<style>html, body { margin: 0; background: #0b1f1d; } .stat-num { font-size: 200px; }</style>
<link rel="stylesheet" href="./styles.css">
<!-- ANIMATION-OVERRIDE -->
<style>html{visibility:hidden}</style>
<script src="animation_runtime.js" defer></script>
<!-- /ANIMATION-OVERRIDE -->
</head>
<body class="dark hero" style="color: #eee">
<p class="eyebrow">Board-level risk signal</p>
<div class="stat-num">8<span class="unit">%</span></div>
<script>document.body.classList.add("deck-nav")</script>
</body></html>
"""


def test_slide_to_template_shape():
    html, dropped = hf.slide_to_template(REAL_SHAPED_SLIDE, slide_id="slide_005", template="stat_highlight",
                                         width=1920, height=1080)
    stripped = html.strip()
    assert stripped.startswith("<template") and stripped.endswith("</template>")
    assert 'data-composition-id="slide_005"' in html and 'data-width="1920"' in html
    # the stale capture injection and the deck's own script are gone
    assert "visibility:hidden" not in html and "animation_runtime.js" not in html
    assert "deck-nav" not in html and dropped == 1   # the injection block is stripped before counting
    # styles move inside the template, made root-relative
    assert ".stat-num { font-size: 200px; }" in html and 'href="styles.css"' in html
    # body classes/style land on a wrapper, not the composition root
    assert re.search(r'<div data-motion-slide-body class="dark hero" style="position:absolute;inset:0;color: #eee">', html)
    # text elements carry their extract-text node ids, for motion design targets
    assert '<p class="eyebrow" data-motion-node="slide_005#n0">Board-level risk signal</p>' in html
    assert '<div class="stat-num" data-motion-node="slide_005#n1">8<span class="unit" data-motion-node="slide_005#n2">%</span>' in html
    # the slide's timeline is built inside its own root
    assert 'window.__motionRunSlide(document.querySelector(\'[data-composition-id="slide_005"]\')' in html
    assert '"template": "stat_highlight"' in html


def _ctx(tmp_path, *, slide_seconds=(1.517, 2.483), viewport="1280x720"):
    deck = tmp_path / "deck"
    write_deck(deck, {
        "slide_001": "<h1>Alpha deck</h1><ul><li>one</li><li>two</li><li>three</li><li>four</li></ul>",
        "slide_002": "<h1>Stat slide</h1><div class='stat'>75%</div><p>body text</p>",
    })
    (deck / "assets").mkdir()
    (deck / "assets" / "logo.txt").write_text("asset", encoding="utf-8")
    from multilingual_slide_video_agent.slides.generate_animation import generate_deck_animation

    generate_deck_animation(deck_dir=deck, out_dir=tmp_path / "anim")
    slides = tmp_path / "slides"
    render_source_images(slides, {"slide_001": "navy", "slide_002": "teal"})
    production = write_production(tmp_path / "out", ["slide_001", "slide_002"], slide_seconds=slide_seconds)
    return MotionRenderContext_from_production(
        production_path=production, translated_deck_dir=deck, animation_dir=tmp_path / "anim",
        slides_dir=slides, viewport=viewport,
    )


@pytest.mark.requires_ffmpeg
def test_build_project_layout_and_frame_exact_clip_timing(tmp_path, monkeypatch):
    monkeypatch.setenv("MSV_LOGS_DIR", str(tmp_path / "logs"))
    ctx = _ctx(tmp_path)
    project = tmp_path / "hf"
    built = hf.build_project(ctx, project)

    assert (project / "index.html").exists()
    assert (project / "assets" / "logo.txt").exists()                  # deck assets at the root
    assert not list(project.glob("slide_*.html"))                       # slides only as compositions
    assert {p.name for p in (project / "compositions").iterdir()} == {"title.html", "slide_001.html", "slide_002.html"}
    for name in hf._INDEX_ASSETS:
        assert (project / name).exists()

    index = (project / "index.html").read_text(encoding="utf-8")
    starts = [float(v) for v in re.findall(r'data-start="([0-9.]+)" data-duration', index)]
    durations = [float(v) for v in re.findall(r'data-duration="([0-9.]+)"', index)]
    # title 1.0s, then 1.517s and 2.483s - boundaries on whole frames at 30fps
    assert [round(s * 30) for s in starts] == [0, 30, 76]
    assert [round(d * 30) for d in durations] == [30, 46, 74]
    assert built["total_frames"] == 150

    # the title card is animated from slide 1's own markup - no screenshots
    title = (project / "compositions" / "title.html").read_text(encoding="utf-8")
    assert "title_backdrop" in title and "blur(" in title and "Alpha deck" in title
    assert not (project / "title.png").exists()


@pytest.mark.requires_node
@pytest.mark.requires_ffmpeg
def test_render_motion_with_hyperframes_end_to_end(tmp_path, monkeypatch):
    if hf.check_available():
        pytest.skip("; ".join(hf.check_available()))
    from multilingual_slide_video_agent.production.motion.render import render_motion

    monkeypatch.setenv("MSV_LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("VIDEO_RESOLUTION", "720p")
    ctx = _ctx(tmp_path, slide_seconds=(1.5, 1.5))
    localization = tmp_path / "localization_en-US.json"
    localization.write_text(json.dumps({"language": "en-US", "segments": [
        {"slide_id": "slide_001", "caption": "First caption"},
        {"slide_id": "slide_002", "caption": "Second caption"},
    ]}), encoding="utf-8")

    envelope = render_motion(
        production_path=str(ctx.production_path), translated_deck_dir=str(ctx.translated_deck_dir),
        animation_dir=str(ctx.animation_dir), slides_dir=str(ctx.slides_dir),
        localization_path=str(localization), engine_name="hyperframes", viewport="1280x720",
    )
    assert envelope["status"] == "completed"
    out = ctx.production_path.parent
    motion = json.loads((out / "video.motion.json").read_text(encoding="utf-8"))
    assert motion["engine"]["name"] == "hyperframes" and motion["engine"]["version"]
    assert motion["validation"]["ok"] is True, motion["validation"]["errors"]
    assert (out / "video.mp4").exists()
    # rendering is the production render: the video is recorded in production.json
    production = json.loads(ctx.production_path.read_text(encoding="utf-8"))
    assert production["output_video"].endswith("video.mp4") and production["video_kind"] == "animated"
    assert production["motion_engine"] == "hyperframes" and production["duration_check_ok"] is True
    assert not (out / "_motion_hyperframes_work").exists()


def test_css_comments_mentioning_style_tags_dont_unbalance_the_template():
    """The real deck's CSS comment "DO NOT EDIT the rules in this <style>
    block" made HyperFrames' check report an unclosed <style> on every slide."""
    slide = (
        "<!DOCTYPE html><html><head><style>\n"
        "/* Deck framework - DO NOT EDIT the rules in this <style> block.\n"
        "   Edit only inside the second <style> block below. */\n"
        ".x::before { content: \"<b>\"; }\n"
        "</style></head><body><p class='x'>hi</p></body></html>"
    )
    html, _ = hf.slide_to_template(slide, slide_id="slide_001", template="feature_callout", width=1920, height=1080)
    assert html.count("<style") == html.count("</style>") == 1
    assert "DO NOT EDIT" not in html                     # comment dropped
    assert r'content: "\3C b>"' in html                  # remaining "<" CSS-escaped


@pytest.mark.requires_node
@pytest.mark.requires_ffmpeg
def test_a_broken_template_fails_the_render_naming_the_slide(tmp_path, monkeypatch):
    """A template that throws in the browser (here: an unknown effect) must
    fail loudly at HyperFrames' `check`, naming the slide - never produce a
    silently broken video."""
    if hf.check_available():
        pytest.skip("; ".join(hf.check_available()))
    from multilingual_slide_video_agent.production.motion.errors import MotionError
    from multilingual_slide_video_agent.slides.animation_templates import load_template_config

    monkeypatch.setenv("MSV_LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("VIDEO_RESOLUTION", "720p")
    ctx = _ctx(tmp_path, slide_seconds=(1.5, 1.5))
    broken = {name: {"steps": [{"role": "title", "effect": "bogus_effect"}]} for name in load_template_config("calm")}
    monkeypatch.setattr(hf, "load_template_config", lambda style: broken)
    with pytest.raises(MotionError, match=r"(?s)check.*slide_00[12]"):
        hf.HyperFramesEngine().render(ctx, tmp_path / "engine")
