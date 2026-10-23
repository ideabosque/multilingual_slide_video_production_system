"""Command-line entry point: `msv <group> <command>`.

Four groups, one per agent:
    msv slides ...       Agent 1 tools (slide_deck_localization) + Agent 2
                          building blocks (translation application,
                          Chromium rendering)
    msv production ...   Agent 2 tools (slideshow_video_production)
    msv publishing ...   Agent 3 tools (youtube_video_publishing)
    msv pipeline ...     Agent 4 tools (slide_video_orchestration) — state/CLI backbone

Every command prints one JSON object to stdout and exits 0 on success, 1
on a handled failure, so Claude (acting as any of the four agents) can
drive this entirely from Bash without parsing prose.
"""
from __future__ import annotations

import functools
import json
import sys
import time
from pathlib import Path

import click

from multilingual_slide_video_agent import config as cfg
from multilingual_slide_video_agent.state import PipelineState, STAGES

# Localization content routinely contains non-Latin scripts (Arabic, CJK,
# etc.) in titles/narration/warnings that end up in printed JSON. Windows'
# default console codepage (cp1252) can't encode most of that, which
# crashes the process on the print step *after* the actual render/upload/
# state work already succeeded - a misleading non-zero exit that looks
# like the work itself failed. Force UTF-8 on stdout/stderr unconditionally
# so `msv`'s exit code always reflects whether the command's work
# succeeded, never whether the terminal's codepage could print the result.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")


def _echo_result(result: dict) -> None:
    click.echo(json.dumps(result, indent=2, ensure_ascii=False))
    if not result.get("ok", True):
        sys.exit(1)


def handle_errors(func):
    """Turn a missing run_id / bad state lookup into the same {"ok": false,
    "errors": [...]} JSON shape every other command uses, instead of a
    Python traceback — callers only ever need to parse JSON."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except (FileNotFoundError, ValueError, RuntimeError) as e:
            _echo_result({"ok": False, "errors": [str(e)]})

    return wrapper


@click.group()
def main() -> None:
    """Multilingual Slide Video Agent CLI."""


# ---------------------------------------------------------------------------
# msv slides ... (Agent 1 + Agent 2 shared deck tools)
# ---------------------------------------------------------------------------

@main.group()
def slides() -> None:
    """Agent 1: slide text extraction & analysis tools. Also used by
    Agent 2 to apply translations and re-render the translated deck."""


@slides.command("extract-text")
@click.option("--deck-dir", required=True, type=click.Path(exists=True, file_okay=False))
@click.option("--out", required=True, type=click.Path())
def slides_extract_text(deck_dir: str, out: str) -> None:
    """Parse every slide's HTML and assign stable node IDs to translatable text."""
    from multilingual_slide_video_agent.slides.extract_text import extract_deck_text

    manifest = extract_deck_text(deck_dir, out)
    click.echo(json.dumps(manifest, indent=2, ensure_ascii=False))


@slides.command("render-images")
@click.option("--deck-dir", required=True, type=click.Path(exists=True, file_okay=False))
@click.option("--out", required=True, type=click.Path())
@click.option("--viewport", default="1920x1080", show_default=True)
def slides_render_images(deck_dir: str, out: str, viewport: str) -> None:
    """Screenshot every slide via headless Chromium (Playwright)."""
    from multilingual_slide_video_agent.slides.render import render_deck_images

    manifest = render_deck_images(deck_dir=deck_dir, out_dir=out, viewport=viewport)
    click.echo(json.dumps(manifest, indent=2, ensure_ascii=False))


@slides.command("apply-translations")
@click.option("--deck-dir", required=True, type=click.Path(exists=True, file_okay=False), help="The ORIGINAL clean source deck - never a previously translated one")
@click.option("--localization", required=True, type=click.Path(exists=True), help="Agent 1's localization_<language>.json")
@click.option("--out", required=True, type=click.Path())
def slides_apply_translations(deck_dir: str, localization: str, out: str) -> None:
    """Apply a language's slide_translations back into the original deck's HTML, by node ID."""
    from multilingual_slide_video_agent.slides.apply_translations import ApplyTranslationsError, apply_translations

    try:
        result = apply_translations(deck_dir=deck_dir, localization_path=localization, out_dir=out)
    except ApplyTranslationsError as e:
        _echo_result({"ok": False, "errors": [str(e)]})
        return
    result["ok"] = True
    click.echo(json.dumps(result, indent=2, ensure_ascii=False))


@slides.command("validate")
@click.option("--slide-analysis", type=click.Path(exists=True))
@click.option("--localization", type=click.Path(exists=True))
@click.option("--language")
@click.option("--manifest", type=click.Path(exists=True), help="slides/manifest.json, to check node ID coverage")
@click.option("--project", type=click.Path(exists=True), help="Optional project.json with extra terminology")
def slides_validate(slide_analysis: str | None, localization: str | None, language: str | None, manifest: str | None, project: str | None) -> None:
    """Validate slide_analysis.json and/or localization_<language>.json."""
    from multilingual_slide_video_agent.slides.validate import validate_localization

    _echo_result(
        validate_localization(
            slide_analysis_path=slide_analysis, localization_path=localization,
            language=language, manifest_path=manifest, project_path=project,
        )
    )


