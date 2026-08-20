"""Inject CJK/Arabic fonts into translated deck HTML files as base64 data URIs.

Playwright's bundled Chromium blocks file:// font loading in @font-face
(CORS/security) and doesn't reliably load system fonts by font-family
name when rendering a local HTML file. The fix: embed the font file as a
base64 data URI in @font-face, which bypasses both restrictions.

Font *files* are resolved at runtime by searching each OS's real font
directories for one of several candidate filenames per language - never
a single hardcoded path - so this works unmodified on Windows, macOS,
and Linux, as long as a matching font is actually installed there (see
README.md "Install": "for CJK captions, a font such as Noto Sans CJK
installed system-wide").
"""
from __future__ import annotations

import base64
import platform
import re
from pathlib import Path

# Candidate font filenames to search for per language, in priority order -
# the first one found on disk wins. Covers Noto Sans CJK/Arabic under the
# various names package managers ship it as (fonts-noto-cjk on Debian/
# Ubuntu, google-noto-sans-cjk-fonts on Fedora, the font-noto-sans-cjk
# Homebrew cask on macOS, the standalone Google Fonts download, ...) plus
# each OS's own bundled CJK fallback font as a last resort.
CJK_FONT_CANDIDATES: dict[str, list[str]] = {
    "ja-JP": [
        "NotoSansCJKjp-Regular.otf", "NotoSansCJKJP-Regular.otf", "NotoSansJP-Regular.ttf",
        "NotoSansCJK-Regular.ttc", "NotoSansCJK-VF.ttc",
        "simhei.ttf", "YuGothM.ttc", "msgothic.ttc",  # Windows fallbacks
        "Hiragino Sans GB.ttc", "PingFang.ttc",  # macOS fallbacks
    ],
    "ko-KR": [
        "NotoSansCJKkr-Regular.otf", "NotoSansCJKKR-Regular.otf", "NotoSansKR-Regular.ttf",
        "NotoSansCJK-Regular.ttc", "NotoSansCJK-VF.ttc",
        "malgun.ttf",  # Windows fallback
        "AppleSDGothicNeo.ttc",  # macOS fallback
    ],
    "zh-CN": [
        "NotoSansCJKsc-Regular.otf", "NotoSansCJKSC-Regular.otf", "NotoSansSC-Regular.ttf",
        "NotoSansCJK-Regular.ttc", "NotoSansCJK-VF.ttc",
        "simhei.ttf",  # Windows fallback
        "PingFang.ttc",  # macOS fallback
    ],
    "zh-TW": [
        "NotoSansCJKtc-Regular.otf", "NotoSansCJKTC-Regular.otf", "NotoSansTC-Regular.ttf",
        "NotoSansCJK-Regular.ttc", "NotoSansCJK-VF.ttc",
        "simhei.ttf",  # Windows fallback (covers Traditional too)
        "PingFang.ttc",  # macOS fallback
    ],
    "ar-SA": [
        "NotoSansArabic-Regular.ttf", "NotoNaskhArabic-Regular.ttf", "NotoSans-Regular.ttf",
        "Geeza Pro.ttc",  # macOS fallback
        "arial.ttf",  # Windows fallback
    ],
}


def _font_search_dirs() -> list[Path]:
    """OS-appropriate real font directories, existing ones only."""
    system = platform.system()
    if system == "Windows":
        candidates = [Path(r"C:\Windows\Fonts")]
    elif system == "Darwin":
        candidates = [
            Path("/System/Library/Fonts"),
            Path("/System/Library/Fonts/Supplemental"),
            Path("/Library/Fonts"),
            Path.home() / "Library/Fonts",
        ]
    else:  # Linux and other POSIX systems
        candidates = [
            Path("/usr/share/fonts"),
            Path("/usr/local/share/fonts"),
            Path.home() / ".fonts",
            Path.home() / ".local/share/fonts",
        ]
    return [d for d in candidates if d.is_dir()]


def _find_font_file(candidates: list[str]) -> Path | None:
    """Search every OS font directory for the first matching candidate
    filename - an exact top-level match first (fast path), then a
    recursive search, since Linux distro font packages commonly nest
    fonts under vendor subdirectories (e.g.
    /usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc)."""
    search_dirs = _font_search_dirs()
    for directory in search_dirs:
        for name in candidates:
            direct = directory / name
            if direct.is_file():
                return direct
    for directory in search_dirs:
        for name in candidates:
            match = next(directory.rglob(name), None)
            if match is not None:
                return match
    return None


# Cache base64-encoded font data by resolved file path.
_font_cache: dict[Path, str] = {}


def _get_font_b64(path: Path) -> str:
    if path not in _font_cache:
        data = path.read_bytes()
        _font_cache[path] = base64.b64encode(data).decode("ascii")
    return _font_cache[path]


def _font_format(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".ttc":
        return "collection"
    if suffix == ".otf":
        return "opentype"
    return "truetype"


def inject_cjk_fonts(translated_dir: str | Path, language: str) -> int:
    """Embed language's resolved font as a base64 @font-face into every
    slide_*.html under translated_dir. Returns the number of files
    touched, or 0 (a no-op, not an error) if the language needs no CJK
    override or no matching font file is found on this machine."""
    if language not in CJK_FONT_CANDIDATES:
        return 0
    font_path = _find_font_file(CJK_FONT_CANDIDATES[language])
    if font_path is None:
        return 0
    font_b64 = _get_font_b64(font_path)
    fmt = _font_format(font_path)

    override = (
        "<!-- CJK-FONT-OVERRIDE -->\n"
        "<style>\n"
        f"  @font-face {{ font-family: 'CJKFont'; src: url(data:font/{fmt};charset=utf-8;base64,{font_b64}); }}\n"
        "  :root {\n"
        "    --font-display: 'CJKFont', 'Iowan Old Style', 'Charter', Georgia, 'Times New Roman', serif !important;\n"
        "    --font-body: 'CJKFont', -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif !important;\n"
        "    --font-mono: 'CJKFont', ui-monospace, 'JetBrains Mono', 'SF Mono', Menlo, monospace;\n"
        "  }\n"
        "</style>\n"
    )

    count = 0
    for html_file in Path(translated_dir).glob("slide_*.html"):
        html = html_file.read_text(encoding="utf-8")
        if "CJK-FONT-OVERRIDE" in html:
            # Remove old override
            html = re.sub(r"<!-- CJK-FONT-OVERRIDE -->.*?</style>\n", "", html, flags=re.DOTALL)
        html = html.replace("</head>", override + "</head>", 1)
        html_file.write_text(html, encoding="utf-8")
        count += 1
    return count


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        slides_base = Path(sys.argv[1])
    else:
        print("Usage: python -m multilingual_slide_video_agent.slides.cjk_fonts <state/run-id/analysis/slides dir>")
        sys.exit(1)

    for lang in CJK_FONT_CANDIDATES:
        translated = slides_base / f"translated_{lang}"
        if not translated.is_dir():
            continue
        found = _find_font_file(CJK_FONT_CANDIDATES[lang])
        if found is None:
            print(f"{lang}: no matching font found on this system, skipped")
            continue
        n = inject_cjk_fonts(translated, lang)
        print(f"{lang}: injected {found.name} into {n} file(s)")
    print("done")
