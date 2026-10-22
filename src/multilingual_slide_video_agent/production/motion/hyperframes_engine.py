"""The `hyperframes` engine (motion-engines-and-hardening-plan B4, Phase 2b):
renders the translated deck frame-exactly with HyperFrames instead of
recording it live.

Every slide becomes a HyperFrames sub-composition and the whole video one
project; HyperFrames seeks each slide's paused GSAP timeline to every frame
before capturing it, so there is no wall clock, no live recording and no
lead-in to trim. What the Phase 2a spike established and this module relies
on (plan B4's results table):

- sub-compositions are `<template>` fragments cloned into ONE shared
  document. HyperFrames scopes their CSS (including `html`, `body` and
  `:root` rules) onto the composition root, but scripts share the page - so
  each slide's animation runs through the runtime's per-slide entry point
  `window.__motionRunSlide(rootEl, ...)`, which resolves roles inside that
  slide only;
- the project is served over HTTP with the project root as base URL, so the
  deck's own relative asset paths keep working when the deck is copied to
  the project root;
- clip timelines are local to each clip's `data-start`;
- telemetry is on by default and is disabled per invocation;
- `check` reports a slide's script error in seconds, while `render` only
  fails after a 45s registration timeout - so `check` runs first.

The engine's contract is unchanged (base.py): an exact-length silent video.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from bs4 import BeautifulSoup

from multilingual_slide_video_agent import config as cfg
from multilingual_slide_video_agent.media import ffprobe_duration
from multilingual_slide_video_agent.production.motion.context import MotionRenderContext
from multilingual_slide_video_agent.production.motion.errors import MotionError
from multilingual_slide_video_agent.production.motion.assembly import segment_frame_counts
from multilingual_slide_video_agent.slides.animation_templates import load_template_config
from multilingual_slide_video_agent.slides.extract_text import list_slide_files

MIN_NODE_MAJOR = 22
TITLE_COMPOSITION_ID = "title"

# The capture injection slides/render.py writes into a slide (and which older
# runs left inside the translated deck itself). Stripped on conversion: the
# HyperFrames page loads the runtime once, and a per-slide copy would start
# a second, page-wide timeline.
_INJECTION_RE = re.compile(r"<!-- ANIMATION-OVERRIDE -->.*?<!-- /ANIMATION-OVERRIDE -->\n?", re.DOTALL)

# Runtime files the index page loads once for every slide: code from the
# installed package (never a bundle's stale copy - see slides/render.py's
# _animation_asset_source) and the deck's design tokens from its bundle.
# templates_config.js is generated fresh for the configured motion style
# (see build_project).
_INDEX_ASSETS = ("gsap.min.js", "animation_runtime.js", "design_tokens.css")


def motion_dir() -> Path:
    """The pinned Node toolchain directory (`motion/`). MSV_ROOT_DIR's copy
    first, then the repository this package was installed from (editable
    installs)."""
    candidates = [cfg.root_dir() / "motion", Path(__file__).resolve().parents[4] / "motion"]
    for candidate in candidates:
        if (candidate / "package.json").exists():
            return candidate
    return candidates[0]


def _cli_script() -> Path:
    return motion_dir() / "node_modules" / "hyperframes" / "bin" / "hyperframes.mjs"


def _node_major(node: str) -> int | None:
    try:
        out = subprocess.run([node, "--version"], capture_output=True, text=True, check=True).stdout
        return int(out.strip().lstrip("v").split(".")[0])
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def check_available() -> list[str]:
    """Missing prerequisites; an empty list means ready. Never raises."""
    missing = []
    node = shutil.which("node")
    major = _node_major(node) if node else None
    if major is None:
        missing.append(f"Node.js {MIN_NODE_MAJOR}+ not found on PATH")
    elif major < MIN_NODE_MAJOR:
        missing.append(f"Node.js {major} found; HyperFrames needs {MIN_NODE_MAJOR}+")
    if not _cli_script().exists():
        missing.append(f"HyperFrames is not installed in {motion_dir()} (run: msv motion install)")
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        missing.append("ffmpeg/ffprobe not found on PATH")
    return missing


def _env() -> dict[str, str]:
    """Telemetry is on by default (plan B4); every invocation opts out
    without touching the user's global HyperFrames settings."""
    return {**os.environ, "HYPERFRAMES_NO_TELEMETRY": "1", "DO_NOT_TRACK": "1"}


