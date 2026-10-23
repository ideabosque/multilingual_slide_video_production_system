"""The motion design language, `motion-design/v1` (motion-engines-and-
hardening-plan C3, Phase 4): the per-deck `motion_design.json` in which
Claude describes a deck's motion, its validator, and its resolution into
the steps and transitions every engine plays.

One interpreter plays every design: animation_runtime.js's step runner,
the same one that plays the template library. The templates are the
language's **presets**: a design slide can name a preset and use it as is,
give its own `steps`, add a `camera` move, and choose how it hands off to
the next slide (`transition_out`). Resolution happens here, once, so the
runtime only ever sees concrete steps.

Validation is structural (schema, vocabulary, bounds, step references) and
fails loudly naming the slide and step. Checking targets against the
deck's layout map, brand and comfort guardrails, and falling back to a
slide's preset are Phase 5 (C4, C5).
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

SCHEMA_ID = "motion-design/v1"

DURATION_TOKENS = ("fast", "base", "slow", "slide_enter", "slide_exit")
DURATION_SECONDS = (0.05, 4.0)

# Effect -> the parameters a design step may give it, besides the common
# keys in _STEP_KEYS. `from` is the entrance's starting state.
EFFECT_PARAMS: dict[str, set[str]] = {
    "reveal": {"blur"},
    "text_split": {"by"},
    "pop": set(),
    "beats": {"between", "first_max"},
    "count_up": {"pop"},
    "accent_line": set(),
    "draw_svg": set(),
    "highlight": {"mode", "color", "alpha"},
    "emphasis": {"scale"},
    "path_connect": {"to", "color", "width", "gap"},
    "exit": {"y"},
}
_FROM_EFFECTS = {"reveal", "text_split", "pop", "beats"}
_FROM_KEYS = {"opacity", "x", "y", "scale", "rotation"}
_STEP_KEYS = {"id", "target", "effect", "duration", "ease", "position", "beat_at", "stagger", "from", "params"}
_TARGET_KINDS = ("node", "group", "selector", "role")
_ROLES = {"title", "subtitle", "body", "diagram", "stat", "cta", "nodes", "slide"}

TRANSITION_TYPES = ("cut", "crossfade", "push", "wipe")
DIRECTIONS = ("left", "right", "up", "down")
TRANSITION_SECONDS = (0.2, 1.2)
CAMERA_EFFECTS = ("push_in", "pan")
CAMERA_MAX_SCALE = 1.08
EMPHASIS_MAX_SCALE = 1.15

# GSAP eases a design may use. No elastic or bounce: landed objects hold
# still (feedback: wobble read as shaking), and the brand register is
# ease-out. `back.out` is the playful style's springy entrance, amplitude
# capped so it overshoots once rather than wobbling.
_EASE_RE = re.compile(r"^(none|linear|(power[0-4]|sine|expo|circ)\.(in|out|inOut)|back\.out(\((\d+(\.\d+)?)\))?)$")
BACK_MAX_AMPLITUDE = 2.5

# A GSAP position: seconds, "<" / ">" with an optional offset, "+=0.2", or
# a label (an earlier step's id) with an optional offset.
_POSITION_RE = re.compile(r"^(?:(?P<label>[A-Za-z_][\w-]*)|[<>])?(?:[+-]=?\d+(\.\d+)?)?$")


class MotionDesignError(Exception):
    """A motion design that can't be played as written. The message names
    every problem with its slide and step."""


def _duration_ok(value: Any) -> bool:
    if isinstance(value, str):
        return value in DURATION_TOKENS
    return isinstance(value, (int, float)) and not isinstance(value, bool) and \
        DURATION_SECONDS[0] <= value <= DURATION_SECONDS[1]


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _check_ease(where: str, ease: Any, errors: list[str]) -> None:
    match = _EASE_RE.match(ease) if isinstance(ease, str) else None
    if not match:
        errors.append(f"{where}: ease {ease!r} is not allowed (ease-out family, sine, expo, circ, none, "
                      f"or back.out(<= {BACK_MAX_AMPLITUDE}); never elastic or bounce)")
    elif match.group(5) and float(match.group(5)) > BACK_MAX_AMPLITUDE:
        errors.append(f"{where}: back.out amplitude {match.group(5)} is over {BACK_MAX_AMPLITUDE}")


def _check_target(where: str, target: Any, errors: list[str]) -> None:
    if not isinstance(target, dict) or len(target) != 1 or next(iter(target)) not in _TARGET_KINDS:
        errors.append(f"{where}: target must be one of {{{', '.join(k + ': …' for k in _TARGET_KINDS)}}}, "
                      f"got {target!r}")
        return
    kind, value = next(iter(target.items()))
    if kind == "role":
        roles = value if isinstance(value, list) else [value]
        if not roles or any(r not in _ROLES for r in roles):
            errors.append(f"{where}: role must be one of {sorted(_ROLES)}, got {value!r}")
    elif not isinstance(value, str) or not value.strip():
        errors.append(f"{where}: target {kind} must be a non-empty string")


def _check_transition(where: str, tr: Any, errors: list[str]) -> None:
    if not isinstance(tr, dict):
        errors.append(f"{where}: must be an object")
        return
    unknown = set(tr) - {"type", "duration", "direction"}
    if unknown:
        errors.append(f"{where}: unknown keys {sorted(unknown)}")
    if tr.get("type") not in TRANSITION_TYPES:
        errors.append(f"{where}: type must be one of {list(TRANSITION_TYPES)}, got {tr.get('type')!r}")
    if "direction" in tr and tr["direction"] not in DIRECTIONS:
        errors.append(f"{where}: direction must be one of {list(DIRECTIONS)}")
    duration = tr.get("duration")
    if duration is not None:
        seconds_ok = _number(duration) and TRANSITION_SECONDS[0] <= duration <= TRANSITION_SECONDS[1]
        if not (duration in DURATION_TOKENS or seconds_ok):
            errors.append(f"{where}: duration must be a token {list(DURATION_TOKENS)} or "
                          f"{TRANSITION_SECONDS[0]}-{TRANSITION_SECONDS[1]} seconds")


def _check_step(where: str, step: Any, earlier_ids: set[str], errors: list[str]) -> None:
    if not isinstance(step, dict):
        errors.append(f"{where}: must be an object")
        return
    effect = step.get("effect")
    if effect not in EFFECT_PARAMS:
        errors.append(f"{where}: effect must be one of {sorted(EFFECT_PARAMS)}, got {effect!r}")
        return
    allowed = _STEP_KEYS | EFFECT_PARAMS[effect]
    unknown = set(step) - allowed
    if unknown:
        errors.append(f"{where}: unknown keys {sorted(unknown)} for effect {effect!r}")
    if "target" not in step:
        errors.append(f"{where}: target is required")
    else:
        _check_target(f"{where}.target", step["target"], errors)
    if "duration" in step and not _duration_ok(step["duration"]):
        errors.append(f"{where}: duration must be a token {list(DURATION_TOKENS)} or "
                      f"{DURATION_SECONDS[0]}-{DURATION_SECONDS[1]} seconds")
    if "ease" in step:
        _check_ease(where, step["ease"], errors)
    if "stagger" in step and not (_number(step["stagger"]) and 0 <= step["stagger"] <= 1):
        errors.append(f"{where}: stagger must be 0-1 seconds")
    if "beat_at" in step:
        if "position" in step:
            errors.append(f"{where}: give either position or beat_at, not both")
        if not (_number(step["beat_at"]) and 0 <= step["beat_at"] <= 1):
            errors.append(f"{where}: beat_at must be a fraction of the slide, 0-1")
    if "position" in step:
        position = step["position"]
        if _number(position):
            if position < 0:
                errors.append(f"{where}: position must not be negative")
        elif not isinstance(position, str) or not _POSITION_RE.match(position):
            errors.append(f"{where}: position {position!r} is not a GSAP position")
        else:
            label = _POSITION_RE.match(position).group("label")
            if label and label not in earlier_ids:
                errors.append(f"{where}: position {position!r} refers to {label!r}, which is not an earlier step's id")
    if "from" in step:
        start = step["from"]
        keys = _FROM_KEYS | ({"blur"} if effect == "reveal" else set())
        if effect not in _FROM_EFFECTS:
            errors.append(f"{where}: effect {effect!r} takes no 'from'")
        elif not isinstance(start, dict) or set(start) - keys or not all(_number(v) for v in start.values()):
            errors.append(f"{where}: from must map {sorted(keys)} to numbers")
    if "params" in step:
        errors.append(f"{where}: put effect parameters on the step itself, not under 'params'")
    if effect == "text_split" and step.get("by", "word") not in ("word", "char", "line"):
        errors.append(f"{where}: by must be word, char or line")
    if effect == "highlight":
        if step.get("mode", "sweep") not in ("sweep", "color"):
            errors.append(f"{where}: highlight mode must be sweep or color")
        if "alpha" in step and not (_number(step["alpha"]) and 0.05 <= step["alpha"] <= 0.8):
            errors.append(f"{where}: highlight alpha must be 0.05-0.8")
    if "color" in step and not (isinstance(step["color"], str) and re.match(r"^[a-z][a-z0-9-]*$", step["color"])):
        errors.append(f"{where}: color must be a brand colour token name such as 'accent-signal'")
    if effect == "emphasis" and "scale" in step and not (_number(step["scale"]) and 1 < step["scale"] <= EMPHASIS_MAX_SCALE):
        errors.append(f"{where}: emphasis scale must be over 1 and at most {EMPHASIS_MAX_SCALE}")
    if effect == "path_connect":
        if "to" not in step:
            errors.append(f"{where}: path_connect needs 'to', the target the arrow points at")
        else:
            _check_target(f"{where}.to", step["to"], errors)
    if effect == "beats" and "between" in step:
        between = step["between"]
        if not (isinstance(between, list) and len(between) == 2 and all(_number(v) for v in between)
                and 0 <= between[0] <= between[1] <= 1):
            errors.append(f"{where}: between must be [start, end] fractions of the slide, 0-1")


def validate_motion_design(doc: Any, *, slide_ids: list[str] | None = None,
                           presets: set[str] | None = None) -> list[str]:
    """Every problem in a motion design, each naming its slide and step;
    an empty list means it can be played. `slide_ids` (the deck's slides)
    and `presets` (template names) are checked when given."""
    errors: list[str] = []
    if not isinstance(doc, dict):
        return ["motion design must be a JSON object"]
    if doc.get("schema") != SCHEMA_ID:
        errors.append(f"schema must be {SCHEMA_ID!r}, got {doc.get('schema')!r}")
    if not isinstance(doc.get("deck_fingerprint"), str) or not doc["deck_fingerprint"]:
        errors.append("deck_fingerprint is required: the fingerprint of the deck the design was made for")
    unknown = set(doc) - {"schema", "deck_fingerprint", "style", "transitions", "slides"}
    if unknown:
        errors.append(f"unknown top-level keys {sorted(unknown)}")
    style = doc.get("style", {})
    if not isinstance(style, dict) or style.get("energy", "balanced") not in ("calm", "balanced", "lively"):
        errors.append("style.energy must be calm, balanced or lively")
    transitions = doc.get("transitions", {})
    if not isinstance(transitions, dict) or set(transitions) - {"default"}:
        errors.append("transitions may only hold 'default'")
    elif "default" in transitions:
        _check_transition("transitions.default", transitions["default"], errors)

    slides = doc.get("slides")
    if not isinstance(slides, list) or not slides:
        errors.append("slides must be a non-empty list")
        return errors
    seen: set[str] = set()
    for i, entry in enumerate(slides):
        if not isinstance(entry, dict) or not isinstance(entry.get("slide_id"), str):
            errors.append(f"slides[{i}]: needs a slide_id")
            continue
        sid = entry["slide_id"]
        where = sid
        if sid in seen:
            errors.append(f"{where}: appears more than once")
        seen.add(sid)
        if slide_ids is not None and sid not in slide_ids:
            errors.append(f"{where}: not a slide in this deck")
        unknown = set(entry) - {"slide_id", "preset", "intent", "steps", "camera", "transition_out"}
        if unknown:
            errors.append(f"{where}: unknown keys {sorted(unknown)}")
        if "preset" in entry and presets is not None and entry["preset"] not in presets:
            errors.append(f"{where}: preset {entry['preset']!r} is not one of {sorted(presets)}")
        steps = entry.get("steps")
        if steps is not None:
            if not isinstance(steps, list) or not steps:
                errors.append(f"{where}: steps must be a non-empty list (omit it to play the preset)")
            else:
                ids: set[str] = set()
                for j, step in enumerate(steps):
                    step_where = f"{where}.steps[{j}]" + (f" ({step['id']})" if isinstance(step, dict) and step.get("id") else "")
                    _check_step(step_where, step, ids, errors)
                    if isinstance(step, dict) and step.get("id"):
                        if step["id"] in ids:
                            errors.append(f"{step_where}: duplicate step id")
                        ids.add(step["id"])
        camera = entry.get("camera")
        if camera is not None:
            if not isinstance(camera, dict) or camera.get("effect") not in CAMERA_EFFECTS:
                errors.append(f"{where}.camera: effect must be one of {list(CAMERA_EFFECTS)}")
            else:
                if set(camera) - {"effect", "scale", "x", "y", "over"}:
                    errors.append(f"{where}.camera: unknown keys {sorted(set(camera) - {'effect', 'scale', 'x', 'y', 'over'})}")
                if "scale" in camera and not (_number(camera["scale"]) and 1 <= camera["scale"] <= CAMERA_MAX_SCALE):
                    errors.append(f"{where}.camera: scale must be 1-{CAMERA_MAX_SCALE}")
                if camera.get("over", "slide") != "slide":
                    errors.append(f"{where}.camera: over must be 'slide'")
                for axis in ("x", "y"):
                    if axis in camera and not (_number(camera[axis]) and abs(camera[axis]) <= 120):
                        errors.append(f"{where}.camera: {axis} must be at most 120px either way")
        if "transition_out" in entry:
            _check_transition(f"{where}.transition_out", entry["transition_out"], errors)
    return errors


def design_fingerprint(path: str | Path) -> str:
    """The design file's content fingerprint: what the motion approval gate
    is keyed to, so any edit reopens it."""
    import hashlib

    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]


def load_motion_design(path: str | Path, *, slide_ids: list[str] | None = None,
                       presets: set[str] | None = None) -> dict[str, Any]:
    """Read and validate a motion design; raises MotionDesignError listing
    every problem."""
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise MotionDesignError(f"can't read motion design {path}: {e}") from e
    errors = validate_motion_design(doc, slide_ids=slide_ids, presets=presets)
    if errors:
        raise MotionDesignError(f"motion design {path} is invalid:\n- " + "\n- ".join(errors))
    return doc


def _runtime_step(step: dict[str, Any]) -> dict[str, Any]:
    """A design step in the runtime's step shape: `from` and the effect's
    own keys become `params`, and `beat_at` a beat position. A step with an
    id gets a timeline label, so later steps can be placed relative to it."""
    params: dict[str, Any] = dict(step.get("from") or {})
    for key in EFFECT_PARAMS[step["effect"]]:
        if key in step:
            params[key] = step[key]
    if "stagger" in step:
        params["stagger"] = step["stagger"]
    if step["effect"] == "beats" and "between" in params:
        params["from"], params["to"] = params.pop("between")
    out: dict[str, Any] = {"target": step["target"], "effect": step["effect"], "params": params}
    for key in ("id", "duration", "ease"):
        if key in step:
            out[key] = step[key]
    if step.get("id"):
        out["label"] = step["id"]
    if "beat_at" in step:
        out["position"] = f"beat:{step['beat_at']}"
    elif "position" in step:
        out["position"] = step["position"]
    return out


def slide_steps(entry: dict[str, Any] | None, preset_steps: list[dict[str, Any]], *,
                drop_exit: bool = False) -> list[dict[str, Any]]:
    """The concrete steps the runtime plays for one slide: the design's own
    steps, else a copy of its preset's, plus its camera move. A camera move
    replaces the preset's own (drift), and `drop_exit` removes exits, since
    a transition to the next slide replaces them."""
    entry = entry or {}
    if entry.get("steps"):
        steps = [_runtime_step(s) for s in entry["steps"]]
    else:
        steps = copy.deepcopy(preset_steps)
    camera = entry.get("camera")
    if camera:
        steps = [s for s in steps if s.get("effect") != "drift"]
        params = {"scale": camera.get("scale", 1.04)}
        if camera["effect"] == "pan":
            params.update({"x": camera.get("x", -40), "y": camera.get("y", 0)})
        steps.append({"target": {"role": "slide"}, "effect": "camera", "params": params})
    if drop_exit:
        steps = [s for s in steps if s.get("effect") != "exit"]
    return steps


def entries_by_slide(doc: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    return {e["slide_id"]: e for e in (doc or {}).get("slides", [])}


def _transition_seconds(tr: dict[str, Any], tokens: dict[str, float]) -> float:
    duration = tr.get("duration", "slide_enter")
    return float(tokens[duration]) if isinstance(duration, str) else float(duration)


def plan_transitions(clip_ids: list[str], frame_counts: list[int], doc: dict[str, Any] | None,
                     fps: int, tokens: dict[str, float]) -> list[dict[str, Any]]:
    """Per clip: how a transition into and out of it overlaps the clips
    next to it. A transition of d frames at a boundary takes d // 2 frames
    before it (the incoming clip starts early: its `lead`) and the rest
    after it (the outgoing clip runs on: its `tail`), so the boundary - and
    every slide's narration-aligned start - stays on its frame, and the
    total length is unchanged. A transition never takes more than half of
    either clip.

    `clip_ids` names each timing item ("title" for the title card); a
    boundary's transition is the outgoing slide's `transition_out`, else
    the design's default, else a cut."""
    entries = entries_by_slide(doc)
    default = ((doc or {}).get("transitions") or {}).get("default") or {"type": "cut"}
    plans = [{"lead": 0, "tail": 0, "in": None, "out": None} for _ in clip_ids]
    for k in range(len(clip_ids) - 1):
        tr = entries.get(clip_ids[k], {}).get("transition_out") or default
        if tr.get("type", "cut") == "cut":
            continue
        frames = round(_transition_seconds(tr, tokens) * fps)
        frames = min(frames, frame_counts[k] // 2, frame_counts[k + 1] // 2)
        if frames < 2:
            continue
        before = frames // 2
        spec = {"type": tr["type"], "direction": tr.get("direction", "left"), "frames": frames}
        plans[k + 1]["lead"] = before
        plans[k + 1]["in"] = spec
        plans[k]["tail"] = frames - before
        plans[k]["out"] = dict(spec)
    return plans


def json_schema() -> dict[str, Any]:
    """A JSON Schema for motion-design/v1, generated from the vocabulary
    above (the validator's own tables), so the language reference the
    motion-design skill reads can't drift from what is accepted."""
    duration = {"oneOf": [{"enum": list(DURATION_TOKENS)},
                          {"type": "number", "minimum": DURATION_SECONDS[0], "maximum": DURATION_SECONDS[1]}]}
    target = {"type": "object", "minProperties": 1, "maxProperties": 1, "properties": {
        "node": {"type": "string", "description": "an extract-text node id, e.g. slide_004#n7"},
        "group": {"type": "string", "description": "a CSS selector for a repeated-sibling group"},
        "selector": {"type": "string", "description": "a CSS selector"},
        "role": {"enum": sorted(_ROLES)},
    }, "additionalProperties": False}
    transition = {"type": "object", "required": ["type"], "additionalProperties": False, "properties": {
        "type": {"enum": list(TRANSITION_TYPES)},
        "direction": {"enum": list(DIRECTIONS)},
        "duration": {"oneOf": [{"enum": list(DURATION_TOKENS)},
                               {"type": "number", "minimum": TRANSITION_SECONDS[0], "maximum": TRANSITION_SECONDS[1]}]},
    }}
    step_variants = []
    for effect, params in sorted(EFFECT_PARAMS.items()):
        properties: dict[str, Any] = {
            "effect": {"const": effect}, "id": {"type": "string"}, "target": target,
            "duration": duration, "ease": {"type": "string"}, "stagger": {"type": "number", "minimum": 0, "maximum": 1},
            "position": {"type": ["number", "string"]}, "beat_at": {"type": "number", "minimum": 0, "maximum": 1},
        }
        if effect in _FROM_EFFECTS:
            properties["from"] = {"type": "object", "additionalProperties": {"type": "number"}}
        for param in sorted(params):
            properties[param] = target if param == "to" else {}
        step_variants.append({"type": "object", "required": ["effect", "target"],
                              "properties": properties, "additionalProperties": False})
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": SCHEMA_ID,
        "type": "object",
        "required": ["schema", "deck_fingerprint", "slides"],
        "additionalProperties": False,
        "properties": {
            "schema": {"const": SCHEMA_ID},
            "deck_fingerprint": {"type": "string"},
            "style": {"type": "object", "properties": {
                "energy": {"enum": ["calm", "balanced", "lively"]}, "notes": {"type": "string"}}},
            "transitions": {"type": "object", "properties": {"default": transition}, "additionalProperties": False},
            "slides": {"type": "array", "minItems": 1, "items": {
                "type": "object", "required": ["slide_id"], "additionalProperties": False, "properties": {
                    "slide_id": {"type": "string"},
                    "preset": {"type": "string"},
                    "intent": {"type": "string"},
                    "steps": {"type": "array", "minItems": 1, "items": {"oneOf": step_variants}},
                    "camera": {"type": "object", "required": ["effect"], "properties": {
                        "effect": {"enum": list(CAMERA_EFFECTS)},
                        "scale": {"type": "number", "minimum": 1, "maximum": CAMERA_MAX_SCALE},
                        "x": {"type": "number"}, "y": {"type": "number"}, "over": {"const": "slide"}}},
                    "transition_out": transition,
                }}},
        },
    }
