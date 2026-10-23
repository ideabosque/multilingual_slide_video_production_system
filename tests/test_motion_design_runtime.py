"""The motion design interpreter in animation_runtime.js (plan C3, Phase 4):
every new effect is seek-safe (the same times, seeked in different orders,
give identical DOM state) and visibly animates; design targets resolve or
fail naming the step; presets play identically by name or as explicit
steps; transitions and the lead keep a slide's own choreography on time.
Requires Playwright's Chromium."""
import json
from pathlib import Path

import pytest

import multilingual_slide_video_agent
from multilingual_slide_video_agent.slides import motion_design as md
from multilingual_slide_video_agent.slides.animation_templates import load_template_config
from multilingual_slide_video_agent.slides.extract_text import tag_text_nodes

pytestmark = pytest.mark.requires_browser

PKG = Path(multilingual_slide_video_agent.__file__).parent
GSAP = PKG / "slides" / "vendor" / "gsap.min.js"
RUNTIME = PKG / "slides" / "assets" / "animation_runtime.js"

TOKENS_CSS = ":root{--ds-color-accent-signal:#D87C2C;--ds-color-brand-forest:#1f4d3a;}"

SLIDE = """<!DOCTYPE html><html><head><style>
body{margin:0;width:1280px;height:720px;background:#f4f1e8;font:32px sans-serif;position:relative}
.layer{display:inline-block;width:200px;height:120px;margin:20px;background:#ddd}
</style></head><body>
<h1>Supplier compliance comes first</h1>
<p class="lede">Every order checks documents before it commits.</p>
<div class="stack"><div class="layer">Check</div><div class="layer">Optimize</div><div class="layer">Record</div></div>
<div class="stat">40%</div>
<svg width="400" height="100"><path class="connector" d="M10 50 L390 50" stroke="#333" stroke-width="4" fill="none"/></svg>
</body></html>"""

# Every property an effect can touch, for every element. An identity matrix
# and `none` draw the same pixels (GSAP leaves one after seeking back past a
# tween that starts at scale 1), so they compare equal.
SNAP = """() => Array.from(document.querySelectorAll('body *')).map(el => {
  const cs = getComputedStyle(el);
  const transform = cs.transform === 'matrix(1, 0, 0, 1, 0, 0)' ? 'none' : cs.transform;
  return [el.tagName, cs.opacity, transform, cs.strokeDashoffset, cs.backgroundSize, cs.color, cs.clipPath,
          cs.filter, el.children.length ? '' : el.textContent];
})"""


def _tagged(html):
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    tag_text_nodes(soup, "slide_009")
    return str(soup)


