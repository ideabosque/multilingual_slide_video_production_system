"""`msv slides extract-roles` (motion-engines-and-hardening-plan B3 #2) -
extract each translated slide's resolved animation roles into
`roles_<language>.json`: the content contract the Remotion engine consumes
(B5) and a validation aid everywhere else.

It deliberately resolves roles by running the animation runtime's own
`roleElements()` (exposed as `window.__extractRoles()`) in headless
Chromium against the already-translated deck, so there is exactly one
definition of "what is the title of this slide" across engines - no second
Python reimplementation to drift - and because the text is read from the
translated DOM it is localized automatically. The bundle is injected in
`seek` mode so the timeline stays paused at 0: role text is read before any
tween has rendered (a live timeline's count-up would race the extraction).

Runs of the same injection the capture path uses (`_inject_animation_assets`
with `motion_mode="seek"`), so a deck whose roles were extracted is already
in the capture-ready state.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from multilingual_slide_video_agent.slides.extract_text import list_slide_files


class ExtractRolesError(Exception):
    pass


def _load_json(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def extract_deck_roles(
    *,
    translated_deck_dir: str | Path,
    animation_dir: str | Path,
    out_path: str | Path,
    viewport: str = "1920x1080",
) -> dict[str, Any]:
    from playwright.sync_api import sync_playwright

    from multilingual_slide_video_agent.slides.render import (
        AnimationCaptureError,
        RenderError,
        _inject_animation_assets,
        _parse_viewport,
    )

    deck_path = Path(translated_deck_dir).resolve()
    animation_path = Path(animation_dir).resolve()
    out_file = Path(out_path).resolve()
    out_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        width, height = _parse_viewport(viewport)
    except RenderError as e:
        raise ExtractRolesError(str(e)) from e

    spec = _load_json(animation_path / "spec.json")
    template_by_slide = {s["slide_id"]: s["template"] for s in spec.get("slides", [])}
    slide_files = list_slide_files(deck_path)
    if not slide_files:
        raise ExtractRolesError(f"no slides found in {deck_path}")

    try:
        _inject_animation_assets(deck_path, animation_path, template_by_slide, motion_mode="seek")
    except AnimationCaptureError as e:
        raise ExtractRolesError(str(e)) from e

    entries: list[dict[str, Any]] = []
    console_errors: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": width, "height": height})
            page_errors: list[str] = []
            page.on("pageerror", lambda exc: page_errors.append(str(exc)))
            for slide_path in slide_files:
                slide_id = slide_path.stem
                if slide_id not in template_by_slide:
                    raise ExtractRolesError(
                        f"no animation template assigned for slide '{slide_id}' - the "
                        f"animation bundle at {animation_path} doesn't match this deck's slides"
                    )
                page.goto(slide_path.resolve().as_uri())
                page.wait_for_function("document.documentElement.style.visibility === 'visible'", timeout=5000)
                roles = page.evaluate("() => window.__extractRoles ? window.__extractRoles() : {}")
                if page_errors:
                    console_errors.extend(page_errors)
                    page_errors.clear()
                entries.append({
                    "slide_id": slide_id,
                    "template": template_by_slide[slide_id],
                    "roles": roles,
                })
            page.close()
        finally:
            browser.close()

    if console_errors:
        raise ExtractRolesError("page error(s) during role extraction: " + "; ".join(console_errors))

    manifest = {
        "deck_dir": str(deck_path),
        "animation_dir": str(animation_path),
        "out_path": str(out_file),
        "viewport": {"width": width, "height": height},
        "slides": entries,
    }
    out_file.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest