import json

import pytest

from multilingual_slide_video_agent.slides.animation_templates import load_template_config
from multilingual_slide_video_agent.slides.generate_animation import (
    ANIMATION_JS_NAME,
    DESIGN_TOKENS_CSS_NAME,
    GSAP_JS_NAME,
    SPEC_FILE_NAME,
    TEMPLATES_CONFIG_JS_NAME,
    GenerateAnimationError,
    generate_deck_animation,
)


@pytest.fixture
def deck_dir(tmp_path):
    deck = tmp_path / "deck"
    deck.mkdir()
    (deck / "slide_001.html").write_text("<html><body><h1>Intro</h1></body></html>", encoding="utf-8")
    (deck / "slide_002.html").write_text("<html><body><h1>Outro</h1></body></html>", encoding="utf-8")
    return deck


def test_generate_deck_animation_writes_expected_bundle(deck_dir, tmp_path):
    out_dir = tmp_path / "animation"
    manifest = generate_deck_animation(deck_dir=deck_dir, out_dir=out_dir)

    assert (out_dir / ANIMATION_JS_NAME).exists()
    assert (out_dir / GSAP_JS_NAME).exists()
    assert (out_dir / DESIGN_TOKENS_CSS_NAME).exists()
    assert (out_dir / SPEC_FILE_NAME).exists()

    spec = json.loads((out_dir / SPEC_FILE_NAME).read_text(encoding="utf-8"))
    assert spec["slides"][0]["template"] == "title_reveal"
    assert spec["slides"][1]["template"] == "closing"
    assert manifest["slides"][0]["slide_id"] == "slide_001"


def test_generate_deck_animation_writes_declarative_templates_config(deck_dir, tmp_path):
    out_dir = tmp_path / "animation"
    generate_deck_animation(deck_dir=deck_dir, out_dir=out_dir)

    templates_js = (out_dir / TEMPLATES_CONFIG_JS_NAME).read_text(encoding="utf-8")
    assert templates_js.startswith("window.__ANIMATION_TEMPLATES__ = ")
    embedded = json.loads(templates_js[len("window.__ANIMATION_TEMPLATES__ = "):-1])
    # The bundle embeds the same config animation_runtime.js's generic
    # engine will read at capture time - not a copy that can drift.
    assert embedded == load_template_config()


def test_generate_deck_animation_uses_slide_analysis_descriptions(deck_dir, tmp_path):
    analysis_path = tmp_path / "slide_analysis.json"
    analysis_path.write_text(json.dumps({
        "slides": [
            {"slide_id": "slide_001", "slide_description": "Intro"},
            {"slide_id": "slide_002", "slide_description": "A 25% improvement"},
        ]
    }), encoding="utf-8")
    manifest = generate_deck_animation(deck_dir=deck_dir, out_dir=tmp_path / "animation", slide_analysis_path=analysis_path)
    # slide_002 is still the last slide, so "closing" (position) wins over "stat_highlight" (text) - both are
    # valid per the heuristic's precedence (position checked first); this just confirms it didn't error out.
    assert manifest["slides"][1]["template"] == "closing"


def test_spec_override_is_validated(deck_dir, tmp_path):
    with pytest.raises(GenerateAnimationError):
        generate_deck_animation(
            deck_dir=deck_dir, out_dir=tmp_path / "animation",
            spec_override={"slide_001": "not_a_real_template", "slide_002": "closing"},
        )


def test_spec_override_must_cover_every_slide(deck_dir, tmp_path):
    with pytest.raises(GenerateAnimationError):
        generate_deck_animation(
            deck_dir=deck_dir, out_dir=tmp_path / "animation",
            spec_override={"slide_001": "title_reveal"},
        )


def test_spec_override_is_honored_when_valid(deck_dir, tmp_path):
    manifest = generate_deck_animation(
        deck_dir=deck_dir, out_dir=tmp_path / "animation",
        spec_override={"slide_001": "feature_callout", "slide_002": "stat_highlight"},
    )
    templates = {s["slide_id"]: s["template"] for s in manifest["slides"]}
    assert templates == {"slide_001": "feature_callout", "slide_002": "stat_highlight"}


def test_visual_role_from_slide_analysis_drives_selection(deck_dir, tmp_path):
    analysis_path = tmp_path / "slide_analysis.json"
    analysis_path.write_text(json.dumps({
        "slides": [
            {"slide_id": "slide_001", "slide_description": "Intro", "visual_role": "diagram_build"},
            {"slide_id": "slide_002", "slide_description": "Outro"},
        ]
    }), encoding="utf-8")
    manifest = generate_deck_animation(deck_dir=deck_dir, out_dir=tmp_path / "animation", slide_analysis_path=analysis_path)
    templates = {s["slide_id"]: s["template"] for s in manifest["slides"]}
    # slide_001 would normally be title_reveal (it's first) - visual_role overrides that.
    assert templates == {"slide_001": "diagram_build", "slide_002": "closing"}

    used = {s["slide_id"]: s["visual_role_used"] for s in manifest["slides"]}
    assert used == {"slide_001": True, "slide_002": False}


def test_invalid_visual_role_in_slide_analysis_fails_loudly(deck_dir, tmp_path):
    analysis_path = tmp_path / "slide_analysis.json"
    analysis_path.write_text(json.dumps({
        "slides": [
            {"slide_id": "slide_001", "slide_description": "Intro", "visual_role": "not_a_real_template"},
            {"slide_id": "slide_002", "slide_description": "Outro"},
        ]
    }), encoding="utf-8")
    with pytest.raises(GenerateAnimationError):
        generate_deck_animation(deck_dir=deck_dir, out_dir=tmp_path / "animation", slide_analysis_path=analysis_path)


def test_spec_override_marks_visual_role_used_as_false(deck_dir, tmp_path):
    # A --spec override always wins over visual_role, and should be
    # reported honestly as not having come from visual_role.
    analysis_path = tmp_path / "slide_analysis.json"
    analysis_path.write_text(json.dumps({
        "slides": [
            {"slide_id": "slide_001", "slide_description": "Intro", "visual_role": "diagram_build"},
            {"slide_id": "slide_002", "slide_description": "Outro"},
        ]
    }), encoding="utf-8")
    manifest = generate_deck_animation(
        deck_dir=deck_dir, out_dir=tmp_path / "animation", slide_analysis_path=analysis_path,
        spec_override={"slide_001": "closing", "slide_002": "closing"},
    )
    assert all(s["visual_role_used"] is False for s in manifest["slides"])
