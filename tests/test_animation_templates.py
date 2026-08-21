from multilingual_slide_video_agent.slides.animation_templates import (
    DEFAULT_TEMPLATE,
    TEMPLATE_NAMES,
    build_spec,
    choose_template,
)


def test_first_slide_is_always_title_reveal():
    assert choose_template(slide_index=1, slide_count=5, slide_description="anything") == "title_reveal"


def test_last_slide_is_always_closing():
    assert choose_template(slide_index=5, slide_count=5, slide_description="anything") == "closing"


def test_cta_language_picks_closing_even_mid_deck():
    assert choose_template(slide_index=3, slide_count=5, slide_description="Contact us to get started") == "closing"


def test_stat_language_picks_stat_highlight():
    assert choose_template(slide_index=3, slide_count=5, slide_description="A 40% reduction in latency") == "stat_highlight"


def test_diagram_language_picks_diagram_build():
    assert choose_template(slide_index=3, slide_count=5, slide_description="System architecture overview") == "diagram_build"


def test_unmatched_content_falls_back_to_default():
    assert choose_template(slide_index=3, slide_count=5, slide_description="Just a regular slide") == DEFAULT_TEMPLATE


def test_missing_description_does_not_raise():
    assert choose_template(slide_index=3, slide_count=5) in TEMPLATE_NAMES


def test_build_spec_covers_every_slide():
    slides = [
        {"slide_index": 1, "slide_id": "slide_001", "slide_description": "Intro"},
        {"slide_index": 2, "slide_id": "slide_002", "slide_description": "40% faster"},
        {"slide_index": 3, "slide_id": "slide_003", "slide_description": "Get started today"},
    ]
    spec = build_spec(slides)
    assert spec == {
        "slide_001": "title_reveal",
        "slide_002": "stat_highlight",
        "slide_003": "closing",
    }


def test_visual_role_takes_priority_over_position():
    # Even slide 1 (which would otherwise always get title_reveal) defers
    # to an explicit, valid visual_role from slide_analysis.json.
    assert choose_template(slide_index=1, slide_count=5, visual_role="diagram_build") == "diagram_build"


def test_visual_role_takes_priority_over_keyword_match():
    # "40% faster" would normally match stat_highlight via keywords, but
    # Agent 1's own judgment (visual_role) wins.
    assert choose_template(
        slide_index=3, slide_count=5, slide_description="A 40% reduction", visual_role="diagram_build",
    ) == "diagram_build"


def test_invalid_visual_role_is_ignored_by_choose_template():
    # choose_template degrades gracefully (falls through to the normal
    # heuristic) on a bad value - generate_deck_animation is where an
    # invalid visual_role fails loudly instead, see test_generate_animation.py.
    assert choose_template(slide_index=1, slide_count=5, visual_role="not_a_real_template") == "title_reveal"


def test_build_spec_honors_visual_role_per_slide():
    slides = [
        {"slide_index": 1, "slide_id": "slide_001", "slide_description": "Intro", "visual_role": None},
        {"slide_index": 2, "slide_id": "slide_002", "slide_description": "Nothing special", "visual_role": "diagram_build"},
    ]
    spec = build_spec(slides)
    assert spec == {"slide_001": "title_reveal", "slide_002": "diagram_build"}
