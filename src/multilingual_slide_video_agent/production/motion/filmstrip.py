"""Filmstrips for reviewing motion (motion-engines-and-hardening-plan C6):
one row per slide, with frames at fixed fractions of that slide's own
time, labelled with the slide id and the second each frame shows. The
motion-design skill inspects them to catch clipped or overflowing
elements, motion that never happened, and clutter; the human reviewer
sees the same sheet next to the preview video.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from multilingual_slide_video_agent.production.motion.errors import MotionError

FRACTIONS = (0.0, 0.15, 0.3, 0.6, 0.95)


def _frame(video: Path, seconds: float, out: Path, width: int) -> None:
    result = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{seconds:.3f}", "-i", str(video),
         "-frames:v", "1", "-vf", f"scale={width}:-2", str(out)],
        capture_output=True, text=True,
    )
    if result.returncode != 0 or not out.exists():
        raise MotionError(f"couldn't extract a frame at {seconds:.2f}s from {video}: {result.stderr.strip()}")


def make_filmstrip(video: str | Path, per_slide: list[dict[str, Any]], out_path: str | Path, *,
                   fractions: tuple[float, ...] = FRACTIONS, thumb_width: int = 320,
                   slide_ids: list[str] | None = None) -> Path:
    """Write the filmstrip PNG for `video`. `per_slide` is a motion
    manifest's list ({slide_id, start, end}); `slide_ids` limits the rows."""
    from PIL import Image, ImageDraw

    video, out = Path(video), Path(out_path)
    rows = [s for s in per_slide if slide_ids is None or s["slide_id"] in slide_ids]
    if not rows:
        raise MotionError("no slides to put in the filmstrip")
    label_w, caption_h, gap = 120, 18, 4
    with tempfile.TemporaryDirectory(prefix="msv_filmstrip_") as tmp:
        thumbs: list[list[tuple[Image.Image, float]]] = []
        for i, slide in enumerate(rows):
            row = []
            for j, fraction in enumerate(fractions):
                # Stay a hair inside the slide, so 0% and 95% never land
                # on a neighbour's frame.
                t = slide["start"] + 0.04 + fraction * max(0.0, slide["end"] - slide["start"] - 0.08)
                path = Path(tmp) / f"{i}_{j}.png"
                _frame(video, t, path, thumb_width)
                row.append((Image.open(path).convert("RGB"), t))
            thumbs.append(row)
        thumb_h = thumbs[0][0][0].height
        sheet = Image.new("RGB", (label_w + len(fractions) * (thumb_width + gap),
                                  len(rows) * (thumb_h + caption_h + gap)), (24, 24, 24))
        draw = ImageDraw.Draw(sheet)
        for i, (slide, row) in enumerate(zip(rows, thumbs)):
            y = i * (thumb_h + caption_h + gap)
            draw.text((8, y + thumb_h // 2 - 6), slide["slide_id"], fill=(240, 240, 240))
            for j, (image, t) in enumerate(row):
                x = label_w + j * (thumb_width + gap)
                sheet.paste(image, (x, y))
                draw.text((x + 4, y + thumb_h + 3), f"{int(fractions[j] * 100)}%  {t:.1f}s", fill=(200, 200, 200))
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return out


def filmstrip_for_render(video: str | Path, motion_json: str | Path, out_path: str | Path, **kwargs: Any) -> Path:
    """The filmstrip of a render-motion output, using its motion manifest."""
    manifest = json.loads(Path(motion_json).read_text(encoding="utf-8"))
    return make_filmstrip(video, manifest["per_slide"], out_path, **kwargs)
