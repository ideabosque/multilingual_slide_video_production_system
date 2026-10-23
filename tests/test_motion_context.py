"""MotionRenderContext construction from production.json + spec.json
(motion-engines-and-hardening-plan B2) - unit level, no ffmpeg/browser."""
import json

import pytest

from multilingual_slide_video_agent.production.motion.context import (
    MotionRenderContext_from_production,
)
from multilingual_slide_video_agent.production.motion.errors import MotionContextError

from motion_fixture_helpers import write_production


def _prepare(tmp_path, templates_by_slide=None, roles=None):
    deck = tmp_path / "deck"
    deck.mkdir()
    templates_by_slide = templates_by_slide or {"slide_001": "title_reveal", "slide_002": "stat_highlight"}
    from motion_fixture_helpers import make_minimal_animation_bundle
    make_minimal_animation_bundle(tmp_path / "anim", templates_by_slide)
    production = write_production(tmp_path / "out", list(templates_by_slide))
    roles_path = None
    if roles is not None:
        roles_path = tmp_path / "roles_en-US.json"
        roles_path.write_text(json.dumps(roles), encoding="utf-8")
    return production, templates_by_slide, roles_path


def test_context_built_from_production_and_spec(tmp_path):
    production, templates, _ = _prepare(tmp_path)
    ctx = MotionRenderContext_from_production(
        production_path=production,
        translated_deck_dir=tmp_path / "deck",
        animation_dir=tmp_path / "anim",
        slides_dir=tmp_path / "slides",
    )
    assert ctx.language == "en-US"
    assert [s.slide_id for s in ctx.slides] == ["slide_001", "slide_002"]
    assert [s.template for s in ctx.slides] == ["title_reveal", "stat_highlight"]
    assert ctx.total_duration == pytest.approx(4.0)
    assert ctx.title == "Motion {test} title"
    assert ctx.title_item["kind"] == "title"
    assert ctx.fps == 30  # motion.yaml's default
    assert ctx.slide_by_id("slide_002").duration == pytest.approx(1.5)


def test_roles_file_is_merged_into_slides(tmp_path):
    production, _, roles_path = _prepare(tmp_path, roles={
        "slides": [{
            "slide_id": "slide_002",
            "template": "stat_highlight",
            "roles": {"title": "Rendimiento", "stat": {"prefix": "", "value": 75, "suffix": "%"}},
        }],
    })
    ctx = MotionRenderContext_from_production(
        production_path=production, translated_deck_dir=tmp_path / "deck",
        animation_dir=tmp_path / "anim", slides_dir=tmp_path / "slides",
        roles_path=roles_path,
    )
    assert ctx.slide_by_id("slide_002").roles["stat"]["value"] == 75
    assert ctx.slide_by_id("slide_001").roles is None  # absent -> optional


def test_empty_timing_fails_loudly(tmp_path):
    production, _, _ = _prepare(tmp_path)
    doc = json.loads(production.read_text(encoding="utf-8"))
    doc["segment_timing"] = []
    production.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(MotionContextError, match="segment_timing"):
        MotionRenderContext_from_production(
            production_path=production, translated_deck_dir=tmp_path / "deck",
            animation_dir=tmp_path / "anim", slides_dir=tmp_path / "slides",
        )


def test_slide_without_template_fails_with_slide_named(tmp_path):
    production, templates, _ = _prepare(tmp_path)
    del templates["slide_002"]
    (tmp_path / "anim" / "spec.json").write_text(json.dumps({"slides": [
        {"slide_id": "slide_001", "template": templates.get("slide_001", "feature_callout")},
    ]}), encoding="utf-8")
    with pytest.raises(MotionContextError, match="slide_002"):
        MotionRenderContext_from_production(
            production_path=production, translated_deck_dir=tmp_path / "deck",
            animation_dir=tmp_path / "anim", slides_dir=tmp_path / "slides",
        )