"""Phase 5 (plan C4, C5): `validate-motion`'s guardrails, the per-slide
fallback at render time, and `inspect-layout`'s map. Exit criterion: bad
target, bounce ease, 5 flashes per second and a beat past the slide's end
are each rejected with a slide-named error; the fallback is verified."""
import copy
import json

import pytest
from click.testing import CliRunner

from multilingual_slide_video_agent.production.motion.clips import duration_tokens
from multilingual_slide_video_agent.slides.animation_templates import load_template_config
from multilingual_slide_video_agent.slides.design_system import load_design_system
from multilingual_slide_video_agent.slides.motion_checks import (
    brand_color_tokens, check_motion_design, slide_durations_from_productions, with_fallbacks,
)

from motion_fixture_helpers import write_deck

PRESETS = set(load_template_config("playful"))
TOKENS = duration_tokens(load_design_system())
BRAND = brand_color_tokens(load_design_system())

SLIDES = {
    "slide_001": "<h1>Alpha deck</h1><p>A short subtitle</p>"
                 "<div class='row'><div class='card'>one</div><div class='card'>two</div><div class='card'>three</div></div>",
    "slide_002": "<h2>Stat slide</h2><div class='stat'>75%</div><p>body text</p>"
                 "<svg width='100' height='20'><path class='wire' d='M0 10 L100 10' stroke='#000'/></svg>",
}
DURATIONS = {"slide_001": 10.0, "slide_002": 8.0}

GOOD = {
    "schema": "motion-design/v1",
    "deck_fingerprint": "FP",
    "slides": [
        {"slide_id": "slide_001", "preset": "title_reveal", "steps": [
            {"id": "hdr", "target": {"node": "slide_001#n0"}, "effect": "text_split", "by": "word"},
            {"id": "cards", "target": {"group": ".row > .card"}, "effect": "pop", "stagger": 0.15, "position": "hdr+=0.3"},
            {"target": {"node": "slide_001#n1"}, "effect": "highlight", "beat_at": 0.5},
        ]},
        {"slide_id": "slide_002", "preset": "stat_highlight", "steps": [
            {"id": "stat", "target": {"role": "stat"}, "effect": "count_up", "pop": True},
            {"target": {"selector": "svg path.wire"}, "effect": "draw_svg", "position": "stat+=0.5"},
            {"target": {"role": "stat"}, "effect": "emphasis", "beat_at": 0.6},
        ]},
    ],
}


@pytest.fixture
def deck(tmp_path):
    write_deck(tmp_path / "deck", SLIDES)
    return tmp_path / "deck"


def _check(doc, deck, *, durations=DURATIONS, layout=None, fingerprint="FP"):
    return check_motion_design(doc, deck_dir=deck, presets=PRESETS, tokens=TOKENS, brand_colors=BRAND,
                               layout_map=layout, slide_durations=durations, source_fingerprint=fingerprint)


def test_a_good_design_passes_every_check(deck):
    result = _check(GOOD, deck)
    assert result == {"ok": True, "errors": [], "slide_errors": {}, "warnings": ["no layout map: role targets are not checked"]}


def _bad(mutate):
    doc = copy.deepcopy(GOOD)
    mutate(doc)
    return doc


