"""`msv slides validate-motion` (motion-engines-and-hardening-plan C5, Phase
5): the checks a motion design must pass before it renders, beyond its
schema (motion_design.py).

1. Schema - motion_design.validate_motion_design.
2. Targets - every node, group and selector matches an element in the deck
   (the same tagged HTML the engines render), and every role resolved on
   that slide (the layout map's roles, when given). The design's
   `deck_fingerprint` must be this deck's.
3. Brand - colours are design-system tokens. Eases and durations are
   already bounded by the schema.
4. Comfort - at most 3 flashes (`emphasis`, `highlight`) per second
   (WCAG 2.3.1), at most 6 elements moving at once, and the entrance
   choreography settles within 40% of the slide's shortest expected
   duration, so viewers have time to read.
5. Timing - no step starts after its slide ends, and a beat step has its
   own duration left before the end.

Timing checks need slide durations: production.json `segment_timing`
from one or more languages (the shortest wins). Without them only checks
1-3 run, with a warning.

Problems are reported per slide, so the renderer can fall back to a
failing slide's preset in that language only (C5, C6). Problems with the
design as a whole (its schema header, its fingerprint) fail everything.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

from multilingual_slide_video_agent.slides import motion_design as md
from multilingual_slide_video_agent.slides.extract_text import list_slide_files, tag_text_nodes

MAX_FLASHES_PER_SECOND = 3
MAX_MOVING_ELEMENTS = 6
SETTLE_FRACTION = 0.4
FLASH_EFFECTS = {"emphasis", "highlight"}
# Effects that bring content in at the start, as opposed to beats timed to
# the narration (`beat_at`, `beats`) and whole-slide moves.
_ENTRANCE_EFFECTS = {"reveal", "text_split", "pop", "count_up", "draw_svg", "accent_line"}
_SVG_SHAPES = ("path", "line", "polyline", "polygon", "circle", "ellipse", "rect")
_CJK_RE = re.compile(r"[぀-ヿ㐀-鿿豈-﫿]")
_POSITION_RE = re.compile(r"^(?P<base>[A-Za-z_][\w-]*|<|>)?(?P<op>[+-]=?)?(?P<num>\d+(?:\.\d+)?)?$")


def _deck_soups(deck_dir: Path) -> dict[str, BeautifulSoup]:
    """Each slide parsed and node-tagged exactly as the engines do."""
    from multilingual_slide_video_agent.production.motion.hyperframes_engine import _INJECTION_RE

    soups = {}
    for path in list_slide_files(deck_dir):
        soup = BeautifulSoup(_INJECTION_RE.sub("", path.read_text(encoding="utf-8")), "lxml")
        tag_text_nodes(soup, path.stem)
        for script in soup.find_all("script"):
            script.decompose()
        soups[path.stem] = soup
    return soups


def _matches(soup: BeautifulSoup, target: dict[str, Any], roles: dict[str, Any] | None) -> tuple[int | None, str | None]:
    """(number of elements the target matches, or None when it can't be
    checked here; an error, or None)."""
    kind, value = next(iter(target.items()))
    if kind == "node":
        found = soup.find(attrs={"data-motion-node": lambda v: bool(v) and value in v.split()})
        return (1, None) if found else (0, f"node {value!r} is not in this slide")
    if kind in ("group", "selector"):
        try:
            count = len(soup.select(value))
        except Exception as e:  # noqa: BLE001 - soupsieve raises several types for a bad selector
            return 0, f"{kind} {value!r} is not a valid CSS selector ({e})"
        return (count, None) if count else (0, f"{kind} {value!r} matches no element")
    if roles is None:
        return None, None
    names = value if isinstance(value, list) else [value]
    for name in names:
        resolved = roles.get(name)
        if name == "slide" or (isinstance(resolved, list) and resolved) or (resolved and not isinstance(resolved, list)):
            return (len(resolved) if isinstance(resolved, list) else 1), None
    return 0, f"role {value!r} resolves to nothing on this slide"


def _text_units(soup: BeautifulSoup, target: dict[str, Any]) -> int:
    """Roughly how many units a text_split staggers over: words, or
    characters in CJK text."""
    kind, value = next(iter(target.items()))
    if kind == "node":
        el = soup.find(attrs={"data-motion-node": lambda v: bool(v) and value in v.split()})
        text = el.get_text(" ", strip=True) if el else ""
    elif kind in ("group", "selector"):
        text = " ".join(el.get_text(" ", strip=True) for el in soup.select(value))
    else:
        return 6
    return max(1, len(_CJK_RE.findall(text)) + len(_CJK_RE.sub(" ", text).split()))


def _svg_shapes(soup: BeautifulSoup, target: dict[str, Any]) -> int:
    kind, value = next(iter(target.items()))
    if kind not in ("group", "selector", "node"):
        return 1
    els = soup.select(value) if kind != "node" else \
        [soup.find(attrs={"data-motion-node": lambda v: bool(v) and value in v.split()})]
    count = 0
    for el in filter(None, els):
        count += 1 if el.name in _SVG_SHAPES else len(el.find_all(_SVG_SHAPES))
    return max(1, count)


def _resolve_position(position: Any, *, timeline_end: float, prev: tuple[float, float],
                      labels: dict[str, float], duration: float) -> float:
    """Where GSAP places a step, mirroring the runtime: seconds, a beat
    fraction, "<" / ">" (the previous step's start / end), "+=" / "-="
    (from the timeline's end), or an earlier step's label."""
    if position is None:
        return timeline_end
    if isinstance(position, (int, float)):
        return float(position)
    if position.startswith("beat:"):
        return float(position[5:]) * duration
    m = _POSITION_RE.match(position)
    if not m:
        return timeline_end
    base, op, num = m.group("base"), m.group("op"), float(m.group("num") or 0)
    if base is None:
        origin = timeline_end
    elif base == "<":
        origin = prev[0]
    elif base == ">":
        origin = prev[1]
    else:
        origin = labels.get(base, timeline_end)
    return origin - num if op and op.startswith("-") else origin + num


def _step_windows(step: dict[str, Any], start: float, *, count: int, units: int, shapes: int,
                  duration: float, tokens: dict[str, float]) -> list[tuple[float, float]]:
    """When each of the step's moving elements moves (mirrors the runtime's
    default durations and staggers)."""
    p = step.get("params", {})
    token = step.get("duration")
    effect = step["effect"]

    def dur(default: float) -> float:
        if token is None:
            return default
        return float(token) if isinstance(token, (int, float)) else tokens[token]

    if effect == "beats":
        d = dur(tokens["slide_enter"])
        first = min(p.get("from", 0.12) * duration, p.get("first_max", 1.2))
        last = max(first, p.get("to", 0.6) * duration)
        return [(first + (last - first) * i / max(1, count - 1), first + (last - first) * i / max(1, count - 1) + d)
                for i in range(count)]
    if effect == "text_split":
        d = dur(tokens["slide_enter"])
        stagger = p.get("stagger", 0.14 if p.get("by") == "line" else 0.04)
        # One text block moving, however many words it has.
        return [(start, start + d + stagger * (max(1, units) - 1))]
    if effect == "draw_svg":
        d = dur(tokens["slide_enter"] * 1.5)
        stagger = p.get("stagger", 0.12)
        return [(start + i * stagger, start + i * stagger + d) for i in range(shapes)]
    if effect == "path_connect":
        d = dur(tokens["slide_enter"] * 1.5)
        return [(start, start + d + tokens["fast"])]
    if effect == "count_up":
        d = dur(tokens["slide_enter"] * (2.5 if p.get("pop") else 1))
        return [(start, start + d)]
    if effect == "exit":
        d = dur(tokens["slide_exit"])
        return [(duration - d, duration)]
    defaults = {"reveal": tokens["base"], "pop": tokens["slide_enter"], "highlight": tokens["slide_enter"],
                "emphasis": tokens["slide_enter"], "accent_line": tokens["slow"]}
    d = dur(defaults.get(effect, tokens["slide_enter"]))
    stagger = p.get("stagger", 0) if isinstance(p.get("stagger", 0), (int, float)) else 0
    return [(start + i * stagger, start + i * stagger + d) for i in range(count)]


def _check_timing(sid: str, steps: list[dict[str, Any]], soup: BeautifulSoup, roles: dict[str, Any] | None,
                  duration: float, tokens: dict[str, float]) -> list[str]:
    errors: list[str] = []
    labels: dict[str, float] = {}
    timeline_end, prev = 0.0, (0.0, 0.0)
    moving: list[tuple[float, float]] = []
    flashes: list[float] = []
    entrance_end = 0.0
    for i, step in enumerate(steps):
        where = f"{sid}.steps[{i}]" + (f" ({step['id']})" if step.get("id") else "")
        if step["effect"] == "camera":
            continue
        start = _resolve_position(step.get("position"), timeline_end=timeline_end, prev=prev,
                                  labels=labels, duration=duration)
        count = _matches(soup, step["target"], roles)[0] or 1
        windows = _step_windows(step, start, count=count, units=_text_units(soup, step["target"]),
                                shapes=_svg_shapes(soup, step["target"]), duration=duration, tokens=tokens)
        first, last = min(w[0] for w in windows), max(w[1] for w in windows)
        if first >= duration:
            errors.append(f"{where}: starts at {first:.2f}s, after the slide ends at {duration:.2f}s")
        elif str(step.get("position", "")).startswith("beat:") and last > duration + 1e-6:
            errors.append(f"{where}: a beat at {first:.2f}s needs until {last:.2f}s, past the slide's end at "
                          f"{duration:.2f}s - place it earlier")
        if step["effect"] in FLASH_EFFECTS:
            flashes.append(start)
        moving.extend(windows)
        if step["effect"] in _ENTRANCE_EFFECTS and not str(step.get("position", "")).startswith("beat:"):
            entrance_end = max(entrance_end, last)
        if step.get("label"):
            labels[step["label"]] = first
        prev = (first, last)
        timeline_end = max(timeline_end, last)

    flashes.sort()
    for i, t in enumerate(flashes):
        in_window = sum(1 for u in flashes[i:] if u < t + 1.0)
        if in_window > MAX_FLASHES_PER_SECOND:
            errors.append(f"{sid}: {in_window} flashes (emphasis/highlight) within one second from {t:.2f}s - "
                          f"at most {MAX_FLASHES_PER_SECOND} per second (WCAG 2.3.1)")
            break
    edges = sorted({w[0] for w in moving})
    for t in edges:
        at_once = sum(1 for a, b in moving if a <= t < b)
        if at_once > MAX_MOVING_ELEMENTS:
            errors.append(f"{sid}: {at_once} elements move at once at {t:.2f}s - at most {MAX_MOVING_ELEMENTS}; "
                          "stagger them or split the step")
            break
    if entrance_end > SETTLE_FRACTION * duration:
        errors.append(f"{sid}: the entrance settles at {entrance_end:.2f}s, later than "
                      f"{int(SETTLE_FRACTION * 100)}% of the slide's shortest expected length "
                      f"({duration:.2f}s) - leave time to read")
    return errors


def slide_durations_from_productions(productions: list[dict[str, Any]]) -> dict[str, float]:
    """The shortest duration of each slide across these languages."""
    shortest: dict[str, float] = {}
    for production in productions:
        for item in production.get("segment_timing", []):
            if item.get("kind") == "slide":
                d = item["end_time"] - item["start_time"]
                shortest[item["slide_id"]] = min(d, shortest.get(item["slide_id"], d))
    return shortest


def check_motion_design(
    doc: Any, *, deck_dir: str | Path, presets: set[str], tokens: dict[str, float],
    brand_colors: set[str], layout_map: dict[str, Any] | None = None,
    slide_durations: dict[str, float] | None = None, source_fingerprint: str | None = None,
) -> dict[str, Any]:
    """Every check in this module's docstring. Returns {"ok", "errors" (the
    design as a whole), "slide_errors" ({slide_id: [...]}), "warnings"}."""
    deck = Path(deck_dir)
    soups = _deck_soups(deck)
    roles_by_slide = ({s["slide_id"]: s.get("roles") or {} for s in layout_map.get("slides", [])}
                      if layout_map else None)
    errors: list[str] = []
    slide_errors: dict[str, list[str]] = {}
    warnings: list[str] = []

    entry_ids = [e.get("slide_id") for e in (doc.get("slides") or []) if isinstance(e, dict)] \
        if isinstance(doc, dict) else []
    for err in md.validate_motion_design(doc, slide_ids=list(soups), presets=presets):
        owner = next((sid for sid in entry_ids if isinstance(sid, str) and re.match(rf"^{re.escape(sid)}[.:]", err)), None)
        (slide_errors.setdefault(owner, []) if owner else errors).append(err)
    if errors:
        return {"ok": False, "errors": errors, "slide_errors": slide_errors, "warnings": warnings}

    if source_fingerprint is not None and doc["deck_fingerprint"] != source_fingerprint:
        errors.append(f"deck_fingerprint {doc['deck_fingerprint']!r} is not this deck's ({source_fingerprint!r}) - "
                      "the design was made for a different version of the deck")
    if layout_map is None:
        warnings.append("no layout map: role targets are not checked")
    if not slide_durations:
        warnings.append("no slide durations (pass a production.json): timing and comfort checks were skipped")

    for entry in doc["slides"]:
        sid = entry["slide_id"]
        if sid in slide_errors or sid not in soups:
            continue
        problems: list[str] = []
        soup, roles = soups[sid], (roles_by_slide or {}).get(sid) if roles_by_slide is not None else None
        for i, step in enumerate(entry.get("steps") or []):
            where = f"{sid}.steps[{i}]" + (f" ({step['id']})" if step.get("id") else "")
            for key in ("target", "to"):
                if key in step:
                    _count, err = _matches(soup, step[key], roles)
                    if err:
                        problems.append(f"{where}: {err}" if key == "target" else f"{where}: to: {err}")
            color = step.get("color")
            if color and color not in brand_colors:
                problems.append(f"{where}: colour {color!r} is not a brand token ({', '.join(sorted(brand_colors))})")
        if not problems and slide_durations and sid in slide_durations and entry.get("steps"):
            problems.extend(_check_timing(sid, md.slide_steps(entry, []), soup, roles,
                                          slide_durations[sid], tokens))
        if problems:
            slide_errors[sid] = problems
    return {"ok": not errors and not slide_errors, "errors": errors, "slide_errors": slide_errors,
            "warnings": warnings}


def brand_color_tokens(design_tokens: dict[str, Any]) -> set[str]:
    """The design system's colour names as the runtime reads them
    (`--ds-color-<name>`)."""
    return {key.replace("_", "-") for key in (design_tokens.get("color") or {})}


def with_fallbacks(doc: dict[str, Any], slide_errors: dict[str, list[str]], presets: set[str]) -> dict[str, Any]:
    """The design with each failing slide reduced to its preset, or to the
    slide's own template when the preset name is the problem (C5: a deck
    never fails to render because of one slide's design)."""
    entries = []
    for entry in doc["slides"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("slide_id"), str):
            continue
        if entry["slide_id"] in slide_errors:
            entry = {"slide_id": entry["slide_id"],
                     **({"preset": entry["preset"]} if entry.get("preset") in presets else {})}
        entries.append(entry)
    return {**doc, "slides": entries}