@slides.command("generate-animation")
@click.option("--deck-dir", required=True, type=click.Path(exists=True, file_okay=False), help="The original clean source deck")
@click.option("--out", required=True, type=click.Path())
@click.option("--slide-analysis", type=click.Path(exists=True), help="slide_analysis.json, improves template selection via slide descriptions")
@click.option("--spec", "spec_path", type=click.Path(exists=True), help="Optional explicit slide_id -> template_name JSON override; default is the built-in role heuristic")
def slides_generate_animation(deck_dir: str, out: str, slide_analysis: str | None, spec_path: str | None) -> None:
    """Generate one deck's GSAP animation bundle, once (marketing_animation_pipeline_plan §4.1)."""
    from multilingual_slide_video_agent.slides.generate_animation import (
        GenerateAnimationError,
        generate_deck_animation,
    )

    spec_override = json.loads(Path(spec_path).read_text(encoding="utf-8")) if spec_path else None
    try:
        manifest = generate_deck_animation(
            deck_dir=deck_dir, out_dir=out, slide_analysis_path=slide_analysis, spec_override=spec_override,
        )
    except GenerateAnimationError as e:
        _echo_result({"ok": False, "errors": [str(e)]})
        return
    manifest["ok"] = True
    click.echo(json.dumps(manifest, indent=2, ensure_ascii=False))



@slides.command("extract-roles")
@click.option("--deck-dir", required=True, type=click.Path(exists=True, file_okay=False), help="The translated deck to read roles from (msv slides apply-translations output)")
@click.option("--animation-dir", required=True, type=click.Path(exists=True, file_okay=False), help="The deck's generated animation bundle (msv slides generate-animation output), for spec.json's per-slide template")
@click.option("--out", required=True, type=click.Path(), help="Where to write roles_<language>.json (convention: the run's analysis/slides/animation/ directory)")
@click.option("--viewport", default="1920x1080", show_default=True)
def slides_extract_roles(deck_dir: str, animation_dir: str, out: str, viewport: str) -> None:
    "Extract each translated slide's resolved animation roles into roles_<language>.json (plan B3 #2)."
    from multilingual_slide_video_agent.slides.extract_roles import ExtractRolesError, extract_deck_roles

    try:
        manifest = extract_deck_roles(
            translated_deck_dir=deck_dir, animation_dir=animation_dir, out_path=out, viewport=viewport,
        )
    except ExtractRolesError as e:
        _echo_result({"ok": False, "errors": [str(e)]})
        return
    manifest["ok"] = True
    click.echo(json.dumps(manifest, indent=2, ensure_ascii=False))


@slides.command("inspect-layout")
@click.option("--deck-dir", required=True, type=click.Path(exists=True, file_okay=False), help="The deck to map: the original deck when designing motion, a translated deck to check one language")
@click.option("--out", required=True, type=click.Path(), help="Where to write layout_map.json (convention: the run's analysis/slides/animation/)")
@click.option("--annotate-dir", type=click.Path(file_okay=False), help="Also save each slide's screenshot with numbered boxes on its targetable elements")
@click.option("--viewport", default="1920x1080", show_default=True)
def slides_inspect_layout(deck_dir: str, out: str, annotate_dir: str | None, viewport: str) -> None:
    "Map each slide's targetable elements for motion design: node ids, boxes, repeated groups, SVG shapes, roles (plan C4)."
    from multilingual_slide_video_agent.slides.layout_map import LayoutMapError, inspect_layout

    try:
        layout = inspect_layout(deck_dir=deck_dir, out_path=out, annotate_dir=annotate_dir, viewport=viewport)
    except LayoutMapError as e:
        _echo_result({"ok": False, "errors": [str(e)]})
        return
    _echo_result({
        "ok": True, "out": str(Path(out).resolve()), "deck_fingerprint": layout["deck_fingerprint"],
        "slides": [{"slide_id": s["slide_id"], "elements": len(s["elements"]), "groups": len(s["groups"]),
                    "svg_shapes": len(s["svg_shapes"]), **({"annotated_image": s["annotated_image"]}
                                                           if "annotated_image" in s else {})}
                   for s in layout["slides"]],
    })


@slides.command("validate-motion")
@click.option("--design", "design_path", required=True, type=click.Path(exists=True), help="The deck's motion_design.json (motion-design/v1)")
@click.option("--deck-dir", required=True, type=click.Path(exists=True, file_okay=False), help="The deck the design targets: the original deck, or a translated deck to check one language")
@click.option("--layout-map", "layout_map_path", type=click.Path(exists=True), help="layout_map.json from msv slides inspect-layout, to check role targets")
@click.option("--production", "production_paths", multiple=True, type=click.Path(exists=True), help="A narrated language's production.json, for slide durations (repeatable; the shortest wins). Without one, timing and comfort checks are skipped")
@click.option("--source-deck", type=click.Path(exists=True, file_okay=False), help="The original deck, whose fingerprint the design must carry (defaults to --deck-dir)")
def slides_validate_motion(design_path: str, deck_dir: str, layout_map_path: str | None,
                           production_paths: tuple[str, ...], source_deck: str | None) -> None:
    "Check a motion design before rendering: schema, targets, brand, comfort and timing guardrails (plan C5). Problems name the slide and step."
    from multilingual_slide_video_agent.production.motion.clips import duration_tokens
    from multilingual_slide_video_agent.slides.animation_templates import load_template_config
    from multilingual_slide_video_agent.slides.design_system import load_design_system
    from multilingual_slide_video_agent.slides.motion_checks import (
        brand_color_tokens, check_motion_design, slide_durations_from_productions,
    )
    from multilingual_slide_video_agent.state import directory_fingerprint

    try:
        doc = json.loads(Path(design_path).read_text(encoding="utf-8"))
    except ValueError as e:
        _echo_result({"ok": False, "errors": [f"can't read {design_path}: {e}"]})
        return
    layout = json.loads(Path(layout_map_path).read_text(encoding="utf-8")) if layout_map_path else None
    productions = [json.loads(Path(p).read_text(encoding="utf-8")) for p in production_paths]
    tokens = load_design_system()
    style = str(cfg.motion_config().get("animation_style", "calm"))
    result = check_motion_design(
        doc, deck_dir=deck_dir, presets=set(load_template_config(style)), tokens=duration_tokens(tokens),
        brand_colors=brand_color_tokens(tokens), layout_map=layout,
        slide_durations=slide_durations_from_productions(productions) or None,
        source_fingerprint=directory_fingerprint(source_deck or deck_dir),
    )
    errors = result["errors"] + [e for errs in result["slide_errors"].values() for e in errs]
    _echo_result({"ok": result["ok"], "errors": errors, "failing_slides": sorted(result["slide_errors"]),
                  "warnings": result["warnings"], "design": str(Path(design_path).resolve())})


