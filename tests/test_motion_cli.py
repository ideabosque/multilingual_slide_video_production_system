"""CLI surface of the motion path: `render-motion` and `motion install`."""
import json

import pytest
from click.testing import CliRunner

from multilingual_slide_video_agent.cli import main
from multilingual_slide_video_agent.production.motion.errors import MotionError


def test_render_motion_command_exists_with_engine_choice():
    result = CliRunner().invoke(main, ["production", "render-motion", "--help"])
    assert result.exit_code == 0
    for option in ("--engine", "--roles", "--production", "--output-name"):
        assert option in result.output
    assert "hyperframes" in result.output and "remotion" in result.output


@pytest.mark.requires_ffmpeg
def test_render_motion_reports_a_failed_render_as_a_json_failure_naming_the_file(tmp_path, monkeypatch):
    """A bundle without design_tokens.css: the JSON failure names the file
    (Windows' own message doesn't)."""
    from multilingual_slide_video_agent.production.motion import render as motion_render
    from motion_fixture_helpers import make_minimal_animation_bundle, write_deck, write_production

    monkeypatch.setenv("MSV_LOGS_DIR", str(tmp_path / "logs"))
    production = write_production(tmp_path / "out", ["slide_001", "slide_002"])
    make_minimal_animation_bundle(tmp_path / "anim", {"slide_001": "title_reveal", "slide_002": "feature_callout"})
    write_deck(tmp_path / "deck", {"slide_001": "<h1>One</h1>", "slide_002": "<h1>Two</h1>"})
    for engine in motion_render.KNOWN_ENGINE_NAMES:
        monkeypatch.setattr(type(motion_render.get_engine(engine)), "check_available", lambda self: [])
        result = CliRunner().invoke(main, [
            "production", "render-motion", "--engine", engine,
            "--production", str(production), "--translated-deck-dir", str(tmp_path / "deck"),
            "--animation-dir", str(tmp_path / "anim"),
        ])
        payload = json.loads(result.output)
        assert payload["ok"] is False
        assert "design_tokens.css" in payload["errors"][0], (engine, payload["errors"])


@pytest.mark.requires_ffmpeg
def test_render_motion_rejects_an_invalid_motion_design_before_rendering(tmp_path, monkeypatch):
    from motion_fixture_helpers import make_minimal_animation_bundle, write_production

    monkeypatch.setenv("MSV_LOGS_DIR", str(tmp_path / "logs"))
    production = write_production(tmp_path / "out", ["slide_001", "slide_002"])
    make_minimal_animation_bundle(tmp_path / "anim", {"slide_001": "title_reveal", "slide_002": "feature_callout"})
    (tmp_path / "deck").mkdir()
    design = tmp_path / "motion_design.json"
    design.write_text(json.dumps({"schema": "motion-design/v1", "deck_fingerprint": "x", "slides": [
        {"slide_id": "slide_002", "steps": [{"target": {"role": "title"}, "effect": "wobble"}]},
    ]}), encoding="utf-8")
    result = CliRunner().invoke(main, [
        "production", "render-motion", "--engine", "hyperframes", "--motion-design", str(design),
        "--production", str(production), "--translated-deck-dir", str(tmp_path / "deck"),
        "--animation-dir", str(tmp_path / "anim"),
    ])
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert "slide_002.steps[0]" in payload["errors"][0] and "wobble" in payload["errors"][0]


def test_motion_install_explains_a_missing_lockfile(tmp_path, monkeypatch):
    (tmp_path / "motion").mkdir()
    (tmp_path / "motion" / "package.json").write_text('{"name": "motion", "dependencies": {}}', encoding="utf-8")
    monkeypatch.setenv("MSV_ROOT_DIR", str(tmp_path))
    result = CliRunner().invoke(main, ["motion", "install"])
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert "package-lock.json is missing" in payload["errors"][0]


def test_committed_motion_lockfile_exists():
    from pathlib import Path

    motion_dir = Path(__file__).resolve().parents[1] / "motion"
    assert (motion_dir / "package-lock.json").exists()
