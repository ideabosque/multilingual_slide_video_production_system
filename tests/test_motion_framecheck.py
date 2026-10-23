"""The B6 frame-analysis primitives (unit level - no ffmpeg): a near-uniform
white/black boundary frame fails, brand-tinted and content frames don't."""
from pathlib import Path

import numpy
from PIL import Image


from multilingual_slide_video_agent.production.motion.validate import (
    is_blank_frame,
    frame_delta,
    frame_stats,
)

THRESHOLDS = {
    "blank_max_stddev": 6.0,
    "blank_white_min_mean": 244.0,
    "blank_black_max_mean": 12.0,
    "animation_min_mean_delta": 1.5,
}


def _png(tmp_path, name, arr):
    img = Image.fromarray(arr.astype("uint8"))
    path = tmp_path / f"{name}.png"
    img.save(path)
    return path


def test_white_black_frames_are_blank(tmp_path):
    white = _png(tmp_path, "white", numpy.full((60, 80), 255.0))
    black = _png(tmp_path, "black", numpy.full((60, 80), 0.0))
    assert is_blank_frame(frame_stats(white), THRESHOLDS) is True
    assert is_blank_frame(frame_stats(black), THRESHOLDS) is True


def test_brand_tinted_and_content_frames_are_not_blank(tmp_path):
    # the brand's warm off-white page background (design_system.yaml) sits far
    # below the white threshold even though it's near-uniform
    tinted = _png(tmp_path, "tinted", numpy.full((60, 80), 236.0))
    assert is_blank_frame(frame_stats(tinted), THRESHOLDS) is False
    # a dark slide's rendered text makes the stddev far too high to be blank
    content = numpy.full((60, 80), 40.0)
    content[20:40, 10:70] = 220.0
    texty = _png(tmp_path, "texty", content)
    assert is_blank_frame(frame_stats(texty), THRESHOLDS) is False


def test_frame_delta_detects_change(tmp_path):
    a = _png(tmp_path, "a", numpy.full((60, 80), 10.0))
    b = _png(tmp_path, "b", numpy.full((60, 80), 200.0))
    same = _png(tmp_path, "c", numpy.full((60, 80), 10.0))
    assert frame_delta(a, a) == 0
    assert frame_delta(a, b) > 100
    assert frame_delta(a, same) == 0


def test_delta_size_mismatch_fails_named(tmp_path):
    a = _png(tmp_path, "a", numpy.full((60, 80), 10.0))
    b = _png(tmp_path, "b", numpy.full((30, 80), 10.0))
    from multilingual_slide_video_agent.production.motion.errors import MotionError
    try:
        frame_delta(a, b)
    except MotionError as e:
        assert "differ" in str(e)
    else:
        raise AssertionError("expected MotionError")

def test_white_frame_with_a_little_small_text_is_not_blank(tmp_path):
    """A white slide with small text has a low stddev (here ~5.3, under the
    old 6.0 rule); counting content pixels tells it apart from empty."""
    arr = numpy.full((300, 400), 255.0)
    arr[100:103, 50:74] = 40.0                     # 72 dark "text" pixels, 0.06%
    small_text = _png(tmp_path, "small_text", arr)
    stats = frame_stats(small_text)
    assert stats["stddev"] < THRESHOLDS["blank_max_stddev"]
    assert stats["content_fraction"] > 0.0002
    assert is_blank_frame(stats, THRESHOLDS) is False
