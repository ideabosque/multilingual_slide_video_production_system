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
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from multilingual_slide_video_agent.slides.extract_text import list_slide_files


class RenderError(Exception):
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