# ---------------------------------------------------------------------------
# msv production ... (Agent 2)
# ---------------------------------------------------------------------------

@main.group()
def production() -> None:
    """Agent 2: voice & slideshow production tools."""


@production.command("narrate")
@click.option("--run-id", required=True)
@click.option("--project-id", required=True)
@click.option("--language", required=True)
@click.option("--source-deck", required=True, type=click.Path(exists=True, file_okay=False), help="The original clean deck, for the source_deck_fingerprint idempotency check")
@click.option("--localization", required=True, type=click.Path(exists=True), help="Agent 1's localization_<language>.json")
@click.option("--output-dir", required=True, type=click.Path())
@click.option("--audio-dir", type=click.Path(), help="Reuse pre-generated per-slide mp3s named <slide_id>.mp3")
def production_narrate(
    run_id: str, project_id: str, language: str, source_deck: str, localization: str,
    output_dir: str, audio_dir: str | None,
) -> None:
    """The `tts` stage: narrate one language (TTS, narration-driven slide timing, captions) into production.json, with no video. render-motion renders the animated video next."""
    from multilingual_slide_video_agent.production.render_slideshow import ProductionError, narrate_language

    try:
        envelope = narrate_language(
            run_id=run_id, project_id=project_id, language=language, source_deck=source_deck,
            localization_path=localization, output_dir=output_dir, audio_dir=audio_dir,
        )
    except ProductionError as e:
        _echo_result({"agent": "slideshow_production_agent", "status": "failed", "ok": False, "errors": [str(e)]})
        return
    envelope["ok"] = envelope.get("status") == "completed"
    _echo_result(envelope)


@production.command("render-slideshow")
@click.option("--run-id", required=True)
@click.option("--project-id", required=True)
@click.option("--language", required=True)
@click.option("--source-deck", required=True, type=click.Path(exists=True, file_okay=False), help="The original clean deck, for the source_deck_fingerprint idempotency check")
@click.option("--slides-dir", required=True, type=click.Path(exists=True, file_okay=False), help="This language's rendered slide images (msv slides render-images output)")
@click.option("--localization", required=True, type=click.Path(exists=True), help="Agent 1's localization_<language>.json")
@click.option("--output-dir", required=True, type=click.Path())
@click.option("--audio-dir", type=click.Path(), help="Reuse pre-generated per-slide mp3s named <slide_id>.mp3")
@click.option("--no-burn-in", is_flag=True, default=False, help="Skip burning captions in; still emits captions.srt")
def production_render_slideshow(
    run_id: str, project_id: str, language: str, source_deck: str, slides_dir: str, localization: str,
    output_dir: str, audio_dir: str | None, no_burn_in: bool,
) -> None:
    """Assemble one language's localized slideshow video (TTS + captions + FFmpeg)."""
    from multilingual_slide_video_agent.production.render_slideshow import ProductionError, render_language

    try:
        envelope = render_language(
            run_id=run_id, project_id=project_id, language=language, source_deck=source_deck,
            slides_dir=slides_dir, localization_path=localization, output_dir=output_dir,
            audio_dir=audio_dir, burn_in_override=(False if no_burn_in else None),
        )
    except ProductionError as e:
        _echo_result({"agent": "slideshow_production_agent", "status": "failed", "ok": False, "errors": [str(e)]})
        return
    envelope["ok"] = envelope.get("status") == "completed"
    _echo_result(envelope)


@production.command("validate")
@click.option("--production", "production_path", required=True, type=click.Path(exists=True))
@click.option("--localization", type=click.Path(exists=True))
@click.option("--run-id")
def production_validate(production_path: str, localization: str | None, run_id: str | None) -> None:
    """Validate a rendered language's production.json."""
    from multilingual_slide_video_agent.production.validate import validate_production

    _echo_result(validate_production(production_path=production_path, localization_path=localization, run_id=run_id))


@production.command("render-motion")
@click.option("--engine", type=click.Choice(["hyperframes", "remotion"]), help="Defaults to config/motion.yaml's default_engine")
@click.option("--production", "production_path", required=True, type=click.Path(exists=True), help="A narrated language's production.json (msv production narrate output)")
@click.option("--translated-deck-dir", required=True, type=click.Path(exists=True, file_okay=False), help="This language's translated HTML deck (msv slides apply-translations output)")
@click.option("--animation-dir", required=True, type=click.Path(exists=True, file_okay=False), help="The deck's generated animation bundle (msv slides generate-animation output)")
@click.option("--slides-dir", type=click.Path(exists=True, file_okay=False), help="Rendered slide images (msv slides render-images). Optional; the HyperFrames engine does not need them")
@click.option("--localization", type=click.Path(exists=True), help="Agent 1's localization_<language>.json, for caption text")
@click.option("--roles", "roles_path", type=click.Path(exists=True), help="roles_<language>.json from msv slides extract-roles (optional; recorded per slide in the render context)")
@click.option("--motion-design", "motion_design_path", type=click.Path(exists=True), help="The deck's motion_design.json (motion-design/v1), played instead of each slide's template. Validated before rendering")
@click.option("--output-dir", type=click.Path(), help="Defaults to the production.json directory")
@click.option("--output-name", help="Defaults to video.mp4")
@click.option("--viewport", default="1920x1080", show_default=True)
def production_render_motion(
    engine: str | None, production_path: str, translated_deck_dir: str, animation_dir: str, slides_dir: str | None,
    localization: str | None, roles_path: str | None, motion_design_path: str | None, output_dir: str | None,
    output_name: str | None, viewport: str,
) -> None:
    """The `rendering` stage: render a narrated language (msv production narrate) as its animated video with a motion engine, and record it in production.json. Writes <output>.mp4 plus <output>.motion.json."""
    from multilingual_slide_video_agent.production.motion.errors import MotionError
    from multilingual_slide_video_agent.production.motion.render import render_motion

    try:
        envelope = render_motion(
            production_path=production_path, translated_deck_dir=translated_deck_dir,
            animation_dir=animation_dir, slides_dir=slides_dir, localization_path=localization,
            roles_path=roles_path, output_dir=output_dir, output_name=output_name,
            engine_name=engine, viewport=viewport, motion_design_path=motion_design_path,
        )
    except MotionError as e:
        _echo_result({"agent": "slideshow_production_agent", "status": "failed", "ok": False, "errors": [str(e)]})
        return
    envelope["ok"] = envelope.get("status") == "completed"
    _echo_result(envelope)



