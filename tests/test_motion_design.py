"""motion-design/v1 (plan C3, Phase 4): the validator, resolution into
runtime steps, transition planning and the generated JSON Schema. No
browser needed; the runtime side is in test_motion_design_runtime.py."""
import copy

import pytest

from multilingual_slide_video_agent.slides import motion_design as md
from multilingual_slide_video_agent.slides.animation_templates import load_template_config

PRESETS = set(load_template_config("calm"))
SLIDES = ["slide_001", "slide_002", "slide_003"]

GOOD = {
    "schema": "motion-design/v1",
    "deck_fingerprint": "content-v1:abc",
    "style": {"energy": "lively", "notes": "Build the argument left to right."},
    "transitions": {"default": {"type": "crossfade", "duration": "slide_exit"}},
    "slides": [
        {"slide_id": "slide_001", "preset": "title_reveal"},
        {
            "slide_id": "slide_002",
            "preset": "diagram_build",
            "intent": "Draw the flow, then point at the tenant boundary.",
            "steps": [
                {"id": "hdr", "target": {"node": "slide_002#n0"}, "effect": "text_split", "by": "word",
                 "from": {"y": 24, "opacity": 0}, "stagger": 0.04, "duration": "slide_enter"},
                {"id": "cards", "target": {"group": ".layer-stack > .layer"}, "effect": "reveal",
                 "from": {"x": -40}, "stagger": 0.12, "position": "hdr+=0.1"},
                {"id": "wires", "target": {"selector": "svg path.connector"}, "effect": "draw_svg", "position": "cards"},
                {"id": "focus", "target": {"node": "slide_002#n7"}, "effect": "highlight", "beat_at": 0.55,
                 "duration": "base"},
                {"target": {"role": "nodes"}, "effect": "path_connect", "to": {"role": "stat"}, "beat_at": 0.7},
                {"target": {"role": "stat"}, "effect": "emphasis", "scale": 1.08, "beat_at": 0.8},
            ],
            "camera": {"effect": "push_in", "scale": 1.04, "over": "slide"},
            "transition_out": {"type": "push", "direction": "left"},
        },
    ],
}


def _errors(doc):
    return md.validate_motion_design(doc, slide_ids=SLIDES, presets=PRESETS)


def test_a_good_design_validates():
    assert _errors(GOOD) == []


@pytest.mark.parametrize("mutate, expected", [
    (lambda d: d.update(schema="motion-design/v2"), "schema must be"),
    (lambda d: d.pop("deck_fingerprint"), "deck_fingerprint is required"),
    (lambda d: d["slides"].append({"slide_id": "slide_099"}), "slide_099: not a slide in this deck"),
    (lambda d: d["slides"].append({"slide_id": "slide_001"}), "slide_001: appears more than once"),
    (lambda d: d["slides"][0].update(preset="spin_cycle"), "preset 'spin_cycle' is not one of"),
    (lambda d: d["slides"][1]["steps"][0].update(effect="wobble"), "slide_002.steps[0] (hdr): effect must be one of"),
    (lambda d: d["slides"][1]["steps"][0].update(ease="elastic.out(1, 0.3)"), "never elastic or bounce"),
    (lambda d: d["slides"][1]["steps"][0].update(ease="back.out(4)"), "back.out amplitude 4 is over"),
    (lambda d: d["slides"][1]["steps"][1].update(position="nope+=0.1"), "refers to 'nope', which is not an earlier step's id"),
    (lambda d: d["slides"][1]["steps"][0].update(position="wires"), "refers to 'wires'"),   # a later step
    (lambda d: d["slides"][1]["steps"][3].update(beat_at=1.4), "beat_at must be a fraction"),
    (lambda d: d["slides"][1]["steps"][3].update(position=1), "either position or beat_at"),
    (lambda d: d["slides"][1]["steps"][0].update(target={"text": "Hello"}), "target must be one of"),
    (lambda d: d["slides"][1]["steps"][0].update(target={"role": "headline"}), "role must be one of"),
    (lambda d: d["slides"][1]["steps"][0].update(duration=9), "duration must be a token"),
    (lambda d: d["slides"][1]["steps"][0].update(by="sentence"), "by must be word, char or line"),
    (lambda d: d["slides"][1]["steps"][2].update(**{"from": {"y": 10}}), "takes no 'from'"),
    (lambda d: d["slides"][1]["steps"][3].update(color="#ff0000"), "brand colour token name"),
    (lambda d: d["slides"][1]["steps"][4].pop("to"), "path_connect needs 'to'"),
    (lambda d: d["slides"][1]["steps"][5].update(scale=1.5), "emphasis scale must be over 1 and at most 1.15"),
    (lambda d: d["slides"][1]["steps"][0].update(params={"y": 3}), "not under 'params'"),
    (lambda d: d["slides"][1]["steps"][1].update(spin=True), "unknown keys ['spin']"),
    (lambda d: d["slides"][1]["camera"].update(scale=1.3), "camera: scale must be 1-1.08"),
    (lambda d: d["slides"][1]["transition_out"].update(type="spin"), "type must be one of"),
    (lambda d: d["transitions"]["default"].update(duration=5), "duration must be a token"),
])
def test_invalid_designs_are_rejected_naming_slide_and_step(mutate, expected):
    doc = copy.deepcopy(GOOD)
    mutate(doc)
    errors = _errors(doc)
    assert any(expected in e for e in errors), errors


