"""Agent 2 output validation (slideshow_video_production SKILL.md
"Validation criteria")."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from multilingual_slide_video_agent.state import PipelineState


def _ffprobe_ok(path: Path) -> bool:
    try:
        subprocess.run(["ffprobe", "-v", "error", str(path)], check=True, capture_output=True, text=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def validate_production(
    *,
    production_path: str,
    localization_path: str | None = None,
    run_id: str | None = None,
) -> dict:
    errors: list[str] = []
    warnings: list[str] = []

    path = Path(production_path)
    if not path.exists():
        return {"ok": False, "errors": [f"production.json not found: {path}"]}
    production = json.loads(path.read_text(encoding="utf-8"))

    for field in ("narration_audio", "captions", "output_video"):
        p = Path(production.get(field) or "")
        if not p.exists():
            errors.append(f"missing expected artifact for '{field}': {p}")

    output_video = Path(production.get("output_video") or "")
    if output_video.exists() and not _ffprobe_ok(output_video):
        errors.append(f"output video is not playable (ffprobe failed): {output_video}")

    if not production.get("duration_check_ok", False):
        warnings.append(
            f"output duration {production.get('output_duration_seconds')}s deviates from "
            f"the computed slideshow duration {production.get('total_duration_seconds')}s beyond tolerance"
        )

    if production.get("pacing_warnings"):
        warnings.extend(production["pacing_warnings"])

    if localization_path:
        localization = json.loads(Path(localization_path).read_text(encoding="utf-8"))
        expected_ids = {s["slide_id"] for s in localization.get("segments", [])}
        produced_ids = set(production.get("slides", []))
        missing = expected_ids - produced_ids
        if missing:
            errors.append(f"slides missing from rendered output: {sorted(missing)}")

        expected_order = [s["slide_id"] for s in sorted(localization.get("segments", []), key=lambda s: s["slide_index"])]
        if production.get("slides") not in (expected_order, []):
            if production.get("slides") != expected_order:
                errors.append(
                    f"slide order in rendered output ({production.get('slides')}) does not match "
                    f"slide_index order from the localization input ({expected_order})"
                )

    if run_id:
        try:
            state = PipelineState.load(run_id)
            if production.get("source_deck_fingerprint") != state.source_deck_fingerprint:
                errors.append(
                    "source_deck_fingerprint mismatch: this video was not rendered from the "
                    "run's registered clean original source deck (possible translated-on-translated build)"
                )
        except FileNotFoundError as e:
            warnings.append(str(e))

    return {"ok": not errors, "errors": errors, "warnings": warnings}
