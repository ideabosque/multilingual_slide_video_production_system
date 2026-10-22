"""The seek-mode runtime contract (plan B3 #1) and its determinism test,
plus the Phase 1 exit criterion "validation catches a deliberately broken
template/selector at capture level". Requires Playwright's Chromium."""
import json
import shutil
from pathlib import Path

import pytest

pytestmark = pytest.mark.requires_browser

import multilingual_slide_video_agent

PKG = Path(multilingual_slide_video_agent.__file__).parent
GSAP = PKG / "slides" / "vendor" / "gsap.min.js"
RUNTIME = PKG / "slides" / "assets" / "animation_runtime.js"

SLIDE_ID = "slide_001"

HTML = (
    "<!DOCTYPE html><html><head><style>body{margin:0;background:#123030;color:#eee}</style></head><body>"
    "<h1>Alpha deck</h1><p>a subtitle line</p>"
    "<ul><li>one</li><li>two</li><li>three</li><li>four</li></ul>"
    "<div class='stat'>40%</div>"
    "</body></html>"
)
TEMPLATE = {
    "feature_callout": {"steps": [
        {"id": "hdr", "role": "title", "effect": "reveal", "params": {"y": 24}, "position": 0},
        {"id": "sub", "role": "subtitle", "effect": "reveal", "position": "hdr+=0.1"},
        {"id": "stat", "role": "stat", "effect": "count_up", "position": "hdr+=0.2"},
        {"id": "body", "role": "body", "effect": "reveal",
         "params": {"y": 12, "stagger": 0.03}, "position": "hdr+=0.3", "min_count": 3},
    ]},
}
CONFIG_INLINE = (
    f"window.__ANIMATION_TEMPLATES__ = {json.dumps(TEMPLATE)};"
    f'window.__ANIMATION_TEMPLATE__ = "feature_callout";'
    f'window.__MOTION_MODE__ = "seek";'
    f'window.__ANIMATION_SLIDE_ID__ = "{SLIDE_ID}";'
)

SNAPJS = (
    "() => JSON.stringify({title_op: getComputedStyle(document.querySelector('h1')).opacity,"
    " stat: document.querySelector('.stat').textContent,"
    " li0_op: getComputedStyle(document.querySelector('li')).opacity})"
)


def _new_page(p, *, seek_mode=True):
    page = p.chromium.launch().new_page()
    inline = CONFIG_INLINE
    if not seek_mode:
        inline = inline.replace('window.__MOTION_MODE__ = "seek";', 'window.__MOTION_MODE__ = "live";')
    page.set_content(HTML)
    page.add_script_tag(content=inline)
    page.add_script_tag(path=str(GSAP))
    page.add_script_tag(path=str(RUNTIME))
    return page


def _seek_snap(page, t):
    snap_expr = SNAPJS[6:]  # strip "() => "
    return page.evaluate(f"() => {{ window.__timelines['{SLIDE_ID}'].seek({t}); return {snap_expr}; }}")


def test_seek_mode_registers_paused_timeline_and_seeks_deterministically():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        page = _new_page(p, seek_mode=True)
        page.wait_for_function("document.documentElement.style.visibility === 'visible'")
        registered = page.evaluate(f"() => Object.keys(window.__timelines)")
        assert registered == [SLIDE_ID]

        # the same times, seeked in two different orders - identical DOM state
        order_a = {t: _seek_snap(page, t) for t in (0, 0.5, 0.25, 2.0)}
        order_b = {}
        for t in (0.5, 2.0, 0, 0.25):
            order_b[t] = _seek_snap(page, t)
        for t, snap in order_a.items():
            assert order_b[t] == snap, f"seek order changed DOM state at t={t}"

        # entrance and settle states differ (check-3's premise)
        assert json.loads(order_a[0])["title_op"] == "0"
        assert json.loads(order_a[2.0])["title_op"] == "1"
        # count-up is seek-safe: value derived from playhead progress, and
        # t=0 shows the counter's start value on first visit too (the stat
        # is still at opacity 0 there, so "0%" is never visible)
        assert json.loads(order_a[2.0])["stat"] == "40%"
        assert json.loads(order_a[0])["stat"] == "0%"
        page.context.close()


def test_default_mode_is_live_behaviour():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        page = _new_page(p, seek_mode=False)
        page.wait_for_function("document.documentElement.style.visibility === 'visible'")
        assert page.evaluate("!window.__timelines")            # nothing seek-registered
        page.wait_for_timeout(900)                             # the live timeline has settled
        assert page.evaluate(SNAPJS[6:]).replace("title_op", "").count("40%") == 1
        assert json.loads(page.evaluate(SNAPJS[6:]))["stat"] == "40%"
        page.context.close()


