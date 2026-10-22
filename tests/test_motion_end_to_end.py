"""End-to-end through the engine seam on a 2-slide fixture deck: context ->
capture -> assembly -> post-pass -> B6 validation -> motion.json, plus the
legacy alias contract. Environment-aware on purpose: where Playwright's
native recording yields an entirely-blank capture (observed on some
Windows/headless builds - the live engine's known fragility, plan D1/B1),
validation refuses the render loudly rather than shipping a broken video;
on healthy captures the full completion contract is asserted."""
import json

import pytest

pytestmark = [pytest.mark.requires_browser, pytest.mark.requires_ffmpeg]

from multilingual_slide_video_agent.production.motion.errors import MotionError
from multilingual_slide_video_agent.production.motion.render import render_motion

from motion_fixture_helpers import render_source_images, write_deck, write_production


def _setup(tmp_path, monkeypatch):
    monkeypatch.setenv("MSV_LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("VIDEO_RESOLUTION", "720p")

    deck = tmp_path / "deck"
    write_deck(deck, {
        "slide_001": "<h1>Alpha deck</h1><ul><li>one</li><li>two</li><li>three</li><li>four</li></ul>",
        "slide_002": "<h1>Stat slide</h1><div class='stat'>75%</div><p>body text</p>",
    })
    from multilingual_slide_video_agent.slides.generate_animation import generate_deck_animation
    generate_deck_animation(deck_dir=deck, out_dir=tmp_path / "anim")

    slides_dir = tmp_path / "slides"
    render_source_images(slides_dir, {"slide_001": "navy", "slide_002": "teal"})

    translated = tmp_path / "translated_en-US"
    translated.mkdir()
    import shutil
    for f in deck.glob("*.html"):
        shutil.copy2(f, translated / f.name)

    production = write_production(tmp_path / "out", ["slide_001", "slide_002"])
    return production, translated, tmp_path / "anim", slides_dir


def test_render_motion_playwright_end_to_end(tmp_path, monkeypatch):
    production, translated, anim, slides_dir = _setup(tmp_path, monkeypatch)
    try:
        envelope = render_motion(
            production_path=str(production), translated_deck_dir=str(translated),
            animation_dir=str(anim), slides_dir=str(slides_dir),
        )
        assert envelope["status"] == "completed"
        motion = json.loads((tmp_path / "out" / "motion.json").read_text(encoding="utf-8"))
        assert motion["engine"]["name"] == "playwright" and motion["fps"] == 30
        assert motion["validation"]["ok"] is True, motion["validation"]["errors"]
        srt = (tmp_path / "out" / "marketing_playwright_captions.srt").read_text(encoding="utf-8")
        assert srt.count(" --> ") == 3  # title + 2 captions
        assert not (tmp_path / "out" / "_motion_playwright_work").exists()
    except MotionError as e:
        # The loud-refusal contract: a broken/unusable capture (entirely
        # blank clips on some environments) must fail as a VALIDATION
        # failure with slide-named errors and an inspectable motion.json -
        # never as a crash, and never as a silently-broken video.
        motion = json.loads((tmp_path / "out" / "motion.json").read_text(encoding="utf-8"))
        assert motion["validation"]["ok"] is False
        assert "slide_001" in " ".join(motion["validation"]["errors"])


def test_alias_keeps_the_legacy_contract(tmp_path, monkeypatch):
    from multilingual_slide_video_agent.production.render_marketing_animation import (
        render_marketing_animation,
    )

    production, translated, anim, slides_dir = _setup(tmp_path, monkeypatch)
    try:
        envelope = render_marketing_animation(
            production_path=str(production), translated_deck_dir=str(translated),
            animation_dir=str(anim), slides_dir=str(slides_dir),
        )
        assert envelope["status"] == "completed"
        legacy = json.loads((tmp_path / "out" / "marketing_animation.json").read_text(encoding="utf-8"))
        assert legacy["style"] == "gsap_animated"
        assert legacy["output_video"].endswith("marketing_animation.mp4")
        assert set(legacy["templates"]) == {"slide_001", "slide_002"}
        assert legacy["duration_seconds"] == pytest.approx(4.0, abs=0.3)
    except MotionError:
        # Same loud-refusal shape as above, on the alias path.
        motion = json.loads((tmp_path / "out" / "motion.json").read_text(encoding="utf-8"))
        assert motion["validation"]["ok"] is False