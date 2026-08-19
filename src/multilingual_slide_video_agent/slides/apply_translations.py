"""Apply Agent 1's per-language `slide_translations` back into the
original English deck's HTML, by node ID, preserving the original
CSS/layout/design (slideshow_video_production SKILL.md, non-negotiable
rules: always translate from the original clean deck, never from a
previously translated one).

Re-parses the original deck fresh rather than trusting a stored
manifest.json, so node IDs are always recomputed the same deterministic
way `msv slides extract-text` computes them (see extract_text.py's
`_iter_text_nodes` - identical traversal order). This means a translation
referencing a node ID that no longer exists (the deck's structure changed
since Agent 1 analyzed it) fails loudly here instead of silently applying
to the wrong element.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

from multilingual_slide_video_agent.slides.extract_text import _iter_text_nodes, list_slide_files


class ApplyTranslationsError(Exception):
    pass


def _load_localization(localization_path: str | Path) -> dict[str, Any]:
    with open(localization_path, "r", encoding="utf-8") as f:
        return json.load(f)


def apply_translations(
    *,
    deck_dir: str | Path,
    localization_path: str | Path,
    out_dir: str | Path,
) -> dict[str, Any]:
    deck_path = Path(deck_dir).resolve()
    out_path = Path(out_dir).resolve()
    localization = _load_localization(localization_path)

    # Fresh copy of every non-slide asset (styles.css, assets/, etc.) so
    # the translated deck is a fully self-contained, independently
    # renderable directory - never a partial diff layered on the original.
    if out_path.exists():
        shutil.rmtree(out_path)
    shutil.copytree(deck_path, out_path)

    translations_by_slide: dict[str, dict[str, str]] = {}
    for seg in localization.get("segments", []):
        slide_id = seg.get("slide_id")
        translations_by_slide[slide_id] = {
            t["node_id"]: t["text"] for t in seg.get("slide_translations", [])
        }

    slide_files = list_slide_files(deck_path)
    applied_nodes = 0
    slides_touched = []
    for slide_path in slide_files:
        slide_id = slide_path.stem
        node_translations = translations_by_slide.get(slide_id)
        if node_translations is None:
            # No localization entry for this slide at all - leave the
            # original English text in place rather than guessing.
            continue

        html = slide_path.read_text(encoding="utf-8")
        soup = BeautifulSoup(html, "lxml")

        remaining = dict(node_translations)
        for i, node in enumerate(_iter_text_nodes(soup)):
            node_id = f"{slide_id}#n{i}"
            if node_id in remaining:
                node.replace_with(remaining.pop(node_id))
                applied_nodes += 1

        if remaining:
            raise ApplyTranslationsError(
                f"slide '{slide_id}': localization references node_id(s) not found in the "
                f"current deck (structure changed since analysis): {sorted(remaining)}"
            )

        dest = out_path / slide_path.relative_to(deck_path)
        dest.write_text(str(soup), encoding="utf-8")
        slides_touched.append(slide_id)

    return {
        "source_deck": str(deck_path),
        "translated_deck": str(out_path),
        "language": localization.get("language"),
        "slides_translated": slides_touched,
        "nodes_applied": applied_nodes,
    }
