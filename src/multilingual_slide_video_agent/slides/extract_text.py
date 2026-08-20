"""Parse a slide deck's HTML and assign every translatable text node a
stable ID, so Agent 1's per-language translations can be applied back onto
the original deck by exact node lookup instead of fuzzy text matching (see
slide_deck_localization SKILL.md's "Node-ID-based translation mapping").

Deck shape (README "Directory layout"): a directory of standalone,
self-contained slide files - slide_001.html, slide_002.html, ... - each a
complete HTML page, optionally sharing styles.css and an assets/ folder.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup, NavigableString

_SLIDE_FILE_RE = re.compile(r"^slide_(\d+)\.html?$")

# Tags whose direct text content is never a caption/copy node worth
# translating - script/style bodies would corrupt the page if translated,
# and title/meta/head content isn't shown on screen.
_SKIP_PARENT_TAGS = {"script", "style", "template", "head", "title", "meta", "noscript"}


def list_slide_files(deck_dir: str | Path) -> list[Path]:
    """Every slide_NNN.html file in `deck_dir`, in slide-number order."""
    deck_path = Path(deck_dir)
    matches = []
    for f in deck_path.iterdir():
        m = _SLIDE_FILE_RE.match(f.name)
        if m:
            matches.append((int(m.group(1)), f))
    if not matches:
        raise FileNotFoundError(f"No slide_NNN.html files found in {deck_path}")
    matches.sort(key=lambda pair: pair[0])
    return [f for _n, f in matches]


def _selector_path(node: NavigableString) -> str:
    """A short, human-readable (not guaranteed-unique) breadcrumb for
    debugging/logging - the authoritative identifier is still node_id."""
    parts = []
    el = node.parent
    while el is not None and getattr(el, "name", None):
        idx = 1
        sib = el.previous_sibling
        while sib is not None:
            if getattr(sib, "name", None) == el.name:
                idx += 1
            sib = sib.previous_sibling
        parts.append(f"{el.name}[{idx}]" if idx > 1 else el.name)
        el = el.parent
    return ">".join(reversed(parts))


def _iter_text_nodes(soup: BeautifulSoup):
    for node in soup.find_all(string=True):
        if not isinstance(node, NavigableString):
            continue
        if node.parent is None or node.parent.name in _SKIP_PARENT_TAGS:
            continue
        # lxml surfaces a phantom "html" text node as a direct child of the
        # BeautifulSoup document root (parent.name == "[document]"). It is
        # whitespace/indentation between `<!doctype html>` and `<html>`, not
        # a real translatable node — but browsers render it as visible text
        # at the top of the page. Skip any direct child of the document root.
        if node.parent.name == "[document]":
            continue
        if not node.strip():
            continue
        yield node


def extract_slide_text(slide_path: Path, slide_index: int) -> dict[str, Any]:
    slide_id = slide_path.stem
    html = slide_path.read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "lxml")

    nodes = []
    for i, node in enumerate(_iter_text_nodes(soup)):
        node_id = f"{slide_id}#n{i}"
        nodes.append(
            {
                "node_id": node_id,
                "selector_path": _selector_path(node),
                "text": str(node).strip(),
            }
        )
    return {
        "slide_index": slide_index,
        "slide_id": slide_id,
        "file": slide_path.name,
        "nodes": nodes,
    }


def extract_deck_text(deck_dir: str | Path, out_path: str | Path) -> dict[str, Any]:
    deck_path = Path(deck_dir).resolve()
    slide_files = list_slide_files(deck_path)

    slides = [
        extract_slide_text(slide_path, slide_index=i + 1)
        for i, slide_path in enumerate(slide_files)
    ]
    manifest = {
        "source_deck": str(deck_path),
        "slide_count": len(slides),
        "slides": slides,
    }

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest
