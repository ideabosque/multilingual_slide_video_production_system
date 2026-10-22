import json
import os
import subprocess
import sys
import time

import pytest

from multilingual_slide_video_agent.production.validate import validate_production
from multilingual_slide_video_agent.state import (
    FINGERPRINT_ALGO,
    PipelineState,
    directory_fingerprint,
)

LANGUAGES = ["en-US", "zh-TW", "ja-JP", "ko-KR", "es-ES", "de-DE", "fr-FR", "zh-CN"]


@pytest.fixture
def isolated_dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("MSV_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("MSV_LOGS_DIR", str(tmp_path / "logs"))
    return tmp_path


@pytest.fixture
def source_deck(tmp_path):
    deck = tmp_path / "deck"
    deck.mkdir()
    (deck / "slide_001.html").write_text("<html><body><h1>Hi</h1></body></html>", encoding="utf-8")
    (deck / "styles.css").write_text("body { margin: 0; }", encoding="utf-8")
    return deck


# ---------- A3: concurrent stage updates ----------

def test_parallel_set_stage_keeps_every_languages_update(isolated_dirs, source_deck):
    """8 processes record 8 different languages' stage at once - the way
    language rollout runs - and none of the updates may be lost."""
    PipelineState.create(
        run_id="run-par", project_id="proj", source_deck=str(source_deck), language_codes=LANGUAGES,
    )
    env = dict(os.environ)
    procs = [
        subprocess.Popen(
            [sys.executable, "-m", "multilingual_slide_video_agent.cli", "pipeline", "set-stage",
             "--run-id", "run-par", "--language", lang, "--stage", "analysis", "--status", "completed"],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        for lang in LANGUAGES
    ]
    for p in procs:
        out, err = p.communicate(timeout=120)
        assert p.returncode == 0, err.decode()

    state = PipelineState.load("run-par")
    statuses = {lang: state.get_stage(lang, "analysis")["status"] for lang in LANGUAGES}
    assert statuses == {lang: "completed" for lang in LANGUAGES}


_HAMMER = """
import sys
from multilingual_slide_video_agent.state import PipelineState
for i in range(15):
    with PipelineState.transaction("run-hammer") as s:
        s.set_stage(sys.argv[1], "analysis", "in_progress", artifacts={f"k{i}": "v"})
"""


def test_sustained_parallel_updates_lose_nothing(isolated_dirs, source_deck):
    """Many back-to-back updates per language from 8 processes. The old
    unlocked load()/save() pattern kept 35 of 200 updates in this setup
    (and crashed with PermissionError on Windows); every one must survive."""
    PipelineState.create(
        run_id="run-hammer", project_id="proj", source_deck=str(source_deck), language_codes=LANGUAGES,
    )
    procs = [
        subprocess.Popen([sys.executable, "-c", _HAMMER, lang], env=dict(os.environ),
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        for lang in LANGUAGES
    ]
    for p in procs:
        _out, err = p.communicate(timeout=180)
        assert p.returncode == 0, err.decode()

    state = PipelineState.load("run-hammer")
    kept = {lang: len(state.get_stage(lang, "analysis")["artifacts"]) for lang in LANGUAGES}
    assert kept == {lang: 15 for lang in LANGUAGES}


def test_transaction_saves_mutations(isolated_dirs, source_deck):
    PipelineState.create(run_id="run-tx", project_id="proj", source_deck=str(source_deck), language_codes=["en-US"])
    with PipelineState.transaction("run-tx") as state:
        state.languages["en-US"]["stages"]["analysis"]["status"] = "completed"
    assert PipelineState.load("run-tx").get_stage("en-US", "analysis")["status"] == "completed"


# ---------- A4: content fingerprint ----------

def test_fingerprint_ignores_mtime_changes(source_deck):
    before = directory_fingerprint(source_deck)
    future = time.time() + 3600
    for f in source_deck.iterdir():
        os.utime(f, (future, future))
    assert directory_fingerprint(source_deck) == before


def test_fingerprint_changes_when_content_changes(source_deck):
    before = directory_fingerprint(source_deck)
    (source_deck / "styles.css").write_text("body { margin: 1px; }", encoding="utf-8")
    assert directory_fingerprint(source_deck) != before


def test_fingerprint_changes_when_a_file_is_renamed(source_deck):
    before = directory_fingerprint(source_deck)
    (source_deck / "styles.css").rename(source_deck / "theme.css")
    assert directory_fingerprint(source_deck) != before


def test_new_state_records_fingerprint_algo(isolated_dirs, source_deck):
    PipelineState.create(run_id="run-fp", project_id="proj", source_deck=str(source_deck), language_codes=["en-US"])
    assert PipelineState.load("run-fp").source_deck_fingerprint_algo == FINGERPRINT_ALGO


def _write_production(tmp_path, *, fingerprint, algo):
    artifact = tmp_path / "artifact.txt"
    artifact.write_text("x", encoding="utf-8")
    production = {
        "narration_audio": str(artifact), "captions": str(artifact), "output_video": str(tmp_path / "missing.mp4"),
        "slides": ["slide_001"], "duration_check_ok": True,
        "source_deck_fingerprint": fingerprint,
    }
    if algo:
        production["source_deck_fingerprint_algo"] = algo
    path = tmp_path / "production.json"
    path.write_text(json.dumps(production), encoding="utf-8")
    return path


def test_legacy_fingerprint_mismatch_is_a_warning_not_an_error(isolated_dirs, source_deck, tmp_path):
    PipelineState.create(run_id="run-legacy", project_id="proj", source_deck=str(source_deck), language_codes=["en-US"])
    path = _write_production(tmp_path, fingerprint="0123456789abcdef", algo=None)
    result = validate_production(production_path=str(path), run_id="run-legacy")
    assert not any("fingerprint mismatch" in e for e in result["errors"])
    assert any("fingerprint not checked" in w for w in result["warnings"])


def test_current_fingerprint_mismatch_is_still_an_error(isolated_dirs, source_deck, tmp_path):
    PipelineState.create(run_id="run-cur", project_id="proj", source_deck=str(source_deck), language_codes=["en-US"])
    path = _write_production(tmp_path, fingerprint="0123456789abcdef", algo=FINGERPRINT_ALGO)
    result = validate_production(production_path=str(path), run_id="run-cur")
    assert any("fingerprint mismatch" in e for e in result["errors"])


def test_production_with_no_slides_is_an_error(tmp_path):
    path = _write_production(tmp_path, fingerprint="x", algo=FINGERPRINT_ALGO)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["slides"] = []
    path.write_text(json.dumps(data), encoding="utf-8")
    result = validate_production(production_path=str(path))
    assert any("no rendered slides" in e for e in result["errors"])


# ---------- A6: YouTube id on rerun ----------

def _published_state(source_deck):
    state = PipelineState.create(
        run_id="run-yt", project_id="proj", source_deck=str(source_deck), language_codes=["en-US"],
    )
    state.set_youtube_result("en-US", "vid123", "https://www.youtube.com/watch?v=vid123")
    return state


def test_rerun_of_publishing_keeps_video_id_for_metadata_update(isolated_dirs, source_deck):
    state = _published_state(source_deck)
    state.invalidate_from("en-US", "publishing")
    assert state.languages["en-US"]["youtube_video_id"] == "vid123"
    assert state.languages["en-US"].get("previous_youtube_videos", []) == []


def test_rerun_of_earlier_stage_archives_video_id(isolated_dirs, source_deck):
    state = _published_state(source_deck)
    state.invalidate_from("en-US", "tts")
    lang = state.languages["en-US"]
    assert lang["youtube_video_id"] is None
    assert [v["youtube_video_id"] for v in lang["previous_youtube_videos"]] == ["vid123"]
    assert lang["previous_youtube_videos"][0]["reason"] == "rerun from 'tts'"
    report = state.to_report()["languages"]["en-US"]
    assert report["previous_youtube_videos"][0]["youtube_video_id"] == "vid123"