def test_extract_roles_writes_localized_roles(tmp_path, monkeypatch):
    from multilingual_slide_video_agent.slides.extract_roles import extract_deck_roles
    from multilingual_slide_video_agent.slides.generate_animation import generate_deck_animation

    from motion_fixture_helpers import write_deck

    deck = tmp_path / "deck"
    write_deck(deck, {
        "slide_001": "<h1>Alpha deck</h1><ul><li>one</li><li>two</li><li>three</li><li>four</li></ul>"
                     "<div class='stat'>40%</div>",
        "slide_002": "<h1>Beta deck</h1><p>body text</p>",
    })
    manifest = generate_deck_animation(deck_dir=deck, out_dir=tmp_path / "anim")
    bundle_dir = Path(manifest["bundle_dir"]) if "bundle_dir" in manifest else tmp_path / "anim"

    roles_path = tmp_path / "roles_en-US.json"
    extract_roles_manifest = extract_deck_roles(
        translated_deck_dir=deck, animation_dir=bundle_dir, out_path=roles_path,
    )
    by_slide = {s["slide_id"]: s for s in extract_roles_manifest["slides"]}
    roles = by_slide["slide_001"]["roles"]
    assert roles["title"] == "Alpha deck"
    assert roles["body"] == ["one", "two", "three", "four"]
    assert roles["stat"]["value"] == 40 and roles["stat"]["suffix"] == "%"
    written = json.loads(roles_path.read_text(encoding="utf-8"))
    assert {s["slide_id"] for s in written["slides"]} == {"slide_001", "slide_002"}
    assert written["slides"][0]["template"]  # template recorded from spec.json
    # The seek-mode injection happens in a temporary copy: the translated
    # deck must not be left frozen at its animation start state.
    for slide in deck.glob("slide_*.html"):
        assert "ANIMATION-OVERRIDE" not in slide.read_text(encoding="utf-8")
    assert not (deck / "animation_runtime.js").exists()


COUNT_UP_TEMPLATE = {"stat_highlight": {"steps": [
    {"id": "stat", "role": "stat", "effect": "count_up", "position": 0},
]}}


def _count_up_texts(stat_text, times):
    from playwright.sync_api import sync_playwright

    html = f"<!DOCTYPE html><html><body><h1>Big number</h1><div class='stat'>{stat_text}</div></body></html>"
    inline = (
        f"window.__ANIMATION_TEMPLATES__ = {json.dumps(COUNT_UP_TEMPLATE)};"
        'window.__ANIMATION_TEMPLATE__ = "stat_highlight";'
        f'window.__MOTION_MODE__ = "seek"; window.__ANIMATION_SLIDE_ID__ = "{SLIDE_ID}";'
    )
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.set_content(html)
            page.add_script_tag(content=inline)
            page.add_script_tag(path=str(GSAP))
            page.add_script_tag(path=str(RUNTIME))
            page.wait_for_function("document.documentElement.style.visibility === 'visible'")
            return [
                page.evaluate(
                    f"() => {{ window.__timelines['{SLIDE_ID}'].seek({t}); "
                    "return document.querySelector('.stat').textContent; }"
                )
                for t in times
            ]
        finally:
            browser.close()


def test_count_up_actually_counts_mid_animation():
    """The start/end text equals the source text either way, so only a
    mid-tween seek proves the number really counts up."""
    start, mid, end = _count_up_texts("40%", (0.0, 0.15, 5.0))
    assert end == "40%"
    assert mid != "40%"
    assert mid.endswith("%") and 0 < int(mid[:-1]) < 40


def test_count_up_keeps_prefix_suffix_and_source_decimals():
    mid, end = _count_up_texts("$1.50M saved", (0.15, 5.0))
    assert end == "$1.50M saved"            # "1.50", not "1.5"
    assert mid != end                       # it really is mid-count
    number = mid[1:-len("M saved")]
    assert mid.startswith("$") and mid.endswith("M saved")
    assert len(number.split(".")[1]) == 2 and 0 < float(number) < 1.5


