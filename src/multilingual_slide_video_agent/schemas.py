"""Validation for the structured data agents pass to one another.

These are the machine-readable contracts described in
`.claude/skills/slide_deck_localization/SKILL.md` (Agent 1 output),
`.claude/skills/slideshow_video_production/SKILL.md` (Agent 2 output),
and each skill's "Handoff contract" section. Kept dependency-free (no
jsonschema) so every skill script can import this without an extra
install.
"""
from __future__ import annotations

from typing import Any


class ValidationResult:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "errors": self.errors, "warnings": self.warnings}


def _require_keys(obj: dict, keys: list[str], where: str, result: ValidationResult) -> None:
    for key in keys:
        if key not in obj or obj[key] in (None, ""):
            result.error(f"{where}: missing required field '{key}'")


def validate_slide_analysis(doc: dict) -> ValidationResult:
    """Validate Agent 1's language-independent slide analysis document."""
    result = ValidationResult()
    _require_keys(doc, ["project_id", "run_id", "source_deck", "slides"], "slide_analysis", result)

    slides = doc.get("slides", [])
    if not isinstance(slides, list) or not slides:
        result.error("slide_analysis: 'slides' must be a non-empty list")
        return result

    seen_indexes = set()
    seen_ids = set()
    for i, slide in enumerate(slides):
        where = f"slide[{i}]"
        _require_keys(slide, ["slide_index", "slide_id", "slide_description"], where, result)
        slide_index = slide.get("slide_index")
        slide_id = slide.get("slide_id")
        if slide_index in seen_indexes:
            result.error(f"{where}: duplicate slide_index '{slide_index}'")
        seen_indexes.add(slide_index)
        if slide_id in seen_ids:
            result.error(f"{where}: duplicate slide_id '{slide_id}'")
        seen_ids.add(slide_id)
    return result


def validate_localization(
    doc: dict,
    *,
    language: str,
    caption_soft_limit: int = 90,
) -> ValidationResult:
    """Validate Agent 1's per-language narration/caption/translation output
    (slide_deck_localization SKILL.md). Unlike the video-source sibling
    project, there is no source duration to check timestamps against - a
    slide's on-screen duration is derived from its own narration length
    (see slideshow_video_production SKILL.md's "Slide duration is
    narration-driven"), so this validates content/structure only."""
    result = ValidationResult()
    _require_keys(doc, ["language", "run_id", "title", "segments"], "localization", result)

    if doc.get("language") not in (None, language):
        result.error(f"localization: language field '{doc.get('language')}' does not match requested '{language}'")

    title = str(doc.get("title", "")).strip()
    if title and len(title) > 100:
        result.warn(f"localization: title is {len(title)} chars - a marketing headline should usually be much shorter")

    segments = doc.get("segments", [])
    if not isinstance(segments, list) or not segments:
        result.error("localization: 'segments' must be a non-empty list")
        return result

    seen_indexes = set()
    for i, seg in enumerate(segments):
        where = f"segment[{i}]"
        _require_keys(
            seg,
            ["slide_index", "slide_id", "slide_description", "narration", "caption"],
            where,
            result,
        )
        slide_index = seg.get("slide_index")
        if slide_index in seen_indexes:
            result.error(f"{where}: duplicate slide_index '{slide_index}'")
        seen_indexes.add(slide_index)

        if not str(seg.get("narration", "")).strip():
            result.error(f"{where}: narration is empty")
        caption = str(seg.get("caption", "")).strip()
        if not caption:
            result.error(f"{where}: caption is empty")
        elif len(caption) > caption_soft_limit:
            result.warn(
                f"{where}: caption is {len(caption)} chars (soft budget: {caption_soft_limit}) - "
                "captions should be a short on-screen highlight, not the full narration sentence"
            )
        narration = str(seg.get("narration", ""))
        if caption and narration and caption.strip() == narration.strip():
            result.warn(f"{where}: caption is identical to narration - shorten the caption to a highlight instead of duplicating the full sentence")

        translations = seg.get("slide_translations", [])
        if not isinstance(translations, list):
            result.error(f"{where}: 'slide_translations' must be a list")
        else:
            seen_node_ids = set()
            for t in translations:
                node_id = t.get("node_id")
                if not node_id:
                    result.error(f"{where}: slide_translations entry missing 'node_id'")
                    continue
                if node_id in seen_node_ids:
                    result.error(f"{where}: duplicate node_id '{node_id}' in slide_translations")
                seen_node_ids.add(node_id)
                if not str(t.get("text", "")).strip():
                    result.error(f"{where}: slide_translations node '{node_id}' has empty text")
    return result


def validate_node_coverage(localization: dict, manifest: dict) -> ValidationResult:
    """Cross-check that every translatable node in `manifest` (Agent 1's
    `msv slides extract-text` output) has a corresponding translation in
    `localization`'s `slide_translations`, and that no translation
    references a node ID the manifest doesn't have (deck structure changed
    since analysis - see slide_deck_localization SKILL.md)."""
    result = ValidationResult()
    manifest_nodes_by_slide: dict[str, set[str]] = {}
    for slide in manifest.get("slides", []):
        slide_id = slide.get("slide_id")
        manifest_nodes_by_slide[slide_id] = {n["node_id"] for n in slide.get("nodes", [])}

    for seg in localization.get("segments", []):
        slide_id = seg.get("slide_id")
        expected = manifest_nodes_by_slide.get(slide_id)
        if expected is None:
            result.error(f"localization: slide_id '{slide_id}' not found in manifest")
            continue
        translated_ids = {t.get("node_id") for t in seg.get("slide_translations", [])}
        missing = expected - translated_ids
        extra = translated_ids - expected
        if missing:
            result.error(f"slide '{slide_id}': node(s) missing a translation: {sorted(missing)}")
        if extra:
            result.error(f"slide '{slide_id}': translation references unknown node_id(s): {sorted(extra)}")
    return result


def validate_production_result(doc: dict) -> ValidationResult:
    """Validate Agent 2's production.json."""
    result = ValidationResult()
    _require_keys(
        doc,
        ["run_id", "language", "source_deck", "narration_audio", "captions", "output_video"],
        "production_result",
        result,
    )
    return result


def validate_publication_metadata(doc: dict) -> ValidationResult:
    """Validate Agent 3's per-language metadata before upload."""
    result = ValidationResult()
    _require_keys(doc, ["language", "title", "description", "privacy_status"], "publication_metadata", result)
    title = doc.get("title", "")
    if title and len(title) > 100:
        result.error(f"publication_metadata: title exceeds YouTube's 100-character limit ({len(title)})")
    description = doc.get("description", "")
    if description and len(description) > 5000:
        result.error(f"publication_metadata: description exceeds YouTube's 5000-character limit ({len(description)})")
    return result


def validate_status_envelope(doc: dict) -> ValidationResult:
    result = ValidationResult()
    _require_keys(doc, ["agent", "run_id", "status", "outputs"], "status_envelope", result)
    valid_statuses = {"completed", "failed", "in_progress", "skipped", "pending"}
    if doc.get("status") not in valid_statuses:
        result.error(f"status_envelope: status '{doc.get('status')}' not in {sorted(valid_statuses)}")
    return result
