"""CLI surface of the motion path: `render-motion`, `motion install`, and the
legacy wrapper's error type."""
import json

import pytest
from click.testing import CliRunner

from multilingual_slide_video_agent.cli import main
from multilingual_slide_video_agent.production import render_marketing_animation as legacy
from multilingual_slide_video_agent.production.motion.errors import MotionError


def test_render_motion_command_exists_with_engine_choice():
    result = CliRunner().invoke(main, ["production", "render-motion", "--help"])
    assert result.exit_code == 0
    for option in ("--engine", "--roles", "--production", "--output-name"):
        assert option in result.output
    assert "hyperframes" in result.output and "remotion" in result.output


@pytest.mark.requires_ffmpeg
def test_render_motion_reports_unbuilt_engine_as_a_json_failure(tmp_path, monkeypatch):
    from motion_fixture_helpers import make_minimal_animation_bundle, render_source_images, write_production

    monkeypatch.setenv("MSV_LOGS_DIR", str(tmp_path / "logs"))
    production = write_production(tmp_path / "out", ["slide_001", "slide_002"])
    make_minimal_animation_bundle(tmp_path / "anim", {"slide_001": "title_reveal", "slide_002": "feature_callout"})
    render_source_images(tmp_path / "slides", {"slide_001": "navy"})
    (tmp_path / "deck").mkdir()
    result = CliRunner().invoke(main, [
        "production", "render-motion", "--engine", "hyperframes",
        "--production", str(production), "--translated-deck-dir", str(tmp_path / "deck"),
        "--animation-dir", str(tmp_path / "anim"), "--slides-dir", str(tmp_path / "slides"),
    ])
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert "Phase 2b" in payload["errors"][0]


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


def test_legacy_wrapper_raises_its_documented_error(monkeypatch):
    def failing_render_motion(**_kwargs):
        raise MotionError("capture failed on slide_001")

    monkeypatch.setattr(legacy, "render_motion", failing_render_motion)
    with pytest.raises(legacy.MarketingAnimationError, match="slide_001"):
        legacy.render_marketing_animation(
            production_path="p.json", translated_deck_dir="d", animation_dir="a", slides_dir="s",
        )