# ---------------------------------------------------------------------------
# msv motion ... (Agent 2; Part B of motion-engines-and-hardening-plan)
# ---------------------------------------------------------------------------

@main.group()
def motion() -> None:
    "The Node toolchain behind the HyperFrames/Remotion engines (plan B3 #3). A missing toolchain only disables the two Node engines; the Python-only path never needs it."


@motion.command("install")
def motion_install() -> None:
    "Run npm ci in motion/ - a pinned install from the committed package-lock.json (never a bare install, never npx at render time, plan B3 #3)."
    import shutil
    import subprocess

    motion_dir = cfg.root_dir() / "motion"
    if not (motion_dir / "package.json").exists():
        _echo_result({"ok": True, "installed": False, "message": "no motion/package.json scaffold yet (plan phases 2a/2b add it); nothing to install"})
        return
    if not (motion_dir / "package-lock.json").exists():
        # `npm ci` refuses to run without a lockfile, and installing without
        # one would defeat the pinning this command exists for.
        _echo_result({"ok": False, "errors": [
            "motion/package-lock.json is missing - run `npm install --package-lock-only` in motion/ "
            "and commit the lockfile (plan B3 #3: pinned installs only)"
        ]})
        return
    npm = shutil.which("npm")
    if not npm:
        _echo_result({"ok": False, "errors": ["npm not on PATH - install Node 22+ first (see msv motion doctor)"]})
        return
    try:
        subprocess.run([npm, "ci", "--prefix", str(motion_dir)], check=True, capture_output=True, text=True)
    except OSError as e:
        _echo_result({"ok": False, "errors": [f"npm ci failed: {e}"]})
        return
    except subprocess.SubprocessError as e:
        stderr = (getattr(e, "stderr", "") or str(e))[-2000:]
        _echo_result({"ok": False, "errors": [f"npm ci failed: {stderr}"]})
        return
    # Remotion renders with its own pinned chrome-headless-shell. Download it
    # now, so a render never fetches anything (plan B3 #3).
    ensure = motion_dir / "remotion" / "ensure-browser.mjs"
    browser = None
    if ensure.exists():
        result = subprocess.run([shutil.which("node") or "node", str(ensure)], cwd=motion_dir,
                                capture_output=True, text=True)
        if result.returncode != 0:
            _echo_result({"ok": False, "errors": [
                f"Remotion's browser download failed: {(result.stdout + result.stderr)[-2000:]}"
            ]})
            return
        browser = json.loads(result.stdout.strip().splitlines()[-1]).get("status", {}).get("path")
    _echo_result({
        "ok": True, "installed": True,
        "from_lockfile": (motion_dir / "package-lock.json").exists(),
        "motion_dir": str(motion_dir),
        "remotion_browser": browser,
    })


@motion.command("preview")
@click.option("--production", "production_path", required=True, type=click.Path(exists=True), help="A narrated language's production.json (msv production narrate output)")
@click.option("--translated-deck-dir", required=True, type=click.Path(exists=True, file_okay=False))
@click.option("--animation-dir", required=True, type=click.Path(exists=True, file_okay=False))
@click.option("--motion-design", "motion_design_path", type=click.Path(exists=True), help="The design to preview; without it, the slides' templates")
@click.option("--localization", type=click.Path(exists=True), help="For captions (optional)")
@click.option("--engine", type=click.Choice(["remotion", "hyperframes"]), help="Defaults to config/motion.yaml's default_engine")
@click.option("--res", "res", default="640x360", show_default=True, help="Output size; the deck still lays out at --viewport")
@click.option("--fps", default=12, show_default=True, type=int)
@click.option("--out-dir", type=click.Path(file_okay=False), help="Defaults to <production dir>/motion_preview")
@click.option("--slides", "slide_ids", help="Comma-separated slide ids for the filmstrip (default: every slide)")
@click.option("--viewport", default="1920x1080", show_default=True)
def motion_preview(
    production_path: str, translated_deck_dir: str, animation_dir: str, motion_design_path: str | None,
    localization: str | None, engine: str | None, res: str, fps: int, out_dir: str | None,
    slide_ids: str | None, viewport: str,
) -> None:
    "Render a small, fast preview of a language with a motion design, plus its filmstrip, for review (plan C6). It never touches production.json and is not held by the motion approval gate."
    from multilingual_slide_video_agent.production.motion.errors import MotionError
    from multilingual_slide_video_agent.production.motion.filmstrip import filmstrip_for_render
    from multilingual_slide_video_agent.production.motion.render import render_motion

    try:
        width, height = (int(v) for v in res.lower().split("x"))
    except ValueError:
        _echo_result({"ok": False, "errors": [f"--res must look like 640x360, got {res!r}"]})
        return
    out = Path(out_dir) if out_dir else Path(production_path).resolve().parent / "motion_preview"
    video, motion_json = out / "preview.mp4", out / "preview.motion.json"
    errors, warnings = [], []
    try:
        envelope = render_motion(
            production_path=production_path, translated_deck_dir=translated_deck_dir, animation_dir=animation_dir,
            localization_path=localization, output_dir=str(out), output_name="preview.mp4", engine_name=engine,
            viewport=viewport, record_in_production=False, motion_design_path=motion_design_path,
            fps=fps, resolution={"width": width, "height": height}, motion_gate=False,
        )
        warnings = envelope.get("warnings", [])
    except MotionError as e:
        errors.append(str(e))
    result: dict = {"ok": not errors, "errors": errors, "warnings": warnings}
    if video.exists() and motion_json.exists():
        # Even a preview that failed validation is worth looking at.
        strip = filmstrip_for_render(video, motion_json, out / "preview_filmstrip.png",
                                     slide_ids=slide_ids.split(",") if slide_ids else None)
        manifest = json.loads(motion_json.read_text(encoding="utf-8"))
        result.update({"video": str(video), "filmstrip": str(strip), "motion_json": str(motion_json),
                       "fallback": (manifest.get("motion_design") or {}).get("fallback", {}),
                       "validation_errors": manifest.get("validation", {}).get("errors", [])})
    _echo_result(result)


