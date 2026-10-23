"""Phase 6 (plan C2, C6): the motion approval gate - its state, its CLI,
render-motion enforcing it - plus the review tools (filmstrip, preview,
schema)."""
import json
import subprocess

import pytest
from click.testing import CliRunner

from multilingual_slide_video_agent.cli import main
from multilingual_slide_video_agent.state import PipelineState

from motion_fixture_helpers import make_minimal_animation_bundle, write_deck, write_production

RUN = "run-motion-test"   # write_production's run id


@pytest.fixture
def run(tmp_path, monkeypatch):
    monkeypatch.setenv("MSV_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("MSV_LOGS_DIR", str(tmp_path / "logs"))
    deck = tmp_path / "source_deck"
    write_deck(deck, {"slide_001": "<h1>One</h1>", "slide_002": "<h1>Two</h1>"})
    state = PipelineState.create(run_id=RUN, project_id="proj-motion-test", source_deck=str(deck),
                                 language_codes=["en-US", "zh-TW"], default_language="en-US")
    design = tmp_path / "motion_design.json"
    design.write_text(json.dumps({"schema": "motion-design/v1", "deck_fingerprint": "x", "slides": [
        {"slide_id": "slide_002", "steps": [{"target": {"role": "title"}, "effect": "reveal"}]}]}), encoding="utf-8")
    return state, design


def _cli(*args):
    result = CliRunner().invoke(main, list(args))
    return result.exit_code, json.loads(result.output)


def test_gate_lifecycle_register_approve_edit_reject(run):
    state, design = run
    from multilingual_slide_video_agent.slides.motion_design import design_fingerprint

    fp = design_fingerprint(design)
    # nothing registered: the default language may render, others may not
    assert state.motion_gate("en-US", fp) is None
    assert "no registered motion design" in state.motion_gate("zh-TW", fp)

    code, out = _cli("pipeline", "register-motion", "--run-id", RUN, "--design", str(design))
    assert code == 0 and out["motion"]["status"] == "draft" and out["motion"]["fingerprint"] == fp
    assert "draft, not approved" in PipelineState.load(RUN).motion_gate("zh-TW", fp)

    code, out = _cli("pipeline", "approve-motion", "--run-id", RUN)
    assert code == 0 and out["motion"]["status"] == "approved"
    assert PipelineState.load(RUN).motion_gate("zh-TW", fp) is None
    # re-registering the same file keeps the approval
    _cli("pipeline", "register-motion", "--run-id", RUN, "--design", str(design))
    assert PipelineState.load(RUN).motion["status"] == "approved"

    # editing the approved file reopens the gate, even before re-registering
    design.write_text(design.read_text(encoding="utf-8").replace("reveal", "pop"), encoding="utf-8")
    new_fp = design_fingerprint(design)
    assert "changed after it was approved" in PipelineState.load(RUN).motion_gate("zh-TW", new_fp)
    # ...and can't be approved without registering (and so previewing) it again
    code, out = _cli("pipeline", "approve-motion", "--run-id", RUN)
    assert code == 1 and "changed since it was registered" in out["errors"][0]
    _cli("pipeline", "register-motion", "--run-id", RUN, "--design", str(design))
    assert PipelineState.load(RUN).motion["status"] == "draft"

    code, out = _cli("pipeline", "reject-motion", "--run-id", RUN, "--notes", "slide 2 feels busy")
    assert code == 0 and out["motion"]["status"] == "rejected" and out["motion"]["notes"] == "slide 2 feels busy"
    report = _cli("pipeline", "status", "--run-id", RUN)[1]
    assert report["report"]["motion"]["status"] == "rejected"


def test_approve_motion_needs_a_registered_design(run):
    code, out = _cli("pipeline", "approve-motion", "--run-id", RUN)
    assert code == 1 and "no motion design registered" in out["errors"][0]


def test_auto_approve_motion_opens_the_gate(tmp_path, monkeypatch):
    monkeypatch.setenv("MSV_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("MSV_LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("PIPELINE_AUTO_APPROVE_MOTION", "true")
    deck = tmp_path / "deck"
    write_deck(deck, {"slide_001": "<h1>One</h1>"})
    code, out = _cli("pipeline", "init", "--project-id", "p", "--source-deck", str(deck), "--languages", "en-US,zh-TW",
                     "--default-language", "en-US", "--run-id", "run-auto")
    assert code == 0 and out["report"]["motion"] == {"status": "none", "auto_approve": True}
    assert PipelineState.load("run-auto").motion_gate("zh-TW", "anything") is None


def _render(tmp_path, language, design):
    production = write_production(tmp_path / f"out-{language}", ["slide_001", "slide_002"], language=language)
    make_minimal_animation_bundle(tmp_path / "anim", {"slide_001": "title_reveal", "slide_002": "feature_callout"})
    write_deck(tmp_path / "deck", {"slide_001": "<h1>One</h1>", "slide_002": "<h1>Two</h1>"})
    return _cli("production", "render-motion", "--engine", "hyperframes", "--motion-design", str(design),
                "--production", str(production), "--translated-deck-dir", str(tmp_path / "deck"),
                "--animation-dir", str(tmp_path / "anim"))


@pytest.mark.requires_ffmpeg
def test_render_motion_holds_non_default_languages_until_approved(run, tmp_path):
    _state, design = run
    _cli("pipeline", "register-motion", "--run-id", RUN, "--design", str(design))
    code, out = _render(tmp_path, "zh-TW", design)
    assert code == 1 and "zh-TW can't render this motion design yet" in out["errors"][0]
    # the default language isn't held: it fails later, on the minimal
    # fixture bundle, not at the gate
    code, out = _render(tmp_path, "en-US", design)
    assert "can't render this motion design yet" not in out["errors"][0]
    # once approved, zh-TW passes the gate too
    _cli("pipeline", "approve-motion", "--run-id", RUN)
    code, out = _render(tmp_path, "zh-TW", design)
    assert "can't render this motion design yet" not in out["errors"][0]


def test_motion_schema_command_prints_the_generated_schema():
    code, out = _cli("motion", "schema")
    assert code == 0 and out["schema"]["$id"] == "motion-design/v1"


@pytest.mark.requires_ffmpeg
def test_filmstrip_has_one_row_per_slide_and_five_frames(tmp_path):
    from PIL import Image

    from multilingual_slide_video_agent.production.motion.filmstrip import make_filmstrip

    video = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=s=320x180:d=4:r=10",
                    "-pix_fmt", "yuv420p", str(video)], check=True)
    per_slide = [{"slide_id": "slide_001", "start": 0, "end": 2}, {"slide_id": "slide_002", "start": 2, "end": 4}]
    out = make_filmstrip(video, per_slide, tmp_path / "strip.png", thumb_width=160)
    image = Image.open(out)
    thumb_h = 90
    assert image.width == 120 + 5 * (160 + 4)
    assert image.height == 2 * (thumb_h + 18 + 4)
    only_two = make_filmstrip(video, per_slide, tmp_path / "one.png", thumb_width=160, slide_ids=["slide_002"])
    assert Image.open(only_two).height == thumb_h + 18 + 4


