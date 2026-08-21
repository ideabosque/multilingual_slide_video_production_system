"""Render every slide in a deck to a PNG screenshot via headless Chromium
(Playwright). Called twice per run, at two different points in the
pipeline (slide_deck_localization / slideshow_video_production SKILL.md):

  1. Against the *original* English deck, so Agent 1 can visually read
     what each slide actually looks like - Claude cannot interpret raw
     HTML/CSS any more than it can play video (README "Workflow" step 1).
  2. Against each language's *translated* deck (produced by
     apply_translations), producing the actual video frames Agent 2
     composites into the slideshow.

Both calls go through this same function; only `deck_dir`/`out_dir` differ.

`render_deck_animation_clips` (marketing_animation_pipeline_plan §4/§4.1)
is a separate, later addition: it injects a deck's pre-generated GSAP
animation bundle (slides/generate_animation.py's output) into a translated
deck and captures each slide as a short video clip via Playwright's native
video recording, instead of a static PNG.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from multilingual_slide_video_agent.slides.extract_text import list_slide_files


class RenderError(Exception):
    pass


class AnimationCaptureError(RenderError):
    pass


def _parse_viewport(viewport: str) -> tuple[int, int]:
    try:
        width_s, height_s = viewport.lower().split("x")
        return int(width_s), int(height_s)
    except ValueError as e:
        raise RenderError(f"--viewport must look like '1920x1080', got '{viewport}'") from e


def render_deck_images(
    *,
    deck_dir: str | Path,
    out_dir: str | Path,
    viewport: str = "1920x1080",
) -> dict[str, Any]:
    from playwright.sync_api import sync_playwright

    deck_path = Path(deck_dir).resolve()
    out_path = Path(out_dir).resolve()
    out_path.mkdir(parents=True, exist_ok=True)
    width, height = _parse_viewport(viewport)

    slide_files = list_slide_files(deck_path)
    rendered = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": width, "height": height})
            for slide_path in slide_files:
                slide_id = slide_path.stem
                dest = out_path / f"{slide_id}.png"
                page.goto(slide_path.resolve().as_uri())
                page.screenshot(path=str(dest))
                rendered.append({"slide_id": slide_id, "image": str(dest)})
            page.close()
        finally:
            browser.close()

    manifest = {
        "deck_dir": str(deck_path),
        "out_dir": str(out_path),
        "viewport": {"width": width, "height": height},
        "slides": rendered,
    }
    (out_path / "render_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return manifest


_ANIMATION_MARKER_START = "<!-- ANIMATION-OVERRIDE -->"
_ANIMATION_MARKER_END = "<!-- /ANIMATION-OVERRIDE -->"
_ANIMATION_ASSET_FILES = ("gsap.min.js", "animation_runtime.js", "design_tokens.css")


def _inject_animation_assets(translated_deck_dir: Path, animation_dir: Path, template_by_slide: dict[str, str]) -> None:
    """Copy the deck's pre-generated animation bundle into the translated
    deck directory and inject the <script>/<link> tags each slide needs,
    idempotently (re-running replaces the prior injection by marker, the
    same pattern slides/cjk_fonts.py uses)."""
    for name in _ANIMATION_ASSET_FILES:
        shutil.copy2(animation_dir / name, translated_deck_dir / name)

    for slide_path in list_slide_files(translated_deck_dir):
        slide_id = slide_path.stem
        template = template_by_slide.get(slide_id)
        if template is None:
            raise AnimationCaptureError(
                f"no animation template assigned for slide '{slide_id}' - "
                f"the animation bundle at {animation_dir} doesn't match this deck's slides"
            )
        html = slide_path.read_text(encoding="utf-8")
        html = re.sub(
            re.escape(_ANIMATION_MARKER_START) + r".*?" + re.escape(_ANIMATION_MARKER_END) + r"\n?",
            "", html, flags=re.DOTALL,
        )
        # The inline `<style>` below is render-blocking and applied before
        # first paint - the page stays invisible until animation_runtime.js's
        # run() reveals it, right after GSAP applies the timeline's "from"
        # starting values. Without this, the browser paints the slide at its
        # normal/final CSS state for a frame or more before JS runs, which is
        # a visible flash at the start of every captured clip (confirmed in
        # production output, not just theoretical). Must be inline, not in
        # design_tokens.css - an external stylesheet's load isn't guaranteed
        # to block that first paint the same way.
        override = (
            f"{_ANIMATION_MARKER_START}\n"
            "<style>html{visibility:hidden}</style>\n"
            '<link rel="stylesheet" href="design_tokens.css">\n'
            f'<script>window.__ANIMATION_TEMPLATE__="{template}";</script>\n'
            '<script src="gsap.min.js"></script>\n'
            '<script src="animation_runtime.js" defer></script>\n'
            f"{_ANIMATION_MARKER_END}\n"
        )
        html = html.replace("</head>", override + "</head>", 1)
        slide_path.write_text(html, encoding="utf-8")


def render_deck_animation_clips(
    *,
    translated_deck_dir: str | Path,
    animation_dir: str | Path,
    out_dir: str | Path,
    durations_by_slide_id: dict[str, float],
    viewport: str = "1920x1080",
) -> dict[str, Any]:
    """Inject `animation_dir`'s GSAP bundle into `translated_deck_dir` (in
    place - the translated deck is already per-run/per-language scratch
    output, same as slides/cjk_fonts.py's existing in-place injection) and
    capture each slide as its own short video clip, held for exactly
    `durations_by_slide_id[slide_id]` seconds - the timeline plays once and
    then holds its final state for the rest of the recording (see
    .claude/skills/gsap_animation_authoring/SKILL.md), which is what makes
    "narration-driven duration" (marketing_animation_pipeline_plan §4.1)
    work without the renderer needing to know the timeline's own length.

    A browser console error or uncaught page exception during any slide's
    capture fails the whole call loudly, naming the slide - a silently
    broken animation (e.g. a typo'd selector) is a worse failure mode than
    a script error, since nothing about the output video would look
    obviously wrong without frame-by-frame review.
    """
    from playwright.sync_api import sync_playwright

    deck_path = Path(translated_deck_dir).resolve()
    animation_path = Path(animation_dir).resolve()
    out_path = Path(out_dir).resolve()
    out_path.mkdir(parents=True, exist_ok=True)
    width, height = _parse_viewport(viewport)

    spec = json.loads((animation_path / "spec.json").read_text(encoding="utf-8"))
    template_by_slide = {s["slide_id"]: s["template"] for s in spec["slides"]}
    _inject_animation_assets(deck_path, animation_path, template_by_slide)

    slide_files = list_slide_files(deck_path)
    missing_durations = [f.stem for f in slide_files if f.stem not in durations_by_slide_id]
    if missing_durations:
        raise AnimationCaptureError(f"no duration supplied for slide(s): {missing_durations}")

    clips = []
    console_errors: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            for slide_path in slide_files:
                slide_id = slide_path.stem
                duration = float(durations_by_slide_id[slide_id])
                clip_tmp_dir = out_path / f"_{slide_id}_capture"
                clip_tmp_dir.mkdir(parents=True, exist_ok=True)

                context = browser.new_context(
                    viewport={"width": width, "height": height},
                    record_video_dir=str(clip_tmp_dir),
                    record_video_size={"width": width, "height": height},
                )
                page = context.new_page()
                slide_errors: list[str] = []
                page.on("console", lambda msg: slide_errors.append(msg.text) if msg.type == "error" else None)
                page.on("pageerror", lambda exc: slide_errors.append(str(exc)))
                page.goto(slide_path.resolve().as_uri())
                page.wait_for_timeout(int(duration * 1000))
                video = page.video
                page.close()
                context.close()

                if slide_errors:
                    console_errors.extend(f"{slide_id}: {msg}" for msg in slide_errors)
                    continue

                dest = out_path / f"{slide_id}.webm"
                video.save_as(str(dest))
                shutil.rmtree(clip_tmp_dir, ignore_errors=True)
                clips.append({"slide_id": slide_id, "clip": str(dest), "duration_seconds": duration})
        finally:
            browser.close()

    if console_errors:
        raise AnimationCaptureError(
            "browser console error(s) during animation capture (see "
            "gsap_animation_authoring SKILL.md's self-check): " + "; ".join(console_errors)
        )

    manifest = {
        "translated_deck_dir": str(deck_path),
        "animation_dir": str(animation_path),
        "out_dir": str(out_path),
        "viewport": {"width": width, "height": height},
        "clips": clips,
    }
    (out_path / "animation_render_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return manifest