@motion.command("filmstrip")
@click.option("--video", required=True, type=click.Path(exists=True))
@click.option("--motion-json", required=True, type=click.Path(exists=True), help="The video's <stem>.motion.json from render-motion")
@click.option("--out", required=True, type=click.Path())
@click.option("--slides", "slide_ids", help="Comma-separated slide ids (default: every slide)")
def motion_filmstrip(video: str, motion_json: str, out: str, slide_ids: str | None) -> None:
    "One row per slide, frames at 0/15/30/60/95% of it, for reviewing motion (plan C6)."
    from multilingual_slide_video_agent.production.motion.errors import MotionError
    from multilingual_slide_video_agent.production.motion.filmstrip import filmstrip_for_render

    try:
        path = filmstrip_for_render(video, motion_json, out, slide_ids=slide_ids.split(",") if slide_ids else None)
    except MotionError as e:
        _echo_result({"ok": False, "errors": [str(e)]})
        return
    _echo_result({"ok": True, "filmstrip": str(path)})


@motion.command("schema")
def motion_schema() -> None:
    "Print the motion-design/v1 JSON Schema, generated from the validator's own vocabulary (the language reference for writing designs)."
    from multilingual_slide_video_agent.slides.motion_design import json_schema

    _echo_result({"ok": True, "schema": json_schema()})


@motion.command("doctor")
def motion_doctor() -> None:
    "Environment check for motion rendering (plan B3 #3): Node, ffmpeg, Chromium, each engine's availability, plus the Remotion license reminder (B5)."
    import shutil
    import subprocess as sp

    from multilingual_slide_video_agent.production.motion import render as motion_render
    from multilingual_slide_video_agent.production.motion.errors import MotionError
    from multilingual_slide_video_agent.slides.render import chromium_available

    node_path = shutil.which("node")
    node_version = None
    if node_path:
        try:
            node_version = sp.run([node_path, "--version"], capture_output=True, text=True, check=True).stdout.strip()
        except Exception:
            node_version = "unknown"
    node_major = int(node_version.lstrip("v").split(".")[0]) if node_version and node_version.lstrip("v").split(".")[0].isdigit() else None

    engines = {}
    for name in motion_render.KNOWN_ENGINE_NAMES:
        try:
            engine = motion_render.get_engine(name)
            missing = engine.check_available()
        except MotionError as e:
            engines[name] = {"available": False, "missing": [str(e)]}
            continue
        engines[name] = {"available": not missing, "missing": missing}

    _echo_result({
        "ok": True,
        "checks": {
            "ffmpeg": bool(shutil.which("ffmpeg")),
            "ffprobe": bool(shutil.which("ffprobe")),
            "node": {
                "present": bool(node_path), "version": node_version,
                "meets_hyperframes_min": node_major is not None and node_major >= 22,
            },
            "playwright_chromium": chromium_available(),
        },
        "engines": engines,
        "remotion_license_reminder": (
            "Remotion's free tier covers individuals and companies of <=3 people; re-check on headcount "
            "growth, any automated-service offering, or a Remotion 5.x upgrade (plan B5). It is the "
            "default engine by the user's decision of 2026-10-22 (D1); --engine hyperframes avoids it."
        ),
    })


# ---------------------------------------------------------------------------
# msv publishing ... (Agent 3)
# ---------------------------------------------------------------------------

@main.group()
def publishing() -> None:
    """Agent 3: YouTube publishing tools."""


@publishing.command("validate")
@click.option("--metadata", "metadata_path", required=True, type=click.Path(exists=True))
@click.option("--language", required=True)
@click.option("--video", type=click.Path())
def publishing_validate(metadata_path: str, language: str, video: str | None) -> None:
    """Validate metadata_<language>.json before upload."""
    from multilingual_slide_video_agent.publishing.validate import validate_metadata

    _echo_result(validate_metadata(metadata_path=metadata_path, language=language, video_path=video))


