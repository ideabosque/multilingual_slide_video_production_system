"""The `remotion` engine (motion-engines-and-hardening-plan B5, Phase 3), in
its deck-faithful mode: Remotion shows each translated slide in an iframe
and, on every frame, seeks the slide's paused GSAP timeline to
frame / fps - the same seek-mode runtime and the same per-slide timelines
HyperFrames renders. The "rebuilt look" React templates are deferred (Open
decision D4).

What this module decides, so the Remotion project (`motion/remotion/`)
stays a thin renderer:

- clip boundaries: whole frames from `segment_frame_counts`, identical to
  HyperFrames, so both engines cut every slide on the same frame;
- the pages: a copy of the translated deck with the animation runtime
  injected in seek mode into each slide (the deck's own scripts dropped,
  as HyperFrames does), plus the title card's backdrop page built from
  slide 1;
- the browser: the chrome-headless-shell `msv motion install` downloaded
  into `motion/node_modules/.remotion`, passed explicitly so a render never
  downloads anything (plan B3 #3).

The engine's contract is unchanged (base.py): an exact-length silent video.
Licensing (B5): Remotion's free license covers individuals and companies of
up to 3 people; `msv motion doctor` prints the reminder, and this engine is
never the default without an explicit decision (D1).
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from bs4 import BeautifulSoup

from multilingual_slide_video_agent.production.motion.clips import ClipPlan, plan_clips
from multilingual_slide_video_agent.production.motion.context import MotionRenderContext
from multilingual_slide_video_agent.production.motion.errors import MotionError
from multilingual_slide_video_agent.production.motion.hyperframes_engine import (
    MIN_NODE_MAJOR,
    TITLE_BACKDROP_TEMPLATES,
    _INJECTION_RE,
    copy_runtime_assets,
    _frame_count,
    _node_major,
    _parse_viewport,
    motion_dir,
)
from multilingual_slide_video_agent.slides.animation_templates import load_template_config
from multilingual_slide_video_agent.slides.extract_text import list_slide_files, tag_text_nodes

# The title page's backdrop look, the same as HyperFrames' TITLE_BACKDROP_CSS:
# in a standalone page the runtime's drift moves <body>.
TITLE_BACKDROP_PAGE_CSS = "body { filter: blur(7px) brightness(0.55) saturate(1.1); }"
TITLE_PAGE_NAME = "_motion_title.html"

# Runtime files every page loads (code from the installed package, design
# tokens from the deck's bundle); templates_config.js is generated.
_PAGE_ASSETS = ("gsap.min.js", "animation_runtime.js", "design_tokens.css")


def remotion_project_dir() -> Path:
    return motion_dir() / "remotion"


def browser_executable() -> Path | None:
    """The chrome-headless-shell Remotion downloaded at install time, if any."""
    cache = motion_dir() / "node_modules" / ".remotion" / "chrome-headless-shell"
    if not cache.exists():
        return None
    names = ("chrome-headless-shell.exe", "chrome-headless-shell")
    found = sorted(p for p in cache.rglob("*") if p.name in names and p.is_file())
    return found[0] if found else None


def check_available() -> list[str]:
    """Missing prerequisites; an empty list means ready. Never raises."""
    missing = []
    node = shutil.which("node")
    major = _node_major(node) if node else None
    if major is None:
        missing.append(f"Node.js {MIN_NODE_MAJOR}+ not found on PATH")
    elif major < MIN_NODE_MAJOR:
        missing.append(f"Node.js {major} found; the motion toolchain needs {MIN_NODE_MAJOR}+")
    if not (motion_dir() / "node_modules" / "@remotion" / "renderer").exists():
        missing.append(f"Remotion is not installed in {motion_dir()} (run: msv motion install)")
    elif browser_executable() is None:
        missing.append("Remotion's browser is not downloaded (run: msv motion install)")
    if not (remotion_project_dir() / "render.mjs").exists():
        missing.append(f"Remotion project not found at {remotion_project_dir()}")
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        missing.append("ffmpeg/ffprobe not found on PATH")
    return missing


def remotion_version() -> str | None:
    try:
        package = motion_dir() / "node_modules" / "remotion" / "package.json"
        return json.loads(package.read_text(encoding="utf-8"))["version"]
    except (OSError, ValueError, KeyError):
        return None


def _prepare_page(source: Path, dest: Path, *, slide_id: str, template: str, duration: float,
                  extra_css: str = "", steps: list | None = None, lead: float = 0.0) -> None:
    """One slide page in seek mode, with its text nodes tagged for motion
    design targets. The deck's own scripts are dropped (as HyperFrames
    does): they would run inside the frame on their own clock, and the
    animation comes from the runtime."""
    from multilingual_slide_video_agent.slides.render import inject_animation_page

    soup = BeautifulSoup(_INJECTION_RE.sub("", source.read_text(encoding="utf-8")), "lxml")
    tag_text_nodes(soup, slide_id)
    for script in soup.find_all("script"):
        script.decompose()
    dest.write_text(str(soup), encoding="utf-8")
    inject_animation_page(dest, template=template, slide_id=slide_id, motion_mode="seek",
                          duration=duration, extra_css=extra_css, steps=steps, lead=lead)


def _transition_props(clip: ClipPlan) -> dict:
    """The clip's transitions for the composition, which plays them on the
    iframe itself: in frames, local to the clip."""
    props = {}
    if clip.transition_in:
        props["enter"] = {k: clip.transition_in[k] for k in ("type", "direction", "frames")}
    if clip.transition_out:
        props["exit"] = {k: clip.transition_out[k] for k in ("type", "direction", "frames", "start")}
    return props


def build_public_dir(ctx: MotionRenderContext, public_dir: Path) -> dict:
    """Write the pages the Remotion composition shows into `public_dir`, and
    return the composition's input props (plus the total frame count)."""
    width, height = _parse_viewport(ctx.viewport)
    if public_dir.exists():
        shutil.rmtree(public_dir)
    deck = public_dir / "deck"
    # The deck's own files, so its relative asset paths resolve unchanged.
    shutil.copytree(ctx.translated_deck_dir, deck)
    copy_runtime_assets(ctx.animation_dir, deck, _PAGE_ASSETS)
    style = str(ctx.motion_config.get("animation_style", "calm"))
    templates = {**load_template_config(style), **TITLE_BACKDROP_TEMPLATES}
    (deck / "templates_config.js").write_text(
        "window.__ANIMATION_TEMPLATES__ = " + json.dumps(templates, ensure_ascii=False) + ";",
        encoding="utf-8",
    )

    slide_files = {p.stem: p for p in list_slide_files(ctx.translated_deck_dir)}
    clips = []
    plan = plan_clips(ctx)
    for clip in plan:
        common = dict(slide_id=clip.id, duration=clip.frames / ctx.fps, steps=clip.steps,
                      lead=clip.lead / ctx.fps)
        if clip.kind == "title":
            page = TITLE_PAGE_NAME
            _prepare_page(slide_files[ctx.slides[0].slide_id], deck / page, template="title_backdrop",
                          extra_css=TITLE_BACKDROP_PAGE_CSS, **common)
        else:
            source = slide_files.get(clip.id)
            if source is None:
                raise MotionError(f"no translated slide file for '{clip.id}' in {ctx.translated_deck_dir}")
            page = source.name
            _prepare_page(source, deck / page, template=clip.template, **common)
        clips.append({"id": clip.id, "src": f"deck/{page}", "from": clip.host_start,
                      "durationInFrames": clip.host_frames, **_transition_props(clip)})

    total = plan[-1].start + plan[-1].frames
    props = {"width": width, "height": height, "fps": ctx.fps, "durationInFrames": total, "clips": clips}
    return {"props": props, "total_frames": total, "animation_style": style}