@pytest.mark.requires_node
@pytest.mark.requires_ffmpeg
def test_preview_renders_small_with_a_filmstrip_and_ignores_the_gate(run, tmp_path, monkeypatch):
    """A preview of a non-default language with an unapproved design: the
    per-language check before approval needs exactly that."""
    from multilingual_slide_video_agent.production.motion import remotion_engine as rm

    if rm.check_available():
        pytest.skip("; ".join(rm.check_available()))
    from test_hyperframes_engine import _ctx

    _state, design = run
    _cli("pipeline", "register-motion", "--run-id", RUN, "--design", str(design))
    ctx = _ctx(tmp_path / "fx", slide_seconds=(1.5, 1.5))
    production = json.loads(ctx.production_path.read_text(encoding="utf-8"))
    production["language"] = "zh-TW"
    ctx.production_path.write_text(json.dumps(production), encoding="utf-8")
    code, out = _cli("motion", "preview", "--production", str(ctx.production_path),
                     "--translated-deck-dir", str(ctx.translated_deck_dir), "--animation-dir", str(ctx.animation_dir),
                     "--motion-design", str(design), "--engine", "remotion", "--viewport", "1280x720",
                     "--res", "320x180", "--fps", "10")
    assert code == 0, out
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=width,height,r_frame_rate", "-of", "json", out["video"]],
                           capture_output=True, text=True, check=True)
    stream = json.loads(probe.stdout)["streams"][0]
    assert (stream["width"], stream["height"], stream["r_frame_rate"]) == (320, 180, "10/1")
    assert out["filmstrip"].endswith("preview_filmstrip.png") and out["fallback"] == {}
    # production.json is untouched by a preview
    assert "output_video" not in json.loads(ctx.production_path.read_text(encoding="utf-8"))
