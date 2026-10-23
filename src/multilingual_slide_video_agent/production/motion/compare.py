"""`msv motion compare` (motion-engines-and-hardening-plan B6 #5, Phase 7):
two renders of the same language, side by side, for human review - usually
the two engines, or a render before and after a change.

For each slide it writes one contact-sheet row: the frame at the slide's
midpoint from A, the same moment from B, and their difference (bright
where they differ). It also reports each slide's duration delta, which
must be 0 ± 1 frame: both renders cut from the same narration timing, so
anything more is a timing bug, not a look difference. The pixel figures
are for reading the sheet, not a pass/fail: HyperFrames substitutes
system fonts (plan status block), so engine comparisons differ in text by
design.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import numpy as np

from multilingual_slide_video_agent.production.motion.errors import MotionError

THUMB = (480, 270)
PIXEL_DELTA = 24


def motion_json_for(video: str | Path) -> Path:
    """The `<stem>.motion.json` render-motion writes next to a video."""
    video = Path(video)
    return video.with_name(f"{video.stem}.motion.json")


def _gray_frame(video: Path, seconds: float) -> np.ndarray:
    w, h = THUMB
    result = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-ss", f"{seconds:.3f}", "-i", str(video), "-frames:v", "1",
         "-vf", f"scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True,
    )
    if result.returncode != 0 or len(result.stdout) != w * h * 3:
        raise MotionError(f"couldn't read a frame at {seconds:.2f}s from {video}")
    return np.frombuffer(result.stdout, dtype=np.uint8).reshape(h, w, 3)


def compare_renders(a_video: str | Path, b_video: str | Path, out_path: str | Path, *,
                    a_motion_json: str | Path | None = None, b_motion_json: str | Path | None = None,
                    labels: tuple[str, str] | None = None) -> dict[str, Any]:
    from PIL import Image, ImageDraw

    a_video, b_video = Path(a_video), Path(b_video)
    a_doc = json.loads(Path(a_motion_json or motion_json_for(a_video)).read_text(encoding="utf-8"))
    b_doc = json.loads(Path(b_motion_json or motion_json_for(b_video)).read_text(encoding="utf-8"))
    a_slides = {s["slide_id"]: s for s in a_doc["per_slide"]}
    b_slides = {s["slide_id"]: s for s in b_doc["per_slide"]}
    if list(a_slides) != list(b_slides):
        raise MotionError(f"the renders have different slides: {list(a_slides)} vs {list(b_slides)}")
    fps = min(a_doc.get("fps") or 30, b_doc.get("fps") or 30)
    names = labels or (a_doc.get("engine", {}).get("name") or "A", b_doc.get("engine", {}).get("name") or "B")

    rows, report = [], []
    for sid, a in a_slides.items():
        b = b_slides[sid]
        delta_frames = round(((b["end"] - b["start"]) - (a["end"] - a["start"])) * fps, 2)
        mid = (a["start"] + a["end"]) / 2
        fa, fb = _gray_frame(a_video, mid), _gray_frame(b_video, mid)
        diff = np.abs(fa.astype(int) - fb.astype(int)).max(axis=2)
        changed = float(np.mean(diff > PIXEL_DELTA))
        rows.append((sid, mid, fa, fb, np.clip(diff * 4, 0, 255).astype(np.uint8)))
        report.append({"slide_id": sid, "duration_delta_frames": delta_frames, "midpoint_seconds": round(mid, 3),
                       "changed_pixel_fraction": round(changed, 4), "timing_ok": abs(delta_frames) <= 1})

    w, h = THUMB
    label_w, header_h, gap = 110, 24, 4
    sheet = Image.new("RGB", (label_w + 3 * (w + gap), header_h + len(rows) * (h + gap)), (24, 24, 24))
    draw = ImageDraw.Draw(sheet)
    for j, title in enumerate((names[0], names[1], "difference")):
        draw.text((label_w + j * (w + gap) + 6, 6), title, fill=(240, 240, 240))
    for i, (sid, mid, fa, fb, diff) in enumerate(rows):
        y = header_h + i * (h + gap)
        entry = report[i]
        draw.text((6, y + 6), sid, fill=(240, 240, 240))
        draw.text((6, y + 24), f"{mid:.1f}s", fill=(180, 180, 180))
        draw.text((6, y + 42), f"{entry['changed_pixel_fraction']:.1%} differ", fill=(180, 180, 180))
        draw.text((6, y + 60), f"{entry['duration_delta_frames']:+g} frames",
                  fill=(120, 220, 120) if entry["timing_ok"] else (240, 90, 90))
        sheet.paste(Image.fromarray(fa), (label_w, y))
        sheet.paste(Image.fromarray(fb), (label_w + w + gap, y))
        sheet.paste(Image.fromarray(diff).convert("RGB"), (label_w + 2 * (w + gap), y))
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return {"ok": all(r["timing_ok"] for r in report), "contact_sheet": str(out), "labels": list(names),
            "fps": fps, "slides": report}