@publishing.command("upload")
@click.option("--run-id", required=True)
@click.option("--project-id", required=True)
@click.option("--language", required=True)
@click.option("--video", type=click.Path(exists=True), help="Required unless --existing-video-id is given")
@click.option("--metadata", "metadata_path", required=True, type=click.Path(exists=True))
@click.option("--output-dir", required=True, type=click.Path())
@click.option("--existing-video-id", help="Metadata-only update of an already-published video; skips upload")
def publishing_upload(
    run_id: str, project_id: str, language: str, video: str | None,
    metadata_path: str, output_dir: str, existing_video_id: str | None,
) -> None:
    """Upload (or metadata-only update) one language's video to YouTube."""
    from multilingual_slide_video_agent.publishing.youtube import publish_video

    envelope = publish_video(
        run_id=run_id, project_id=project_id, language=language, video_path=video,
        metadata_path=metadata_path, output_dir=output_dir, existing_video_id=existing_video_id,
    )
    envelope["ok"] = envelope.get("status") == "completed"
    _echo_result(envelope)


@publishing.command("get-refresh-token")
@click.option(
    "--client-secrets-file",
    default=None,
    help="Defaults to YOUTUBE_CLIENT_SECRETS_FILE (or config/youtube_client_secret.json)",
)
@handle_errors
def publishing_get_refresh_token(client_secrets_file: str | None) -> None:
    """One-time interactive helper: mint a YouTube OAuth refresh token."""
    from multilingual_slide_video_agent.publishing.oauth import get_refresh_token

    path = client_secrets_file or str(cfg.youtube_client_secrets_file())
    token = get_refresh_token(path)
    click.echo("\nAdd this to .env:\nYOUTUBE_REFRESH_TOKEN=" + token)


# ---------------------------------------------------------------------------
# msv pipeline ... (Agent 4)
# ---------------------------------------------------------------------------

@main.group()
def pipeline() -> None:
    """Agent 4: pipeline orchestration state/CLI backbone."""


def _generate_run_id(project_id: str) -> str:  # noqa: ARG001 - kept for signature symmetry/future per-project seeding
    date_part = time.strftime("%Y%m%d", time.gmtime())
    from multilingual_slide_video_agent.config import state_dir

    state_dir().mkdir(parents=True, exist_ok=True)
    existing = sorted(state_dir().glob(f"run-{date_part}-*.json"))
    seq = len(existing) + 1
    while True:
        candidate = f"run-{date_part}-{seq:03d}"
        if not (state_dir() / f"{candidate}.json").exists():
            return candidate
        seq += 1


def _resolve_run_id(run_id: str | None, project_id: str | None) -> str | None:
    if run_id:
        return run_id
    if project_id:
        return PipelineState.latest_run_for_project(project_id)
    return None


@pipeline.command("init")
@click.option("--project-id", required=True)
@click.option("--source-deck", required=True, type=click.Path(exists=True, file_okay=False))
@click.option("--languages", help="Comma-separated; defaults to SUPPORTED_LANGUAGES")
@click.option("--run-id", help="Defaults to an auto-generated run-YYYYMMDD-NNN")
@click.option("--auto-publish", type=bool, default=None)
@click.option("--default-language", help="Rendered and reviewed first; defaults to DEFAULT_LANGUAGE. Every other language's translation stage is held until it's approved (msv pipeline approve-production).")
@click.option("--auto-approve-production", type=bool, default=None, help="Skip the default-language approval gate entirely (defaults to PIPELINE_AUTO_APPROVE_PRODUCTION, false)")
@click.option("--auto-approve-motion", type=bool, default=None, help="Let a validated motion design render every language without human approval (defaults to PIPELINE_AUTO_APPROVE_MOTION, false)")
def pipeline_init(
    project_id: str, source_deck: str, languages: str | None, run_id: str | None, auto_publish: bool | None,
    default_language: str | None, auto_approve_production: bool | None, auto_approve_motion: bool | None,
) -> None:
    """Create a new pipeline run (run_pipeline, part 1)."""
    from multilingual_slide_video_agent.logging_utils import RunLogger

    language_list = [lang.strip() for lang in languages.split(",")] if languages else cfg.supported_languages()
    unknown = [lang for lang in language_list if lang not in cfg.languages_config().get("languages", {})]
    if unknown:
        _echo_result({"ok": False, "errors": [f"Unsupported language(s), add to config/languages.yaml first: {unknown}"]})
        return

    resolved_run_id = run_id or _generate_run_id(project_id)
    if PipelineState.exists(resolved_run_id):
        _echo_result({"ok": False, "errors": [f"run_id '{resolved_run_id}' already exists; use next-actions to resume instead"]})
        return

    resolved_auto_publish = auto_publish if auto_publish is not None else cfg.env_bool("PIPELINE_AUTO_PUBLISH", False)
    resolved_default_language = default_language or cfg.default_language()
    if resolved_default_language not in language_list:
        _echo_result({"ok": False, "errors": [f"--default-language '{resolved_default_language}' is not in the requested languages {language_list}"]})
        return
    resolved_auto_approve_production = (
        auto_approve_production if auto_approve_production is not None
        else cfg.env_bool("PIPELINE_AUTO_APPROVE_PRODUCTION", False)
    )
    state = PipelineState.create(
        run_id=resolved_run_id, project_id=project_id, source_deck=source_deck,
        language_codes=language_list, auto_publish=resolved_auto_publish,
        default_language=resolved_default_language, auto_approve_production=resolved_auto_approve_production,
        auto_approve_motion=(auto_approve_motion if auto_approve_motion is not None
                             else cfg.env_bool("PIPELINE_AUTO_APPROVE_MOTION", False)),
    )
    RunLogger(resolved_run_id, project_id).log(
        agent="pipeline_orchestrator_agent", skill="slide_video_orchestration",
        event="run_initialized", status="completed", languages=language_list,
    )
    _echo_result({"ok": True, "run_id": resolved_run_id, "report": state.to_report(), "next_actions": state.next_actions()})