def _seek_states(opts, times, *, html=SLIDE, templates=None):
    """Build one slide's timeline via __motionRunSlide and return the DOM
    snapshot at each time, seeked in the given order."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 720})
            page.set_content(_tagged(html))
            page.add_style_tag(content=TOKENS_CSS)
            page.add_script_tag(content="window.__ANIMATION_TEMPLATES__ = "
                                + json.dumps(templates or load_template_config("playful")) + ";")
            page.add_script_tag(path=str(GSAP))
            page.add_script_tag(path=str(RUNTIME))
            page.evaluate("opts => { window.__motionRunSlide(document, opts); }",
                          {"slideId": "slide_009", "duration": 6, **opts})
            return [page.evaluate(f"t => {{ window.__timelines['slide_009'].seek(t); return ({SNAP})(); }}", t)
                    for t in times]
        finally:
            browser.close()


def _assert_seek_safe(opts, times=(0, 0.25, 0.6, 0.8, 1.5, 3.0, 5.9), **kwargs):
    """The same times in two different orders give identical states, and
    some state differs from the first (something animated - a pulse ends
    where it started). Returns the states in `times` order."""
    forward = _seek_states(opts, times, **kwargs)
    order = list(reversed(times))
    backward = dict(zip(order, _seek_states(opts, order, **kwargs)))
    for t, state in zip(times, forward):
        assert backward[t] == state, f"seek order changed the DOM at t={t}"
    assert any(state != forward[0] for state in forward[1:]), "nothing animated"
    return forward


def _design(*steps, camera=None):
    entry = {"slide_id": "slide_009", "steps": list(steps)}
    if camera:
        entry["camera"] = camera
    return {"steps": md.slide_steps(entry, [])}


@pytest.mark.parametrize("step", [
    {"target": {"role": "title"}, "effect": "text_split", "by": "word"},
    {"target": {"role": "title"}, "effect": "text_split", "by": "char", "stagger": 0.01},
    {"target": {"node": "slide_009#n1"}, "effect": "text_split", "by": "line"},
    {"target": {"selector": "svg path.connector"}, "effect": "draw_svg"},
    {"target": {"node": "slide_009#n1"}, "effect": "highlight", "beat_at": 0.2},
    {"target": {"role": "title"}, "effect": "highlight", "mode": "color", "color": "brand-forest"},
    {"target": {"role": "stat"}, "effect": "emphasis", "scale": 1.1, "beat_at": 0.1},
    {"target": {"group": ".stack > .layer"}, "effect": "reveal", "from": {"x": -40, "blur": 6}, "stagger": 0.1},
    {"target": {"group": ".stack > .layer"}, "effect": "path_connect", "to": {"role": "stat"}},
], ids=lambda s: f"{s['effect']}-{s.get('by') or s.get('mode') or next(iter(s['target']))}")
def test_each_design_effect_is_seek_safe_and_animates(step):
    _assert_seek_safe(_design(step))


def test_camera_move_is_seek_safe_and_capped():
    _assert_seek_safe(_design({"target": {"role": "title"}, "effect": "reveal"},
                              camera={"effect": "push_in", "scale": 1.08}))
    opts = {"steps": [{"target": {"role": "slide"}, "effect": "camera", "params": {"scale": 1.5}}]}
    (end,) = _body_scale(opts, 5.99)
    assert end <= 1.0801   # the runtime caps it even if a design got past validation


def _body_scale(opts, t):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.set_content(SLIDE)
            page.add_script_tag(path=str(GSAP))
            page.add_script_tag(path=str(RUNTIME))
            return [page.evaluate(
                "([opts, t]) => { window.__motionRunSlide(document, {slideId: 's', duration: 6, ...opts});"
                " window.__timelines['s'].seek(t); return new DOMMatrix(getComputedStyle(document.body).transform).a; }",
                [opts, t])]
        finally:
            browser.close()


def test_path_connect_draws_an_arrow_between_the_boxes():
    states = _seek_states(_design({"target": {"node": "slide_009#n0"}, "effect": "path_connect",
                                   "to": {"role": "stat"}}), [0, 5])
    paths = [row for row in states[1] if row[0] == "path"]
    assert len(paths) == 2                                # the deck's connector plus the arrow
    assert paths[1][3] in ("0px", "0")                     # fully drawn by the end
    heads = [row for row in states[0] if row[0] == "polygon"]
    assert heads and heads[0][1] == "0"                    # arrowhead hidden until the line arrives


def test_a_design_target_that_matches_nothing_fails_naming_the_step():
    from playwright.sync_api import Error

    with pytest.raises(Error, match=r"slide_009: motion design step 'ghost': target .*matches no element"):
        _seek_states(_design({"id": "ghost", "target": {"selector": ".nowhere"}, "effect": "reveal"}), [0])


def test_draw_svg_without_shapes_fails_naming_the_step():
    from playwright.sync_api import Error

    with pytest.raises(Error, match=r"draw_svg found no SVG shapes"):
        _seek_states(_design({"id": "wires", "target": {"role": "title"}, "effect": "draw_svg"}), [0])


def test_an_unknown_brand_colour_fails():
    from playwright.sync_api import Error

    with pytest.raises(Error, match=r"unknown brand colour token 'hot-pink'"):
        _seek_states(_design({"target": {"role": "title"}, "effect": "highlight", "color": "hot-pink"}), [0])


def test_step_labels_place_later_steps_relative_to_earlier_ones():
    """'hdr+=0.5' starts 0.5s after hdr starts, not at the timeline's end."""
    opts = _design(
        {"id": "hdr", "target": {"role": "title"}, "effect": "reveal", "duration": 2},
        {"id": "lede", "target": {"role": "subtitle"}, "effect": "reveal", "position": "hdr+=0.5", "duration": 0.2},
    )
    t04, t08 = _seek_states(opts, [0.4, 0.8])
    lede = lambda state: next(r for r in state if r[0] == "P")[1]
    assert lede(t04) == "0" and lede(t08) == "1"    # lede runs 0.5-0.7s, while hdr is still going


@pytest.mark.parametrize("style", ["calm", "playful"])
def test_every_preset_plays_identically_by_name_or_as_explicit_steps(style):
    """Presets are the templates in the design language: a design slide
    that names a preset (no steps of its own) renders exactly what the
    template renders."""
    templates = load_template_config(style)
    times = [0, 0.3, 0.9, 2.5, 5.5]
    for name, template in templates.items():
        by_name = _seek_states({"template": name}, times, templates=templates)
        explicit = _seek_states({"steps": md.slide_steps({"slide_id": "s", "preset": name}, template["steps"])},
                                times, templates=templates)
        assert by_name == explicit, f"{style} preset {name} differs from its template"


@pytest.mark.parametrize("transition", [
    {"type": "crossfade", "direction": "left"},
    {"type": "push", "direction": "up"},
    {"type": "wipe", "direction": "right"},
])
def test_transitions_and_lead_are_seek_safe_and_keep_the_choreography_on_time(transition):
    lead, d = 0.25, 0.5
    opts = {**_design({"target": {"role": "title"}, "effect": "reveal", "duration": 0.3}),
            "lead": lead,
            "transitionIn": {**transition, "duration": d},
            "transitionOut": {**transition, "duration": d, "at": lead + 6 - 0.25}}
    states = _assert_seek_safe(opts, times=(0, 0.1, 0.25, 0.4, 3.0, 6.1))
    h1 = lambda state: next(r for r in state if r[0] == "H1")[1]
    # the slide's own steps start at `lead`: the title is still hidden there
    assert h1(states[2]) == "0" and h1(states[4]) == "1"


def test_runtime_steps_for_a_full_design_slide_build():
    """A whole design slide, as the engines pass it, builds and settles."""
    entry = {"slide_id": "slide_009", "steps": [
        {"id": "hdr", "target": {"role": "title"}, "effect": "text_split", "by": "word"},
        {"id": "cards", "target": {"group": ".stack > .layer"}, "effect": "pop", "stagger": 0.1, "position": "hdr+=0.2"},
        {"target": {"selector": "svg path.connector"}, "effect": "draw_svg", "position": "cards"},
        {"target": {"role": "stat"}, "effect": "count_up", "pop": True, "beat_at": 0.4},
        {"target": {"role": "stat"}, "effect": "emphasis", "beat_at": 0.8},
    ], "camera": {"effect": "pan", "x": -30, "scale": 1.05}}
    _assert_seek_safe({"steps": md.slide_steps(entry, [])})