@pytest.mark.parametrize("name, mutate, slide, expected", [
    ("bad target", lambda d: d["slides"][0]["steps"][1].update(target={"group": ".row > .tile"}),
     "slide_001", "group '.row > .tile' matches no element"),
    ("missing node", lambda d: d["slides"][0]["steps"][0].update(target={"node": "slide_001#n42"}),
     "slide_001", "node 'slide_001#n42' is not in this slide"),
    ("bad selector", lambda d: d["slides"][1]["steps"][1].update(target={"selector": "svg >> path"}),
     "slide_002", "is not a valid CSS selector"),
    ("bounce ease", lambda d: d["slides"][0]["steps"][1].update(ease="bounce.out"),
     "slide_001", "never elastic or bounce"),
    ("5 flashes per second", lambda d: d["slides"][1]["steps"].extend(
        {"target": {"role": "stat"}, "effect": "emphasis", "position": 3 + i * 0.2} for i in range(5)),
     "slide_002", "flashes (emphasis/highlight) within one second"),
    ("beat past the end", lambda d: d["slides"][1]["steps"][2].update(beat_at=0.97, duration=1.0),
     "slide_002", "past the slide's end"),
    ("step after the end", lambda d: d["slides"][1]["steps"].append(
        {"target": {"role": "stat"}, "effect": "emphasis", "position": 9}),
     "slide_002", "after the slide ends"),
    ("off-brand colour", lambda d: d["slides"][0]["steps"][2].update(color="hot-pink"),
     "slide_001", "not a brand token"),
    ("slow entrance", lambda d: d["slides"][0]["steps"].append(
        {"target": {"node": "slide_001#n1"}, "effect": "reveal", "position": 5, "duration": 1}),
     "slide_001", "the entrance settles at 6.00s"),
    ("too much at once", lambda d: d["slides"][0]["steps"].extend(
        {"target": {"group": ".row > .card"}, "effect": "reveal", "position": 1} for _ in range(3)),
     "slide_001", "elements move at once"),
])
def test_guardrails_reject_with_a_slide_named_error(deck, name, mutate, slide, expected):
    result = _check(_bad(mutate), deck)
    assert not result["ok"]
    assert list(result["slide_errors"]) == [slide], (name, result)
    assert any(expected in e and e.startswith(slide) for e in result["slide_errors"][slide]), result["slide_errors"]


def test_a_design_for_another_deck_is_rejected_as_a_whole(deck):
    result = _check(GOOD, deck, fingerprint="OTHER")
    assert result["errors"] and "not this deck's" in result["errors"][0]


def test_a_broken_header_is_rejected_as_a_whole(deck):
    result = _check(_bad(lambda d: d.update(schema="motion-design/v9")), deck)
    assert result["errors"] and not result["slide_errors"]


def test_role_targets_are_checked_against_the_layout_map(deck):
    layout = {"slides": [{"slide_id": "slide_001", "roles": {"title": "Alpha deck", "body": []}},
                         {"slide_id": "slide_002", "roles": {"title": "Stat slide", "stat": None}}]}
    result = _check(GOOD, deck, layout=layout)
    assert list(result["slide_errors"]) == ["slide_002"]
    assert "role 'stat' resolves to nothing" in result["slide_errors"]["slide_002"][0]


def test_without_durations_timing_is_skipped_with_a_warning(deck):
    result = _check(_bad(lambda d: d["slides"][1]["steps"][2].update(beat_at=0.99, duration=4)), deck, durations=None)
    assert result["ok"] and any("timing and comfort checks were skipped" in w for w in result["warnings"])


def test_shortest_duration_across_languages_wins():
    productions = [{"segment_timing": [{"kind": "slide", "slide_id": "s1", "start_time": 0, "end_time": 9}]},
                   {"segment_timing": [{"kind": "slide", "slide_id": "s1", "start_time": 2, "end_time": 8}]}]
    assert slide_durations_from_productions(productions) == {"s1": 6}


def test_failing_slides_fall_back_to_their_preset():
    doc = copy.deepcopy(GOOD)
    doc["slides"].append({"slide_id": "slide_003", "preset": "nope", "steps": []})
    fallen = with_fallbacks(doc, {"slide_001": ["x"], "slide_003": ["y"]}, PRESETS)
    assert fallen["slides"][0] == {"slide_id": "slide_001", "preset": "title_reveal"}
    assert fallen["slides"][1] == GOOD["slides"][1]
    assert fallen["slides"][2] == {"slide_id": "slide_003"}      # bad preset: the slide's own template


