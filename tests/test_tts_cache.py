import json

import pytest

from multilingual_slide_video_agent.production import render_slideshow

PROFILE = {"voice": "marin", "tts_instructions": "Speak warmly."}


@pytest.fixture
def tts_calls(monkeypatch):
    calls = []

    def fake_tts(text, output, voice, model, instructions):
        calls.append(text)
        output.write_bytes(f"audio:{text}".encode("utf-8"))

    monkeypatch.setattr(render_slideshow, "_generate_segment_tts", fake_tts)
    return calls


def _ensure(seg_audio, text, *, trust_unkeyed=False, extra=""):
    return render_slideshow._ensure_segment_tts(
        text, seg_audio, PROFILE, "gpt-4o-mini-tts", extra, trust_unkeyed=trust_unkeyed,
    )


def test_first_render_generates_audio_and_sidecar(tmp_path, tts_calls):
    seg_audio = tmp_path / "slide_001.mp3"
    key, regenerated = _ensure(seg_audio, "Hello")
    assert regenerated and tts_calls == ["Hello"]
    assert seg_audio.read_bytes() == b"audio:Hello"
    assert json.loads(seg_audio.with_suffix(".json").read_text(encoding="utf-8"))["key"] == key
    assert not (tmp_path / "slide_001.partial.mp3").exists()


def test_unchanged_narration_reuses_cached_audio(tmp_path, tts_calls):
    seg_audio = tmp_path / "slide_001.mp3"
    _ensure(seg_audio, "Hello")
    _key, regenerated = _ensure(seg_audio, "Hello")
    assert not regenerated and tts_calls == ["Hello"]


def test_edited_narration_regenerates_audio(tmp_path, tts_calls):
    seg_audio = tmp_path / "slide_001.mp3"
    _ensure(seg_audio, "Hello")
    _key, regenerated = _ensure(seg_audio, "Hello, edited")
    assert regenerated and tts_calls == ["Hello", "Hello, edited"]
    assert seg_audio.read_bytes() == b"audio:Hello, edited"


def test_changed_pronunciation_hints_regenerate_audio(tmp_path, tts_calls):
    seg_audio = tmp_path / "slide_001.mp3"
    _ensure(seg_audio, "Hello")
    _key, regenerated = _ensure(seg_audio, "Hello", extra='Pronounce "A2A" as "A to A".')
    assert regenerated


def test_legacy_clip_without_sidecar_is_regenerated_in_default_dir(tmp_path, tts_calls):
    seg_audio = tmp_path / "slide_001.mp3"
    seg_audio.write_bytes(b"old audio")
    _key, regenerated = _ensure(seg_audio, "Hello")
    assert regenerated and seg_audio.read_bytes() == b"audio:Hello"


def test_clip_without_sidecar_is_trusted_in_explicit_audio_dir(tmp_path, tts_calls):
    seg_audio = tmp_path / "slide_001.mp3"
    seg_audio.write_bytes(b"supplied audio")
    _key, regenerated = _ensure(seg_audio, "Hello", trust_unkeyed=True)
    assert not regenerated and tts_calls == []
    assert seg_audio.read_bytes() == b"supplied audio"


def test_mismatched_sidecar_regenerates_even_in_explicit_audio_dir(tmp_path, tts_calls):
    seg_audio = tmp_path / "slide_001.mp3"
    _ensure(seg_audio, "Hello")
    _key, regenerated = _ensure(seg_audio, "Different", trust_unkeyed=True)
    assert regenerated