@pipeline.command("status")
@click.option("--run-id")
@click.option("--project-id", help="Resolves to the latest run for this project if --run-id is omitted")
@handle_errors
def pipeline_status(run_id: str | None, project_id: str | None) -> None:
    """get_pipeline_status."""
    resolved = _resolve_run_id(run_id, project_id)
    if resolved is None:
        _echo_result({"ok": False, "errors": [f"no run found for project_id '{project_id}'"]})
        return
    state = PipelineState.load(resolved)
    _echo_result({"ok": True, "report": state.to_report()})


@pipeline.command("next-actions")
@click.option("--run-id")
@click.option("--project-id")
@click.option("--languages", help="Comma-separated subset to plan for")
@handle_errors
def pipeline_next_actions(run_id: str | None, project_id: str | None, languages: str | None) -> None:
    """What run_pipeline/resume_pipeline should do next."""
    resolved = _resolve_run_id(run_id, project_id)
    if resolved is None:
        _echo_result({"ok": False, "errors": [f"no run found for project_id '{project_id}'"]})
        return
    state = PipelineState.load(resolved)
    language_list = [lang.strip() for lang in languages.split(",")] if languages else None
    _echo_result({
        "ok": True, "run_id": resolved,
        "next_actions": state.next_actions(language_list),
        "overall_status": state.overall_status(),
    })


@pipeline.command("set-stage")
@click.option("--run-id", required=True)
@click.option("--language", required=True)
@click.option("--stage", required=True, type=click.Choice(STAGES))
@click.option("--status", "stage_status", required=True, type=click.Choice(["pending", "in_progress", "completed", "failed", "skipped"]))
@click.option("--error")
@click.option("--artifact", multiple=True, help="key=value, repeatable")
@click.option("--retry", is_flag=True, default=False, help="Increment this stage's retry_count")
@click.option("--youtube-video-id")
@click.option("--youtube-url")
@handle_errors
def pipeline_set_stage(
    run_id: str, language: str, stage: str, stage_status: str, error: str | None,
    artifact: tuple[str, ...], retry: bool, youtube_video_id: str | None, youtube_url: str | None,
) -> None:
    """Record one stage's outcome."""
    from multilingual_slide_video_agent.logging_utils import RunLogger

    artifacts = {}
    for pair in artifact:
        key, _, value = pair.partition("=")
        artifacts[key] = value
    with PipelineState.transaction(run_id) as state:
        state.set_stage(language, stage, stage_status, artifacts=artifacts or None, error=error, increment_retry=retry)
        if youtube_video_id:
            state.set_youtube_result(language, youtube_video_id, youtube_url or "")

    RunLogger(run_id, state.project_id).log(
        agent="pipeline_orchestrator_agent", skill="slide_video_orchestration",
        stage=stage, language=language, event="stage_updated", status=stage_status,
        retry_count=state.get_stage(language, stage).get("retry_count", 0),
        errors=[error] if error else [],
    )
    _echo_result({"ok": True, "report": state.to_report()})


@pipeline.command("rerun-language")
@click.option("--run-id", required=True)
@click.option("--language", required=True)
@click.option("--from-stage", type=click.Choice(STAGES), help="Defaults to 'analysis' (full rerun)")
@handle_errors
def pipeline_rerun_language(run_id: str, language: str, from_stage: str | None) -> None:
    """Reset one language from a given stage onward, then resume."""
    from multilingual_slide_video_agent.logging_utils import RunLogger

    with PipelineState.transaction(run_id) as state:
        if language not in state.languages:
            _echo_result({"ok": False, "errors": [f"language '{language}' is not part of run '{run_id}'"]})
            return
        reset = state.invalidate_from(language, from_stage or "analysis")
    RunLogger(run_id, state.project_id).log(
        agent="pipeline_orchestrator_agent", skill="slide_video_orchestration",
        language=language, event="language_rerun_requested", status="completed", reset_stages=reset,
    )
    _echo_result({"ok": True, "reset_stages": reset, "next_actions": state.next_actions([language])})


@pipeline.command("rerun-stage")
@click.option("--run-id", required=True)
@click.option("--stage", required=True, type=click.Choice(STAGES))
@click.option("--language", help="Omit to apply to every language in the run")
@handle_errors
def pipeline_rerun_stage(run_id: str, stage: str, language: str | None) -> None:
    """Reset one stage, for one language or all languages, then resume."""
    from multilingual_slide_video_agent.logging_utils import RunLogger

    with PipelineState.transaction(run_id) as state:
        language_list = [language] if language else list(state.languages.keys())
        results = {}
        for lang in language_list:
            if lang not in state.languages:
                continue
            results[lang] = state.invalidate_from(lang, stage)
    RunLogger(run_id, state.project_id).log(
        agent="pipeline_orchestrator_agent", skill="slide_video_orchestration",
        stage=stage, event="stage_rerun_requested", status="completed", languages=language_list,
    )
    _echo_result({"ok": True, "reset": results, "next_actions": state.next_actions(language_list)})


@pipeline.command("approve-production")
@click.option("--run-id", required=True)
@handle_errors
def pipeline_approve_production(run_id: str) -> None:
    """Release every non-default language's `translation` stage after
    reviewing the default language's render (see state.py's
    `_production_gate_open`). Fails clearly if the default language
    hasn't finished validation yet - there's nothing to have reviewed."""
    from multilingual_slide_video_agent.logging_utils import RunLogger

    with PipelineState.transaction(run_id) as state:
        default_status = state.language_status(state.default_language)
        if default_status not in {"ready_for_review", "completed"}:
            _echo_result({
                "ok": False,
                "errors": [
                    f"default language '{state.default_language}' has status '{default_status}', not yet "
                    "ready_for_review/completed - nothing to approve yet"
                ],
            })
            return
        state.approve_production()
    RunLogger(run_id, state.project_id).log(
        agent="pipeline_orchestrator_agent", skill="slide_video_orchestration",
        event="production_approved", status="completed", language=state.default_language,
    )
    _echo_result({"ok": True, "default_language": state.default_language, "next_actions": state.next_actions()})


