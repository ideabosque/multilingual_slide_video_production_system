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


# ---------------------------------------------------------------------------
# msv production ... (Agent 2)
# ---------------------------------------------------------------------------

@main.group()
def production() -> None:
    """Agent 2: voice & slideshow production tools."""


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


@production.command("render-marketing-animation")
@click.option("--production", "production_path", required=True, type=click.Path(exists=True), help="An already-rendered language's production.json (msv production render-slideshow output)")
@click.option("--translated-deck-dir", required=True, type=click.Path(exists=True, file_okay=False), help="This language's translated HTML deck (msv slides apply-translations output)")
@click.option("--animation-dir", required=True, type=click.Path(exists=True, file_okay=False), help="The deck's generated animation bundle (msv slides generate-animation output)")
@click.option("--slides-dir", required=True, type=click.Path(exists=True, file_okay=False), help="This language's rendered slide images, for the title card background (msv slides render-images output)")
@click.option("--localization", type=click.Path(exists=True), help="Agent 1's localization_<language>.json, for caption text")
@click.option("--output-dir", type=click.Path(), help="Defaults to the production.json directory")
@click.option("--output-name", default="marketing_animation.mp4", show_default=True)
@click.option("--viewport", default="1920x1080", show_default=True)
def production_render_marketing_animation(
    production_path: str, translated_deck_dir: str, animation_dir: str, slides_dir: str,
    localization: str | None, output_dir: str | None, output_name: str, viewport: str,
) -> None:
    """Rebuild an already-rendered language as a GSAP-animated marketing MP4 (marketing_animation_pipeline_plan §4)."""
    from multilingual_slide_video_agent.production.render_marketing_animation import (
        MarketingAnimationError,
        render_marketing_animation,
    )

    try:
        envelope = render_marketing_animation(
            production_path=production_path, translated_deck_dir=translated_deck_dir,
            animation_dir=animation_dir, slides_dir=slides_dir, localization_path=localization,
            output_dir=output_dir, output_name=output_name, viewport=viewport,
        )
    except MarketingAnimationError as e:
        _echo_result({"agent": "slideshow_production_agent", "status": "failed", "ok": False, "errors": [str(e)]})
        return
    envelope["ok"] = envelope.get("status") == "completed"
    _echo_result(envelope)


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
def pipeline_init(
    project_id: str, source_deck: str, languages: str | None, run_id: str | None, auto_publish: bool | None,
    default_language: str | None, auto_approve_production: bool | None,
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

    state = PipelineState.load(run_id)
    artifacts = {}
    for pair in artifact:
        key, _, value = pair.partition("=")
        artifacts[key] = value
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

    state = PipelineState.load(run_id)
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

    state = PipelineState.load(run_id)
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

    state = PipelineState.load(run_id)
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


@pipeline.command("approve-publish")
@click.option("--run-id", required=True)
@click.option("--languages", help="Comma-separated; defaults to every ready language")
@handle_errors
def pipeline_approve_publish(run_id: str, languages: str | None) -> None:
    """Human sign-off releasing held publishing stages (publish_pending)."""
    from multilingual_slide_video_agent.logging_utils import RunLogger

    state = PipelineState.load(run_id)
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
    from multilingual_slide_video_agent.state import directory_fingerprint
    from pathlib import Path as _Path

    state = PipelineState.load(run_id)
    errors: list[str] = []
    warnings: list[str] = []

    source = _Path(state.source_deck)
    if not source.is_dir():
        errors.append(f"registered source deck no longer exists: {source}")
    else:
        current_fp = directory_fingerprint(source)
        if current_fp != state.source_deck_fingerprint:
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
