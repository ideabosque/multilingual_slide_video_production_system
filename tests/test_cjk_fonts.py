from multilingual_slide_video_agent.slides.cjk_fonts import (
    CJK_FONT_CANDIDATES,
    _find_font_file,
    inject_cjk_fonts,
)


def test_non_cjk_language_is_a_no_op(tmp_path):
    (tmp_path / "slide_001.html").write_text("<html><head></head><body></body></html>", encoding="utf-8")
    assert inject_cjk_fonts(tmp_path, "en-US") == 0


def test_missing_font_file_is_a_graceful_no_op(monkeypatch, tmp_path):
    # No matching font anywhere on this machine - should skip cleanly
    # rather than crash with FileNotFoundError (the old hardcoded-path
    # behavior).
    monkeypatch.setattr("multilingual_slide_video_agent.slides.cjk_fonts._font_search_dirs", lambda: [])
    assert _find_font_file(CJK_FONT_CANDIDATES["ja-JP"]) is None
    (tmp_path / "slide_001.html").write_text("<html><head></head><body></body></html>", encoding="utf-8")
    assert inject_cjk_fonts(tmp_path, "ja-JP") == 0


def test_injects_and_replaces_font_override(monkeypatch, tmp_path):
    font_dir = tmp_path / "fonts"
    font_dir.mkdir()
    font_file = font_dir / "NotoSansCJKjp-Regular.otf"
    font_file.write_bytes(b"fake-font-bytes")
    monkeypatch.setattr("multilingual_slide_video_agent.slides.cjk_fonts._font_search_dirs", lambda: [font_dir])

    deck_dir = tmp_path / "deck"
    deck_dir.mkdir()
    (deck_dir / "slide_001.html").write_text("<html><head><title>x</title></head><body></body></html>", encoding="utf-8")

    count = inject_cjk_fonts(deck_dir, "ja-JP")
    assert count == 1
    html = (deck_dir / "slide_001.html").read_text(encoding="utf-8")
    assert "CJK-FONT-OVERRIDE" in html
    assert "font/opentype" in html
    assert html.count("CJK-FONT-OVERRIDE") == 1

    # Re-running (e.g. a rerun) must replace the old override, not stack a second one.
    inject_cjk_fonts(deck_dir, "ja-JP")
    html = (deck_dir / "slide_001.html").read_text(encoding="utf-8")
    assert html.count("CJK-FONT-OVERRIDE") == 1