@pipeline.command("register-motion")
@click.option("--run-id", required=True)
@click.option("--design", "design_path", required=True, type=click.Path(exists=True), help="The deck's motion_design.json")
@handle_errors
def pipeline_register_motion(run_id: str, design_path: str) -> None:
    """Record the deck's motion design for review (plan C2). A changed file
    becomes a draft again; the approved file, unchanged, keeps its approval."""
    from multilingual_slide_video_agent.slides.motion_design import design_fingerprint

    with PipelineState.transaction(run_id) as state:
        state.register_motion(str(Path(design_path).resolve()), design_fingerprint(design_path))
    _echo_result({"ok": True, "motion": state.to_report()["motion"]})


@pipeline.command("approve-motion")
@click.option("--run-id", required=True)
@handle_errors
def pipeline_approve_motion(run_id: str) -> None:
    """Approve the registered motion design, as its file is now, for every
    language (plan C2). Run after a human has reviewed its preview."""
    from multilingual_slide_video_agent.logging_utils import RunLogger
    from multilingual_slide_video_agent.slides.motion_design import design_fingerprint

    with PipelineState.transaction(run_id) as state:
        if not state.motion:
            _echo_result({"ok": False, "errors": ["no motion design registered for this run (msv pipeline register-motion)"]})
            return
        try:
            state.approve_motion(design_fingerprint(state.motion["design"]))
        except (ValueError, OSError) as e:
            _echo_result({"ok": False, "errors": [str(e)]})
            return
    RunLogger(run_id, state.project_id).log(
        agent="pipeline_orchestrator_agent", skill="slide_video_orchestration",
        event="motion_approved", status="completed", design=state.motion["design"],
    )
    _echo_result({"ok": True, "motion": state.to_report()["motion"]})


@pipeline.command("reject-motion")
@click.option("--run-id", required=True)
@click.option("--notes", required=True, help="What to change, in plain language (e.g. 'slide 3 feels busy')")
@handle_errors
def pipeline_reject_motion(run_id: str, notes: str) -> None:
    """Send the motion design back for revision with the reviewer's notes."""
    with PipelineState.transaction(run_id) as state:
        if not state.motion:
            _echo_result({"ok": False, "errors": ["no motion design registered for this run (msv pipeline register-motion)"]})
            return
        state.reject_motion(notes)
    _echo_result({"ok": True, "motion": state.to_report()["motion"]})


@pipeline.command("approve-publish")
@click.option("--run-id", required=True)
@click.option("--languages", help="Comma-separated; defaults to every ready language")
@handle_errors
def pipeline_approve_publish(run_id: str, languages: str | None) -> None:
    """Human sign-off releasing held publishing stages (publish_pending)."""
    from multilingual_slide_video_agent.logging_utils import RunLogger

    with PipelineState.transaction(run_id) as state:
        language_list = [lang.strip() for lang in languages.split(",")] if languages else list(state.languages.keys())
        approved, blocked = [], []
        for lang in language_list:
            if lang not in state.languages:
                continue
            if state.language_status(lang) not in {"ready_for_review", "completed"}:
                blocked.append(lang)
                continue
            state.approve_publish(lang)
            approved.append(lang)
    RunLogger(run_id, state.project_id).log(
        agent="pipeline_orchestrator_agent", skill="slide_video_orchestration",
        event="publish_approved", status="completed", languages=approved,
    )
    _echo_result({"ok": True, "approved": approved, "blocked_not_ready": blocked, "next_actions": state.next_actions(approved)})


@pipeline.command("validate")
@click.option("--run-id", required=True)
@handle_errors
def pipeline_validate(run_id: str) -> None:
    """validate_pipeline: consistency checks over run state."""
    from multilingual_slide_video_agent.state import FINGERPRINT_ALGO, directory_fingerprint, fingerprints_comparable
    from pathlib import Path as _Path

    state = PipelineState.load(run_id)
    errors: list[str] = []
    warnings: list[str] = []

    source = _Path(state.source_deck)
    if not source.is_dir():
        errors.append(f"registered source deck no longer exists: {source}")
    else:
        current_fp = directory_fingerprint(source)
        if not fingerprints_comparable(state.source_deck_fingerprint_algo, FINGERPRINT_ALGO):
            warnings.append(
                "run was created with the legacy mtime-based deck fingerprint, which can't be compared "
                "with the current content fingerprint - start a new run to get source-change detection"
            )
        elif current_fp != state.source_deck_fingerprint:
            warnings.append(
                "source deck content has changed since this run started "
                f"(was {state.source_deck_fingerprint}, now {current_fp}) — "
                "consider starting a new run rather than resuming this one"
            )

    if not state.languages:
        errors.append("run has no languages configured")

    max_retries = cfg.env_int("PIPELINE_MAX_RETRIES", 3)
    for language, data in state.languages.items():
        for stage in STAGES:
            entry = data["stages"][stage]
            if entry["status"] == "in_progress":
                warnings.append(
                    f"{language}/{stage} is stuck 'in_progress' (last updated {entry['updated_at']}) — "
                    "likely an interrupted run; safe to rerun this stage"
                )
            if entry["status"] == "failed" and entry.get("retry_count", 0) >= max_retries:
                warnings.append(f"{language}/{stage} exhausted retries ({entry['retry_count']}) and needs attention")

    _echo_result({"ok": not errors, "errors": errors, "warnings": warnings, "report": state.to_report()})


@pipeline.command("report")
@click.option("--run-id", required=True)
@handle_errors
def pipeline_report(run_id: str) -> None:
    """Final execution report."""
    state = PipelineState.load(run_id)
    _echo_result({"ok": True, "report": state.to_report()})


if __name__ == "__main__":
    main()
