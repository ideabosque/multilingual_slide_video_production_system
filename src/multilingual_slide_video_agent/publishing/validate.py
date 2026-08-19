"""Validate Agent 3's metadata before upload (youtube_video_publishing
SKILL.md "Validation criteria"): title/description exist and fit
YouTube's limits, language is correct, tags are well-formed, terminology
preserved, and the video file exists.
"""
from __future__ import annotations

import json
from pathlib import Path

from multilingual_slide_video_agent import schemas
from multilingual_slide_video_agent import terminology


def validate_metadata(*, metadata_path: str, language: str, video_path: str | None = None) -> dict:
    path = Path(metadata_path)
    if not path.exists():
        return {"ok": False, "errors": [f"metadata file not found: {path}"]}
    metadata = json.loads(path.read_text(encoding="utf-8"))

    result = schemas.validate_publication_metadata(metadata)
    errors = list(result.errors)
    warnings = list(result.warnings)

    if metadata.get("language") != language:
        errors.append(f"metadata language '{metadata.get('language')}' does not match requested '{language}'")

    tags = metadata.get("tags", [])
    tags_length = sum(len(t) for t in tags) + max(len(tags) - 1, 0)
    if tags_length > 500:
        errors.append(f"combined tag length {tags_length} exceeds YouTube's 500-character limit")

    combined_text = metadata.get("title", "") + "\n" + metadata.get("description", "")
    report = terminology.check_text(combined_text, language=language, context="publication metadata")
    for v in report.violations:
        errors.append(f"terminology: {v.kind} '{v.term}' ({v.context})")

    if video_path and not Path(video_path).exists():
        errors.append(f"video file not found: {video_path}")

    return {"ok": not errors, "errors": errors, "warnings": warnings}