def test_validate_motion_cli_names_failing_slides(deck, tmp_path):
    from multilingual_slide_video_agent.cli import main
    from multilingual_slide_video_agent.state import directory_fingerprint

    doc = _bad(lambda d: d["slides"][0]["steps"][1].update(ease="elastic.out(1, 0.3)"))
    doc["deck_fingerprint"] = directory_fingerprint(deck)
    design = tmp_path / "motion_design.json"
    design.write_text(json.dumps(doc), encoding="utf-8")
    result = CliRunner().invoke(main, ["slides", "validate-motion", "--design", str(design), "--deck-dir", str(deck)])
    payload = json.loads(result.output)
    assert result.exit_code == 1 and payload["ok"] is False
    assert payload["failing_slides"] == ["slide_001"] and "elastic" in payload["errors"][0]
    assert any("timing and comfort checks were skipped" in w for w in payload["warnings"])


@pytest.mark.requires_browser
def test_inspect_layout_maps_targets_and_annotates(deck, tmp_path):
    from multilingual_slide_video_agent.slides.layout_map import inspect_layout
    from multilingual_slide_video_agent.state import directory_fingerprint

    layout = inspect_layout(deck_dir=deck, out_path=tmp_path / "layout_map.json", annotate_dir=tmp_path / "ann",
                            viewport="1280x720")
    assert layout["deck_fingerprint"] == directory_fingerprint(deck)
    s1, s2 = layout["slides"]
    assert s1["elements"][0]["nodes"] == ["slide_001#n0"] and s1["elements"][0]["text"] == "Alpha deck"
    assert s1["elements"][0]["box"]["w"] > 0 and s1["elements"][0]["font_size"] > 20
    group = next(g for g in s1["groups"] if g["count"] == 3)
    assert group["selector"] == ".row > .card" and group["texts"] == ["one", "two", "three"]
    assert s2["svg_shapes"][0]["length"] == 100
    assert s2["roles"]["stat"]["value"] == 75
    assert (tmp_path / "ann" / "slide_001.png").exists()
    # the map's own roles feed the role check
    assert _check(GOOD, deck, layout=layout)["ok"]
    # the deck itself is untouched
    assert "data-motion-node" not in (deck / "slide_001.html").read_text(encoding="utf-8")


@pytest.mark.requires_node
@pytest.mark.requires_ffmpeg
def test_render_falls_back_per_slide_and_reports_it(tmp_path, monkeypatch):
    """A slide whose design fails in this language plays its preset; the
    render completes and the envelope and manifest name the slide."""
    from multilingual_slide_video_agent.production.motion import hyperframes_engine as hf
    from multilingual_slide_video_agent.production.motion.render import render_motion

    if hf.check_available():
        pytest.skip("; ".join(hf.check_available()))
    from test_hyperframes_engine import _ctx

    monkeypatch.setenv("MSV_LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("VIDEO_RESOLUTION", "720p")
    ctx = _ctx(tmp_path, slide_seconds=(2.0, 2.0))
    design = {"schema": "motion-design/v1", "deck_fingerprint": "fixture", "slides": [
        {"slide_id": "slide_001", "preset": "title_reveal",
         "steps": [{"target": {"selector": ".does-not-exist"}, "effect": "reveal"}]},
        {"slide_id": "slide_002", "steps": [{"target": {"role": "title"}, "effect": "text_split"}]},
    ]}
    path = tmp_path / "motion_design.json"
    path.write_text(json.dumps(design), encoding="utf-8")
    envelope = render_motion(production_path=str(ctx.production_path), translated_deck_dir=str(ctx.translated_deck_dir),
                             animation_dir=str(ctx.animation_dir), viewport="1280x720", engine_name="hyperframes",
                             motion_design_path=str(path), record_in_production=False)
    assert envelope["status"] == "completed"
    assert any("slide_001 falls back to its preset" in w for w in envelope["warnings"])
    motion = json.loads((ctx.production_path.parent / "video.motion.json").read_text(encoding="utf-8"))
    assert list(motion["motion_design"]["fallback"]) == ["slide_001"]
    assert motion["validation"]["ok"] is True