def _run_cli(args: list[str], *, timeout: float, what: str) -> subprocess.CompletedProcess:
    cmd = [shutil.which("node") or "node", str(_cli_script()), *args]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                env=_env(), timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise MotionError(f"hyperframes {what} timed out after {timeout:.0f}s") from e
    if result.returncode != 0:
        output = _strip_ansi((result.stdout or "") + (result.stderr or ""))
        raise MotionError(f"hyperframes {what} failed (exit {result.returncode}):\n{_error_lines(output)}")
    return result


def _strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def _error_lines(output: str, limit: int = 15) -> str:
    """The lines that explain a failure (errors name the slide - e.g.
    `composition script error: slide_004 ReferenceError ...`), else the tail."""
    lines = [ln.strip() for ln in output.splitlines() if ln.strip()]
    flagged = [ln for ln in lines if re.search(r"✗|error|Error|failed|threw", ln)]
    return "\n".join((flagged or lines)[-limit:])


def hyperframes_version() -> str | None:
    try:
        return _run_cli(["--version"], timeout=60, what="--version").stdout.strip().splitlines()[-1]
    except (MotionError, IndexError):
        return None


def _parse_viewport(viewport: str) -> tuple[int, int]:
    try:
        width, height = (int(v) for v in viewport.lower().split("x"))
        return width, height
    except ValueError as e:
        raise MotionError(f"viewport must look like '1920x1080', got '{viewport}'") from e


def _sanitize_css(css: str) -> str:
    """CSS text safe to embed in a sub-composition. HyperFrames' check
    counts `<style` / `</style` as text, so a comment such as "do not edit
    this <style> block" (the real food-manufacturing deck has one) reads as
    an unclosed tag and fails every slide. Comments never affect rendering,
    so they're dropped; any `<` left can only be inside a CSS string, where
    the `\\3C ` escape renders identically."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    return css.replace("<", "\\3C ")


def slide_to_template(
    slide_html: str, *, slide_id: str, template: str, width: int, height: int, duration: float = 0.0,
    templates: dict | None = None, extra_css: str = "",
) -> tuple[str, int]:
    """Convert one translated slide (a full HTML document) into a
    HyperFrames sub-composition: a single bare `<template>` whose root
    carries the slide's styles, its body content, and a script that builds
    the slide's timeline inside that root only. Returns (html, number of
    the deck's own <script> elements dropped)."""
    soup = BeautifulSoup(_INJECTION_RE.sub("", slide_html), "lxml")
    head = soup.head or soup.new_tag("head")
    body = soup.body or soup.new_tag("body")

    # The deck's own scripts would run in the shared page (and on every
    # seek); the animation comes from the runtime instead.
    dropped = 0
    for script in soup.find_all("script"):
        script.decompose()
        dropped += 1

    for style in head.find_all("style"):
        style.string = _sanitize_css(style.get_text())
    styles = [str(tag) for tag in head.find_all(["style", "link"])
              if tag.name == "style" or "stylesheet" in (tag.get("rel") or [])]
    # Root-relative paths only (plan B4): the deck sits at the project root.
    styles = [re.sub(r'(href|src)="\./', r'\1="', s) for s in styles]

    # Body classes/inline style move onto a full-frame wrapper: a class on
    # the composition root itself is not stylable after HyperFrames' scoping.
    wrapper_attrs = ""
    if body.get("class"):
        wrapper_attrs += f' class="{" ".join(body["class"])}"'
    wrapper_style = "position:absolute;inset:0;"
    if body.get("style"):
        wrapper_style += body["style"]
    content = "".join(str(child) for child in body.contents)

    html = (
        f'<template id="{slide_id}-template">\n'
        f'<div id="root" data-composition-id="{slide_id}" data-width="{width}" data-height="{height}">\n'
        + "\n".join(styles) + "\n"
        + (f"<style>{extra_css}</style>\n" if extra_css else "")
        + f'<div data-motion-slide-body{wrapper_attrs} style="{wrapper_style}">{content}</div>\n'
        "<script>\n"
        f'  window.__motionRunSlide(document.querySelector(\'[data-composition-id="{slide_id}"]\'),\n'
        f"    {{ slideId: {json.dumps(slide_id)}, template: {json.dumps(template)}, duration: {duration:.6f}"
        + (f", templates: {json.dumps(templates)}" if templates else "")
        + " });\n"
        "</script>\n"
        "</div>\n"
        "</template>\n"
    )
    return html, dropped


