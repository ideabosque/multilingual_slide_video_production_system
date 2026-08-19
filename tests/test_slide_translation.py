import json

import pytest

from multilingual_slide_video_agent.slides.apply_translations import ApplyTranslationsError, apply_translations
from multilingual_slide_video_agent.slides.extract_text import extract_deck_text


@pytest.fixture
def deck_dir(tmp_path):
    deck = tmp_path / "deck"
    deck.mkdir()
    (deck / "slide_001.html").write_text(
        "<html><body><h1>Welcome</h1><p>This is the intro slide.</p></body></html>",
        encoding="utf-8",
    )
    (deck / "slide_002.html").write_text(
        "<html><body><h1>Features</h1><p>Fast, simple, reliable.</p></body></html>",
        encoding="utf-8",
    )
    (deck / "styles.css").write_text("body { margin: 0; }", encoding="utf-8")
    return deck


def test_extract_deck_text_assigns_stable_ordered_node_ids(deck_dir, tmp_path):
    manifest = extract_deck_text(deck_dir, tmp_path / "manifest.json")
    assert manifest["slide_count"] == 2
    slide1 = manifest["slides"][0]
    assert slide1["slide_id"] == "slide_001"
    node_ids = [n["node_id"] for n in slide1["nodes"]]
    assert node_ids == ["slide_001#n0", "slide_001#n1"]
    assert slide1["nodes"][0]["text"] == "Welcome"
    assert slide1["nodes"][1]["text"] == "This is the intro slide."


def test_extract_deck_text_writes_manifest_file(deck_dir, tmp_path):
    out = tmp_path / "manifest.json"
    extract_deck_text(deck_dir, out)
    assert out.exists()
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert loaded["slide_count"] == 2


def test_apply_translations_replaces_text_and_preserves_assets(deck_dir, tmp_path):
    localization = {
        "language": "zh-TW",
        "run_id": "r1",
        "title": "測試",
        "segments": [
            {
                "slide_index": 1,
                "slide_id": "slide_001",
                "slide_description": "intro",
                "narration": "...",
                "caption": "...",
                "slide_translations": [
                    {"node_id": "slide_001#n0", "text": "歡迎"},
                    {"node_id": "slide_001#n1", "text": "這是介紹投影片。"},
                ],
            },
            {
                "slide_index": 2,
                "slide_id": "slide_002",
                "slide_description": "features",
                "narration": "...",
                "caption": "...",
                "slide_translations": [
                    {"node_id": "slide_002#n0", "text": "功能"},
                    {"node_id": "slide_002#n1", "text": "快速、簡單、可靠。"},
                ],
            },
        ],
    }
    localization_path = tmp_path / "localization_zh-TW.json"
    localization_path.write_text(json.dumps(localization, ensure_ascii=False), encoding="utf-8")

    out_dir = tmp_path / "translated_zh-TW"
    result = apply_translations(deck_dir=deck_dir, localization_path=localization_path, out_dir=out_dir)

    assert result["nodes_applied"] == 4
    translated_html = (out_dir / "slide_001.html").read_text(encoding="utf-8")
    assert "歡迎" in translated_html
    assert "這是介紹投影片。" in translated_html
    # Non-slide assets are copied over untouched.
    assert (out_dir / "styles.css").exists()


def test_apply_translations_fails_loudly_on_unknown_node_id(deck_dir, tmp_path):
    localization = {
        "language": "zh-TW",
        "run_id": "r1",
        "title": "測試",
        "segments": [
            {
                "slide_index": 1,
                "slide_id": "slide_001",
                "slide_description": "intro",
                "narration": "...",
                "caption": "...",
                "slide_translations": [
                    {"node_id": "slide_001#n0", "text": "歡迎"},
                    {"node_id": "slide_001#n1", "text": "這是介紹投影片。"},
                    {"node_id": "slide_001#n99", "text": "unexpected"},
                ],
            }
        ],
    }
    localization_path = tmp_path / "localization_zh-TW.json"
    localization_path.write_text(json.dumps(localization, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ApplyTranslationsError):
        apply_translations(deck_dir=deck_dir, localization_path=localization_path, out_dir=tmp_path / "out")
