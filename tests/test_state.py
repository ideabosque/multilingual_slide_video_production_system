import pytest

from multilingual_slide_video_agent.state import PipelineState, STAGES


@pytest.fixture
def isolated_state_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("MSV_STATE_DIR", str(tmp_path / "state"))
    return tmp_path


@pytest.fixture
def source_deck(tmp_path):
    deck = tmp_path / "deck"
    deck.mkdir()
    (deck / "slide_001.html").write_text("<html><body><h1>Hi</h1></body></html>", encoding="utf-8")
    return deck


def test_create_and_load_round_trips(isolated_state_dir, source_deck):
    state = PipelineState.create(
        run_id="run-test-001", project_id="proj", source_deck=str(source_deck),
        language_codes=["en-US", "zh-TW"],
    )
    loaded = PipelineState.load("run-test-001")
    assert loaded.project_id == "proj"
    assert set(loaded.languages) == {"en-US", "zh-TW"}
    assert loaded.overall_status() == "in_progress" or loaded.overall_status() == "pending"


def test_next_actions_respects_stage_order(isolated_state_dir, source_deck):
    state = PipelineState.create(
        run_id="run-test-002", project_id="proj", source_deck=str(source_deck),
        language_codes=["en-US"],
    )
    actions = state.next_actions()
    assert actions == [{"language": "en-US", "stage": "analysis"}]

    state.set_stage("en-US", "analysis", "completed")
    actions = state.next_actions()
    assert actions == [{"language": "en-US", "stage": "translation"}]


def test_publishing_held_until_auto_publish_or_approval(isolated_state_dir, source_deck):
    state = PipelineState.create(
        run_id="run-test-003", project_id="proj", source_deck=str(source_deck),
        language_codes=["en-US"], auto_publish=False,
    )
    for stage in ["analysis", "translation", "rendering", "tts", "validation"]:
        state.set_stage("en-US", stage, "completed")

    assert state.next_actions() == []
    assert state.language_status("en-US") == "ready_for_review"

    state.approve_publish("en-US")
    assert state.next_actions() == [{"language": "en-US", "stage": "publishing"}]


def test_invalidate_from_resets_only_downstream_stages(isolated_state_dir, source_deck):
    state = PipelineState.create(
        run_id="run-test-004", project_id="proj", source_deck=str(source_deck),
        language_codes=["en-US"],
    )
    for stage in STAGES:
        state.set_stage("en-US", stage, "completed")
    assert state.language_status("en-US") == "completed"

    reset = state.invalidate_from("en-US", "translation")
    assert reset == ["translation", "rendering", "tts", "validation", "publishing"]
    assert state.get_stage("en-US", "analysis")["status"] == "completed"
    assert state.get_stage("en-US", "translation")["status"] == "pending"


def test_failure_in_one_language_does_not_block_another(isolated_state_dir, source_deck):
    state = PipelineState.create(
        run_id="run-test-005", project_id="proj", source_deck=str(source_deck),
        language_codes=["en-US", "ja-JP"],
    )
    state.set_stage("ja-JP", "analysis", "failed", error="boom")
    actions = state.next_actions()
    assert {"language": "en-US", "stage": "analysis"} in actions
    assert state.language_status("ja-JP") == "failed"


def test_non_default_languages_held_until_production_approved(isolated_state_dir, source_deck):
    state = PipelineState.create(
        run_id="run-test-006", project_id="proj", source_deck=str(source_deck),
        language_codes=["en-US", "zh-TW", "ja-JP"], default_language="en-US",
    )
    for lang in state.languages:
        state.set_stage(lang, "analysis", "completed")

    # Only the default language's translation stage is offered until it's produced.
    actions = state.next_actions()
    assert actions == [{"language": "en-US", "stage": "translation"}]
    assert state.language_status("zh-TW") == "blocked_pending_production_approval"

    for stage in ["translation", "rendering", "tts", "validation"]:
        state.set_stage("en-US", stage, "completed")

    # Default language done, but the gate isn't open yet without approval.
    actions = state.next_actions()
    assert all(a["language"] == "en-US" for a in actions)
    assert state.overall_status() == "awaiting_production_approval"

    state.approve_production()
    actions = state.next_actions()
    assert {"language": "zh-TW", "stage": "translation"} in actions
    assert {"language": "ja-JP", "stage": "translation"} in actions


def test_auto_approve_production_skips_the_gate(isolated_state_dir, source_deck):
    state = PipelineState.create(
        run_id="run-test-007", project_id="proj", source_deck=str(source_deck),
        language_codes=["en-US", "zh-TW"], default_language="en-US",
        auto_approve_production=True,
    )
    for lang in state.languages:
        state.set_stage(lang, "analysis", "completed")
    for stage in ["translation", "rendering", "tts", "validation"]:
        state.set_stage("en-US", stage, "completed")

    assert {"language": "zh-TW", "stage": "translation"} in state.next_actions()


def test_rerunning_default_language_relocks_production_gate(isolated_state_dir, source_deck):
    state = PipelineState.create(
        run_id="run-test-008", project_id="proj", source_deck=str(source_deck),
        language_codes=["en-US", "zh-TW"], default_language="en-US",
    )
    for lang in state.languages:
        state.set_stage(lang, "analysis", "completed")
    for stage in ["translation", "rendering", "tts", "validation"]:
        state.set_stage("en-US", stage, "completed")
    state.approve_production()
    assert state.production_approved is True

    state.invalidate_from("en-US", "translation")
    assert state.production_approved is False
    assert {"language": "zh-TW", "stage": "translation"} not in state.next_actions()