# The title card's backdrop: the first slide's own markup, dimmed and
# blurred, with a slow push-in, behind the burned-in title text (post.py's
# Title style). It needs no rendered screenshots, and it moves like
# everything else in an animation-first video.
TITLE_BACKDROP_TEMPLATES = {
    "title_backdrop": {"steps": [{"role": "slide", "effect": "drift", "params": {"scale": 1.1}}]},
}
TITLE_BACKDROP_CSS = "#root [data-motion-slide-body] { filter: blur(7px) brightness(0.55) saturate(1.1); }"


def build_project(ctx: MotionRenderContext, project_dir: Path) -> dict:
    """Write the HyperFrames project for one language into `project_dir`.
    Clip boundaries are whole frames rounded from the absolute timeline -
    the same `segment_frame_counts` validation relies on, so every slide is cut
    on the frame validation expects."""
    from multilingual_slide_video_agent.slides.render import _animation_asset_source

    width, height = _parse_viewport(ctx.viewport)
    if project_dir.exists():
        shutil.rmtree(project_dir)
    # The deck's own files (styles, assets) at the project root, so its
    # relative paths resolve unchanged.
    shutil.copytree(ctx.translated_deck_dir, project_dir)
    for stale in list_slide_files(project_dir):
        stale.unlink()
    for name in _INDEX_ASSETS:
        shutil.copy2(_animation_asset_source(ctx.animation_dir, name), project_dir / name)
    # The template definitions are project config, not per-deck data: a
    # bundle carries a snapshot from when it was generated, and it can't
    # know which motion style this render uses.
    style = str(ctx.motion_config.get("animation_style", "calm"))
    (project_dir / "templates_config.js").write_text(
        "window.__ANIMATION_TEMPLATES__ = " + json.dumps(load_template_config(style), ensure_ascii=False) + ";",
        encoding="utf-8",
    )
    compositions = project_dir / "compositions"
    compositions.mkdir(exist_ok=True)

    slide_files = {p.stem: p for p in list_slide_files(ctx.translated_deck_dir)}
    template_by_slide = {s.slide_id: s.template for s in ctx.slides}

    frame_counts = segment_frame_counts([t["end_time"] - t["start_time"] for t in ctx.timing], ctx.fps)
    clips, dropped_scripts = [], {}
    start_frame = 0
    for item, frames in zip(ctx.timing, frame_counts):
        if item.get("kind") == "title":
            first_slide = ctx.slides[0].slide_id
            html, _dropped = slide_to_template(
                slide_files[first_slide].read_text(encoding="utf-8"), slide_id=TITLE_COMPOSITION_ID,
                template="title_backdrop", width=width, height=height, duration=frames / ctx.fps,
                templates=TITLE_BACKDROP_TEMPLATES, extra_css=TITLE_BACKDROP_CSS,
            )
            (compositions / f"{TITLE_COMPOSITION_ID}.html").write_text(html, encoding="utf-8")
            cid = TITLE_COMPOSITION_ID
        else:
            cid = item["slide_id"]
            source = slide_files.get(cid)
            if source is None:
                raise MotionError(f"no translated slide file for '{cid}' in {ctx.translated_deck_dir}")
            html, dropped = slide_to_template(
                source.read_text(encoding="utf-8"), slide_id=cid, template=template_by_slide[cid],
                width=width, height=height, duration=frames / ctx.fps,
            )
            (compositions / f"{cid}.html").write_text(html, encoding="utf-8")
            if dropped:
                dropped_scripts[cid] = dropped
        clips.append(
            f'    <div class="clip" id="{cid}-host" data-composition-id="{cid}" '
            f'data-composition-src="compositions/{cid}.html" '
            f'data-start="{start_frame / ctx.fps:.6f}" data-duration="{frames / ctx.fps:.6f}" '
            f'data-track-index="0"></div>'
        )
        start_frame += frames

    index = (
        "<!DOCTYPE html>\n<html>\n<head>\n<meta charset=\"utf-8\">\n"
        '<link rel="stylesheet" href="design_tokens.css">\n'
        "<style>html, body { margin: 0; background: #000; }</style>\n"
        '<script src="gsap.min.js"></script>\n'
        '<script src="templates_config.js"></script>\n'
        '<script src="animation_runtime.js"></script>\n'
        "</head>\n<body>\n"
        f'  <div id="root" data-composition-id="root" data-start="0" data-width="{width}" data-height="{height}">\n'
        + "\n".join(clips) + "\n"
        "  </div>\n"
        "  <script>\n"
        "    window.__timelines = window.__timelines || {};\n"
        '    window.__timelines["root"] = gsap.timeline({ paused: true });\n'
        "  </script>\n"
        "</body>\n</html>\n"
    )
    (project_dir / "index.html").write_text(index, encoding="utf-8")
    return {"total_frames": start_frame, "width": width, "height": height, "animation_style": style,
            "dropped_scripts": dropped_scripts}


