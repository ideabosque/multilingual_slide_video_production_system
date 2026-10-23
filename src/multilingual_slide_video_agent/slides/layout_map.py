"""`msv slides inspect-layout` (motion-engines-and-hardening-plan C4, Phase
5): what a motion designer can target on each slide, and where it is.

A screenshot shows what a slide looks like; this map gives the means to
target its elements precisely and to design spatial motion (left-to-right
builds, arrows between real boxes). For each slide, `layout_map.json`
records:

- `elements`: every element holding text, with its extract-text node ids
  (the ids a design's `{"node": ...}` target uses), a short selector, its
  box, font size and colour, and a number shown on the annotated
  screenshot;
- `groups`: repeated sibling groups (cards, rows, chips) with a CSS
  selector that matches exactly that group (a design's `{"group": ...}`);
- `svg_shapes`: SVG shapes with their stroke length (`draw_svg`);
- `roles`: what the animation runtime resolves each role to on this
  slide (`window.__extractRoles`, the one definition every engine uses).

Boxes are in CSS pixels at the given viewport, measured before any
animation runs. With `annotate_dir`, each slide's screenshot is saved with
numbered boxes on its elements, so a designer can map what they see to
ids. The slides are loaded from a scratch copy; the deck is never changed.
"""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

from multilingual_slide_video_agent.slides.extract_text import list_slide_files, tag_text_nodes

# Runs in the slide page: collects the map's per-slide entry.
_COLLECT_JS = r"""
() => {
  const round = (v) => Math.round(v * 10) / 10;
  const box = (el) => {
    const r = el.getBoundingClientRect();
    return {x: round(r.left), y: round(r.top), w: round(r.width), h: round(r.height)};
  };
  const shortSelector = (el) => {
    const cls = typeof el.className === 'string' ? el.className.trim().split(/\s+/).filter(Boolean) : [];
    return el.tagName.toLowerCase() + (cls.length ? '.' + cls.join('.') : '');
  };
  // A selector path that matches exactly this element: tag:nth-child steps
  // up from <body>.
  const path = (el) => {
    const parts = [];
    for (let e = el; e && e !== document.body && e.parentElement; e = e.parentElement) {
      const index = Array.prototype.indexOf.call(e.parentElement.children, e) + 1;
      parts.unshift(e.tagName.toLowerCase() + ':nth-child(' + index + ')');
    }
    return 'body > ' + parts.join(' > ');
  };
  const visible = (el) => {
    const cs = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return cs.display !== 'none' && cs.visibility !== 'hidden' && r.width > 0 && r.height > 0;
  };

  const elements = [];
  document.querySelectorAll('[data-motion-node]').forEach((el) => {
    const cs = getComputedStyle(el);
    elements.push({
      label: elements.length + 1,
      nodes: el.getAttribute('data-motion-node').split(/\s+/),
      tag: el.tagName.toLowerCase(),
      selector: shortSelector(el),
      text: (el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 80),
      box: box(el),
      visible: visible(el),
      font_size: parseFloat(cs.fontSize),
      color: cs.color,
    });
  });

  // Repeated sibling groups: children of one parent sharing a class, the
  // way decks express card grids and chip rows.
  const groups = [];
  document.querySelectorAll('body *').forEach((parent) => {
    const byClass = {};
    Array.prototype.forEach.call(parent.children, (child) => {
      const cls = typeof child.className === 'string' ? child.className.trim().split(/\s+/)[0] : '';
      if (cls) (byClass[cls] = byClass[cls] || []).push(child);
    });
    Object.keys(byClass).forEach((cls) => {
      const members = byClass[cls];
      if (members.length < 2) return;
      const exact = (sel) => {
        try {
          const found = document.querySelectorAll(sel);
          return found.length === members.length && members.every((m) => Array.prototype.includes.call(found, m));
        } catch (e) { return false; }
      };
      const parentClass = typeof parent.className === 'string' ? parent.className.trim().split(/\s+/)[0] : '';
      const candidates = [];
      if (parentClass) candidates.push('.' + parentClass + ' > .' + cls);
      candidates.push('.' + cls);
      candidates.push(path(parent) + ' > .' + cls);
      groups.push({
        selector: candidates.find(exact),
        count: members.length,
        boxes: members.map(box),
        texts: members.map((m) => (m.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 40)),
      });
    });
  });

  const svg_shapes = [];
  document.querySelectorAll('svg path, svg line, svg polyline, svg polygon, svg circle, svg ellipse, svg rect')
    .forEach((el) => {
      let length = null;
      try { length = round(el.getTotalLength()); } catch (e) { /* not a geometry element */ }
      svg_shapes.push({selector: path(el), box: box(el), length: length});
    });

  return {
    elements: elements,
    groups: groups.filter((g) => g.selector),
    svg_shapes: svg_shapes,
    roles: window.__extractRoles ? window.__extractRoles() : {},
  };
}
"""


