from multilingual_slide_video_agent.production.render_slideshow import compute_slide_timeline


def _segments(*slide_ids):
    return [{"slide_index": i + 1, "slide_id": sid} for i, sid in enumerate(slide_ids)]


def test_slides_play_sequentially_back_to_back():
    segments = _segments("slide_001", "slide_002", "slide_003")
    durations = [4.0, 6.0, 3.0]
    timing, total = compute_slide_timeline(
        list(zip(segments, durations)), title_duration=0.0, slide_pause_seconds=0.5
    )
    assert [t["start_time"] for t in timing] == [0.0, 4.5, 11.0]
    assert [t["end_time"] for t in timing] == [4.5, 11.0, 14.5]
    assert total == 14.5


def test_title_card_precedes_the_first_slide():
    segments = _segments("slide_001", "slide_002")
    durations = [5.0, 5.0]
    timing, total = compute_slide_timeline(
        list(zip(segments, durations)), title_duration=3.0, slide_pause_seconds=0.5
    )
    assert timing[0] == {"kind": "title", "start_time": 0.0, "end_time": 3.0}
    assert timing[1]["start_time"] == 3.0
    assert timing[1]["end_time"] == 8.5
    assert timing[2]["start_time"] == 8.5
    assert total == 14.0


def test_a_longer_slide_only_pushes_slides_after_it():
    segments = _segments("slide_001", "slide_002", "slide_003")
    durations = [2.0, 20.0, 2.0]
    timing, _total = compute_slide_timeline(
        list(zip(segments, durations)), title_duration=0.0, slide_pause_seconds=0.0
    )
    assert timing[0]["end_time"] == 2.0
    assert timing[1]["start_time"] == 2.0
    assert timing[1]["end_time"] == 22.0
    assert timing[2]["start_time"] == 22.0