def _concurrency(value) -> int | None:
    """motion.yaml's `concurrency`: `auto` (Remotion's default) or a count."""
    if value in (None, "auto"):
        return None
    return int(value)


class RemotionEngine:
    """Frame-exact rendering of the translated deck via Remotion, in iframes."""

    name = "remotion"

    def check_available(self) -> list[str]:
        return check_available()

    def version(self) -> str | None:
        return remotion_version()

    def render(self, ctx: MotionRenderContext, work_dir: Path) -> Path:
        work_dir.mkdir(parents=True, exist_ok=True)
        engine_cfg = (ctx.motion_config.get("engines") or {}).get("remotion") or {}
        timeout = float(engine_cfg.get("timeout_seconds", 1800))
        encode = ctx.motion_config.get("encode", {})

        built = build_public_dir(ctx, work_dir / "public")
        (work_dir / "build.json").write_text(json.dumps(built, indent=2), encoding="utf-8")

        width = built["props"]["width"]
        scale = ctx.resolution["width"] / width
        if abs(ctx.resolution["height"] - built["props"]["height"] * scale) > 0.5:
            raise MotionError(
                f"viewport {ctx.viewport} and output resolution {ctx.resolution} differ in aspect ratio"
            )
        output = work_dir / "remotion.mp4"
        args = {
            "publicDir": str(work_dir / "public"),
            "bundleDir": str(work_dir / "bundle"),
            "props": built["props"],
            "output": str(output),
            "crf": int(encode.get("crf", 19)),
            "x264Preset": str(encode.get("preset", "medium")),
            "concurrency": _concurrency(engine_cfg.get("concurrency", "auto")),
            "scale": scale,
            "browserExecutable": str(browser_executable()),
            "timeoutMs": int(engine_cfg.get("delay_render_timeout_seconds", 120) * 1000),
        }
        args_path = work_dir / "render_args.json"
        args_path.write_text(json.dumps(args, indent=2, ensure_ascii=False), encoding="utf-8")

        cmd = [shutil.which("node") or "node", str(remotion_project_dir() / "render.mjs"), str(args_path)]
        try:
            result = subprocess.run(cmd, cwd=motion_dir(), capture_output=True, text=True, encoding="utf-8",
                                    errors="replace", timeout=timeout)
        except subprocess.TimeoutExpired as e:
            raise MotionError(f"remotion render timed out after {timeout:.0f}s") from e
        report = _last_json_line(result.stdout)
        if result.returncode != 0 or not report.get("ok"):
            detail = report.get("error") or (result.stderr or result.stdout or "")[-2000:]
            browser = report.get("browser_errors") or []
            raise MotionError(
                f"remotion render failed (exit {result.returncode}): {detail}"
                + (f"\nbrowser errors: {' | '.join(browser)}" if browser else "")
            )

        frames = _frame_count(output)
        if frames != built["total_frames"]:
            raise MotionError(
                f"remotion rendered {frames} frames instead of {built['total_frames']} - refusing a "
                "video whose slides would drift against their narration"
            )
        return output


def _last_json_line(stdout: str) -> dict:
    for line in reversed((stdout or "").splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except ValueError:
                continue
    return {}
