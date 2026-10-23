"""`msv motion compare` (plan B6 #5, Phase 7): contact sheet plus
per-slide duration deltas, which must be 0 ± 1 frame."""
import json
import subprocess

import pytest
from click.testing import CliRunner

from multilingual_slide_video_agent.cli import main
from multilingual_slide_video_agent.production.motion.compare import compare_renders

pytestmark = pytest.mark.requires_ffmpeg


def _render(tmp_path, name, color, per_slide, engine):
    video = tmp_path / f"{name}.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c={color}:s=320x180:d=4:r=30",
                    "-pix_fmt", "yuv420p", str(video)], check=True)
    (tmp_path / f"{name}.motion.json").write_text(json.dumps({
        "engine": {"name": engine}, "fps": 30, "per_slide": per_slide}), encoding="utf-8")
    return video


SLIDES = [{"slide_id": "slide_001", "start": 0.0, "end": 2.0}, {"slide_id": "slide_002", "start": 2.0, "end": 4.0}]


def test_identical_timing_passes_and_draws_one_row_per_slide(tmp_path):
    from PIL import Image

    a = _render(tmp_path, "a", "navy", SLIDES, "hyperframes")
    b = _render(tmp_path, "b", "teal", SLIDES, "remotion")
    result = compare_renders(a, b, tmp_path / "sheet.png")
    assert result["ok"] and result["labels"] == ["hyperframes", "remotion"]
    assert [s["duration_delta_frames"] for s in result["slides"]] == [0, 0]
    assert all(s["changed_pixel_fraction"] > 0.9 for s in result["slides"])    # navy vs teal
    image = Image.open(tmp_path / "sheet.png")
    assert image.height == 24 + 2 * (270 + 4)


def test_a_slide_off_by_more_than_a_frame_fails_naming_it(tmp_path):
    a = _render(tmp_path, "a", "navy", SLIDES, "hyperframes")
    shifted = [{"slide_id": "slide_001", "start": 0.0, "end": 2.1}, {"slide_id": "slide_002", "start": 2.1, "end": 4.0}]
    b = _render(tmp_path, "b", "navy", shifted, "remotion")
    result = CliRunner().invoke(main, ["motion", "compare", "--a", str(a), "--b", str(b), "--out", str(tmp_path / "s.png")])
    payload = json.loads(result.output)
    assert result.exit_code == 1 and payload["ok"] is False
    assert payload["errors"][0].startswith("slide_001: durations differ by +3 frames")


def test_renders_of_different_decks_are_refused(tmp_path):
    a = _render(tmp_path, "a", "navy", SLIDES, "hyperframes")
    b = _render(tmp_path, "b", "navy", SLIDES[:1], "remotion")
    result = CliRunner().invoke(main, ["motion", "compare", "--a", str(a), "--b", str(b), "--out", str(tmp_path / "s.png")])
    assert json.loads(result.output)["errors"][0].startswith("the renders have different slides")