def test_load_motion_design_lists_every_problem(tmp_path):
    doc = copy.deepcopy(GOOD)
    doc["slides"][1]["steps"][0]["effect"] = "wobble"
    doc["slides"][1]["camera"]["scale"] = 2
    path = tmp_path / "motion_design.json"
    path.write_text(__import__("json").dumps(doc), encoding="utf-8")
    with pytest.raises(md.MotionDesignError) as err:
        md.load_motion_design(path, slide_ids=SLIDES, presets=PRESETS)
    assert "wobble" in str(err.value) and "camera: scale" in str(err.value)


def test_design_steps_resolve_to_the_runtime_step_shape():
    entry = GOOD["slides"][1]
    steps = md.slide_steps(entry, preset_steps=[{"role": "title", "effect": "reveal"}])
    hdr, cards, wires, focus, connect, pulse, camera = steps
    assert hdr == {"target": {"node": "slide_002#n0"}, "effect": "text_split", "id": "hdr", "label": "hdr",
                   "duration": "slide_enter", "params": {"y": 24, "opacity": 0, "by": "word", "stagger": 0.04}}
    assert cards["position"] == "hdr+=0.1" and cards["params"] == {"x": -40, "stagger": 0.12}
    assert focus["position"] == "beat:0.55"
    assert connect["params"] == {"to": {"role": "stat"}}
    assert pulse["params"] == {"scale": 1.08}
    # the camera move is appended as a whole-slide step
    assert camera == {"target": {"role": "slide"}, "effect": "camera", "params": {"scale": 1.04}}


def test_a_design_slide_without_steps_plays_a_copy_of_its_preset():
    preset = load_template_config("playful")["stat_highlight"]["steps"]
    steps = md.slide_steps({"slide_id": "s"}, preset)
    assert steps == preset and steps is not preset
    # a camera move replaces the preset's own drift; a transition replaces its exit
    steps = md.slide_steps({"slide_id": "s", "camera": {"effect": "pan", "x": -60}}, preset, drop_exit=True)
    effects = [s["effect"] for s in steps]
    assert "drift" not in effects and "exit" not in effects and effects[-1] == "camera"
    assert steps[-1]["params"] == {"scale": 1.04, "x": -60, "y": 0}


def test_beats_between_maps_to_the_runtime_fractions():
    step = md._runtime_step({"target": {"role": "body"}, "effect": "beats", "between": [0.1, 0.5]})
    assert step["params"] == {"from": 0.1, "to": 0.5}


TOKENS = {"fast": 0.12, "base": 0.16, "slow": 0.2, "slide_enter": 0.48, "slide_exit": 0.32}


def test_transitions_overlap_neighbours_without_moving_any_boundary():
    doc = {"transitions": {"default": {"type": "crossfade", "duration": 0.5}},
           "slides": [{"slide_id": "slide_001", "transition_out": {"type": "push", "direction": "up", "duration": 0.4}},
                      {"slide_id": "slide_002", "transition_out": {"type": "cut"}}]}
    plans = md.plan_transitions(["title", "slide_001", "slide_002", "slide_003"], [30, 90, 90, 90], doc, 30, TOKENS)
    # title -> slide_001: the default crossfade, 15 frames: 7 before the boundary, 8 after
    assert plans[0] == {"lead": 0, "tail": 8, "in": None, "out": {"type": "crossfade", "direction": "left", "frames": 15}}
    assert plans[1]["lead"] == 7 and plans[1]["in"]["type"] == "crossfade"
    # slide_001 -> slide_002: its own push, 12 frames
    assert plans[1]["tail"] == 6 and plans[1]["out"] == {"type": "push", "direction": "up", "frames": 12}
    assert plans[2]["lead"] == 6
    # slide_002 -> slide_003: a cut
    assert plans[2]["tail"] == 0 and plans[3]["lead"] == 0 and plans[3]["in"] is None


def test_a_transition_never_takes_more_than_half_a_clip():
    doc = {"transitions": {"default": {"type": "wipe", "duration": 1.2}}, "slides": []}
    plans = md.plan_transitions(["a", "b"], [10, 90], doc, 30, TOKENS)
    assert plans[0]["out"]["frames"] == 5 and plans[0]["tail"] + plans[1]["lead"] == 5
    # under two frames, it's a cut
    plans = md.plan_transitions(["a", "b"], [3, 90], doc, 30, TOKENS)
    assert plans[0]["out"] is None and plans[1]["lead"] == 0


def test_no_design_means_no_transitions():
    plans = md.plan_transitions(["title", "slide_001"], [30, 60], None, 30, TOKENS)
    assert all(p == {"lead": 0, "tail": 0, "in": None, "out": None} for p in plans)


def test_json_schema_is_generated_from_the_vocabulary():
    schema = md.json_schema()
    assert schema["$id"] == md.SCHEMA_ID
    variants = schema["properties"]["slides"]["items"]["properties"]["steps"]["items"]["oneOf"]
    effects = {v["properties"]["effect"]["const"] for v in variants}
    assert effects == set(md.EFFECT_PARAMS)
    by_effect = {v["properties"]["effect"]["const"]: v for v in variants}
    assert "by" in by_effect["text_split"]["properties"] and "from" in by_effect["reveal"]["properties"]
    assert "from" not in by_effect["draw_svg"]["properties"]
