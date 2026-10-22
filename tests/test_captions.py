import subprocess
from pathlib import Path

import pytest

from multilingual_slide_video_agent.production.captions import ass_escape, concat_quote


def test_ass_escape_neutralizes_override_blocks_and_backslashes():
    escaped = ass_escape(r"Use {curly} and C:\path\new")
    assert escaped == "Use \\{curly\\} and C:\\\u2060path\\\u2060new"


def test_ass_escape_turns_real_newlines_into_ass_line_breaks():
    assert ass_escape("one\ntwo\r\nthree") == "one\\Ntwo\\Nthree"


def test_ass_escape_keeps_a_literal_backslash_n_literal():
    # The source text contains the two characters "\N", not a newline - it
    # must not become a line break.
    assert ass_escape(r"a \N b") == "a \\\u2060N b"


def test_ass_escape_leaves_plain_and_cjk_text_unchanged():
    assert ass_escape("歡迎 IdeaBosque, 40% faster") == "歡迎 IdeaBosque, 40% faster"


def test_concat_quote_escapes_single_quotes():
    assert concat_quote(Path("/tmp/O'Brien/slide.png")) == "'/tmp/O'\\''Brien/slide.png'"


@pytest.mark.requires_ffmpeg
def test_concat_quote_survives_a_real_ffmpeg_concat(tmp_path):
    odd_dir = tmp_path / "O'Brien deck"
    odd_dir.mkdir()
    clips = []
    for i in range(2):
        clip = odd_dir / f"tone {i}.wav"
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=d=0.5", str(clip)],
            check=True,
        )
        clips.append(clip)
    concat_list = tmp_path / "list.txt"
    concat_list.write_text("\n".join(f"file {concat_quote(c)}" for c in clips), encoding="utf-8")
    out = tmp_path / "out.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(concat_list), str(out)],
        check=True,
    )
    assert out.exists() and out.stat().st_size > 0