class LayoutMapError(Exception):
    pass


def _prepare_page(source: Path, dest: Path) -> None:
    """The slide, node-tagged as the engines tag it, without its own
    scripts, plus the runtime (for role resolution only - with no template
    set, it builds no timeline and leaves the page as authored)."""
    from multilingual_slide_video_agent.production.motion.hyperframes_engine import _INJECTION_RE

    soup = BeautifulSoup(_INJECTION_RE.sub("", source.read_text(encoding="utf-8")), "lxml")
    tag_text_nodes(soup, source.stem)
    for script in soup.find_all("script"):
        script.decompose()
    html = str(soup).replace("</body>", '<script src="animation_runtime.js"></script></body>', 1)
    dest.write_text(html, encoding="utf-8")


def _annotate(screenshot: Path, entry: dict[str, Any], dest: Path) -> None:
    from PIL import Image, ImageDraw

    image = Image.open(screenshot).convert("RGB")
    draw = ImageDraw.Draw(image)
    for group in entry["groups"]:
        for b in group["boxes"]:
            draw.rectangle([b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"]], outline=(40, 120, 220), width=2)
    for el in entry["elements"]:
        if not el["visible"]:
            continue
        b = el["box"]
        draw.rectangle([b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"]], outline=(216, 124, 44), width=2)
        tag = str(el["label"])
        x, y = b["x"], max(0, b["y"] - 18)
        draw.rectangle([x, y, x + 9 * len(tag) + 6, y + 17], fill=(216, 124, 44))
        draw.text((x + 3, y + 2), tag, fill=(255, 255, 255))
    image.save(dest)


def inspect_layout(*, deck_dir: str | Path, out_path: str | Path, annotate_dir: str | Path | None = None,
                   viewport: str = "1920x1080") -> dict[str, Any]:
    from playwright.sync_api import sync_playwright

    from multilingual_slide_video_agent.slides.render import RenderError, _parse_viewport
    from multilingual_slide_video_agent.slides.generate_animation import _ASSETS_DIR, ANIMATION_JS_NAME
    from multilingual_slide_video_agent.state import FINGERPRINT_ALGO, directory_fingerprint

    deck = Path(deck_dir).resolve()
    try:
        width, height = _parse_viewport(viewport)
    except RenderError as e:
        raise LayoutMapError(str(e)) from e
    slide_files = list_slide_files(deck)
    annotate = Path(annotate_dir).resolve() if annotate_dir else None
    if annotate:
        annotate.mkdir(parents=True, exist_ok=True)

    slides, page_errors = [], []
    with tempfile.TemporaryDirectory(prefix="msv_layout_", ignore_cleanup_errors=True) as tmp:
        work = Path(tmp) / "deck"
        shutil.copytree(deck, work)
        shutil.copy2(_ASSETS_DIR / ANIMATION_JS_NAME, work / ANIMATION_JS_NAME)
        for slide in slide_files:
            _prepare_page(slide, work / slide.name)
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page(viewport={"width": width, "height": height})
                page.on("pageerror", lambda exc: page_errors.append(str(exc)))
                for slide in slide_files:
                    page.goto((work / slide.name).as_uri())
                    page.evaluate("document.fonts.ready")
                    entry = {"slide_id": slide.stem, **page.evaluate(_COLLECT_JS)}
                    if annotate:
                        shot = Path(tmp) / f"{slide.stem}.png"
                        page.screenshot(path=str(shot))
                        image = annotate / f"{slide.stem}.png"
                        _annotate(shot, entry, image)
                        entry["annotated_image"] = str(image)
                    slides.append(entry)
            finally:
                browser.close()
    if page_errors:
        raise LayoutMapError("page error(s) while inspecting the deck: " + "; ".join(page_errors))

    layout = {
        "deck_dir": str(deck),
        "deck_fingerprint": directory_fingerprint(deck),
        "deck_fingerprint_algo": FINGERPRINT_ALGO,
        "viewport": {"width": width, "height": height},
        "slides": slides,
    }
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(layout, indent=2, ensure_ascii=False), encoding="utf-8")
    return layout