def _frame_count(path: Path) -> int:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets",
         "-show_entries", "stream=nb_read_packets", "-of", "csv=p=0", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    return int(out.split(",")[0])


class HyperFramesEngine:
    """Frame-exact rendering of the translated deck via HyperFrames."""

    name = "hyperframes"

    def check_available(self) -> list[str]:
        return check_available()

    def version(self) -> str | None:
        return hyperframes_version()

    def render(self, ctx: MotionRenderContext, work_dir: Path) -> Path:
        work_dir.mkdir(parents=True, exist_ok=True)
        engine_cfg = (ctx.motion_config.get("engines") or {}).get("hyperframes") or {}
        timeout = float(engine_cfg.get("timeout_seconds", 1800))
        encode = ctx.motion_config.get("encode", {})

        project = work_dir / "hf"
        built = build_project(ctx, project)
        (work_dir / "build.json").write_text(json.dumps(built, indent=2), encoding="utf-8")

        _run_cli(["check", str(project)], timeout=timeout, what="check")
        raw = work_dir / "hyperframes.mp4"
        _run_cli([
            "render", str(project), "-o", str(raw), "-f", str(ctx.fps),
            "--crf", str(encode.get("crf", 19)), "-w", str(engine_cfg.get("workers", "auto")),
            "--strict", "--quiet",
        ], timeout=timeout, what="render")

        frames = _frame_count(raw)
        if frames != built["total_frames"]:
            raise MotionError(
                f"hyperframes rendered {frames} frames instead of {built['total_frames']} - refusing a "
                "video whose slides would drift against their narration"
            )
        if (built["width"], built["height"]) == (ctx.resolution["width"], ctx.resolution["height"]):
            return raw

        # The deck is authored at the viewport size; scale once to the
        # output resolution.
        silent = work_dir / "silent.mp4"
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error", "-i", str(raw),
            "-vf", f"scale={ctx.resolution['width']}:{ctx.resolution['height']}",
            "-c:v", "libx264", "-preset", str(encode.get("preset", "medium")),
            "-crf", str(encode.get("crf", 19)), "-pix_fmt", str(encode.get("pix_fmt", "yuv420p")), "-an",
            str(silent),
        ], check=True, capture_output=True)
        if abs(ffprobe_duration(str(silent)) - ctx.total_duration) > 1.0 / ctx.fps:
            raise MotionError("scaled hyperframes video drifted from segment_timing's total by more than one frame")
        return silent
