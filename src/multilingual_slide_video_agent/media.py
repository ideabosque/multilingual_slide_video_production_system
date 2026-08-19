"""Small ffprobe helper shared by production rendering and validation.
No video-probing equivalent of the video-source sibling project's
analysis/probe.py is needed here - there is no source video, only
individually-rendered slide images and generated narration clips."""
from __future__ import annotations

import subprocess


def ffprobe_duration(path: str) -> float:
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path),
    ]
    return float(subprocess.check_output(cmd, text=True).strip())