def test_capture_fails_loudly_on_a_broken_template(tmp_path):
    """Phase 1 exit criterion: a deliberately broken animation config fails
    the capture loudly, naming the slide - not a silently-broken video."""
    from multilingual_slide_video_agent.slides.render import (
        AnimationCaptureError,
        render_deck_animation_clips,
    )

    from motion_fixture_helpers import write_deck

    deck = tmp_path / "deck"
    write_deck(deck, {"slide_001": "<h1>Alpha</h1><p>body</p>"})
    anim = tmp_path / "anim"
    anim.mkdir()
    shutil.copy2(GSAP, anim / "gsap.min.js")
    shutil.copy2(RUNTIME, anim / "animation_runtime.js")
    (anim / "design_tokens.css").write_text("/* minimal */", encoding="utf-8")
    (anim / "templates_config.js").write_text(
        "window.__ANIMATION_TEMPLATES__ = "
        + json.dumps({"feature_callout": {"steps": [
            {"id": "hdr", "role": "title", "effect": "bogus_effect", "position": 0},
        ]}}) + ";", encoding="utf-8")
    (anim / "spec.json").write_text(
        json.dumps({"slides": [{"slide_id": "slide_001", "template": "feature_callout"}]}),
        encoding="utf-8")

    with pytest.raises(AnimationCaptureError, match="Unknown animation effect"):
        render_deck_animation_clips(
            translated_deck_dir=deck, animation_dir=anim,
            out_dir=tmp_path / "captures", durations_by_slide_id={"slide_001": 1.0},
        )

def _seek_page(html, template, times, snap_js):
    """Load `html` with the runtime in seek mode and return snap_js's value
    at each seek time."""
    from playwright.sync_api import sync_playwright

    inline = (
        f"window.__ANIMATION_TEMPLATES__ = {json.dumps(template)};"
        f'window.__ANIMATION_TEMPLATE__ = "{next(iter(template))}";'
        f'window.__MOTION_MODE__ = "seek"; window.__ANIMATION_SLIDE_ID__ = "{SLIDE_ID}";'
    )
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.set_content(html)
            page.add_script_tag(content=inline)
            page.add_script_tag(path=str(GSAP))
            page.add_script_tag(path=str(RUNTIME))
            page.wait_for_function("document.documentElement.style.visibility === 'visible'")
            return [
                page.evaluate(f"() => {{ window.__timelines['{SLIDE_ID}'].seek({t}); return ({snap_js})(); }}")
                for t in times
            ]
        finally:
            browser.close()


# Markup patterns from a real deck (run-20260911-002 slides 5, 7, 10), where
# the old role selectors resolved nothing and the slides didn't animate.
REAL_STAT_SLIDE = (
    "<!DOCTYPE html><html><body><section class='slide'>"
    "<p class='eyebrow'>Board-level risk signal</p>"
    "<div class='stat-num'>60<span class='unit'>%</span></div>"
    "<p class='stat-caption'>target spoilage-cost reduction</p>"
    "</section></body></html>"
)


def test_stat_num_class_counts_up_and_keeps_its_unit_span():
    snap = ("() => { const el = document.querySelector('.stat-num');"
            " return {html: el.innerHTML, text: el.textContent}; }")
    mid, end = _seek_page(REAL_STAT_SLIDE, COUNT_UP_TEMPLATE, (0.15, 5.0), snap)
    assert end["html"] == '60<span class="unit">%</span>'   # markup unchanged once settled
    assert mid["html"].endswith('<span class="unit">%</span>')
    assert 0 < int(mid["text"][:-1]) < 60


TITLE_TEMPLATE = {"title_reveal": {"steps": [
    {"id": "hdr", "role": "title", "effect": "reveal", "position": 0},
]}}
TITLE_OPACITY = "() => [...document.querySelectorAll('h1, h2, h3')].map(h => getComputedStyle(h).opacity)"


def test_title_falls_back_to_h3_when_a_slide_has_no_h1_or_h2():
    html = ("<!DOCTYPE html><html><body><p class='eyebrow'>Shortage response</p>"
            "<h3>Ask what is equivalent.</h3><h3>Contact five suppliers.</h3></body></html>")
    (start,) = _seek_page(html, TITLE_TEMPLATE, (0,), TITLE_OPACITY)
    assert start == ["0", "1"]          # the first h3 is the title; the second is untouched


def test_h1_still_wins_over_an_earlier_h3():
    html = "<!DOCTYPE html><html><body><h3>kicker</h3><h1>Real title</h1></body></html>"
    (start,) = _seek_page(html, TITLE_TEMPLATE, (0,), TITLE_OPACITY)
    assert start == ["1", "0"]          # [h3, h1] in document order: only the h1 animates
