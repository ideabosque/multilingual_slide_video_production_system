"""Text-escaping helpers shared by every renderer that writes ffmpeg/libass
input files (render_slideshow.py, production/motion/post.py)."""
from __future__ import annotations

from pathlib import Path


def ass_escape(text: str) -> str:
    """Make arbitrary caption/title text safe for an ASS `Dialogue:` line.

    libass treats `{...}` as an override block and `\\` as the start of an
    escape sequence (`\\n`, `\\N`, `\\h`), so a translated caption containing
    either would lose text or break lines. Braces have real escapes
    (`\\{`/`\\}`); a backslash has none (`\\\\` is not honoured - verified
    by burning test captions), so each literal backslash is followed by an
    invisible U+2060 WORD JOINER, which stops libass reading it as an escape
    without adding a visible character or a line-break opportunity.
    Backslashes are handled first so the escapes added afterwards keep
    their meaning."""
    return (
        text.replace("\\", "\\⁠")
        .replace("{", "\\{")
        .replace("}", "\\}")
        .replace("\r\n", "\n")
        .replace("\n", "\\N")
    )


def concat_quote(path: Path) -> str:
    """Quote a path for an ffmpeg concat-demuxer `file '...'` line. Inside
    single quotes a literal `'` can't be escaped, so it's closed, emitted
    as `\\'`, and reopened - ffmpeg's documented escaping for this case."""
    return "'" + path.as_posix().replace("'", "'\\''") + "'"
