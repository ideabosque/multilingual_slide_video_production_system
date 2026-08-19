"""Validate Agent 1's outputs before handoff to Agent 4
(slide_deck_localization SKILL.md "Validation criteria"): required
languages generated, narration/captions/translations present, every
manifest node ID covered, terminology preserved.
"""
from __future__ import annotations

import json
from pathlib import Path

from multilingual_slide_video_agent import schemas
from multilingual_slide_video_agent import terminology


def validate_localization(
    *,
    slide_analysis_path: str | None = None,
    localization_path: str | None = None,
    language: str | None = None,
    manifest_path: str | None = None,
    project_path: str | None = None,
) -> dict:
    project_terminology = None
    if project_path:
        project_doc = json.loads(Path(project_path).read_text(encoding="utf-8"))
        project_terminology = project_doc.get("terminology")

    errors: list[str] = []
    warnings: list[str] = []

    if slide_analysis_path:
        doc = json.loads(Path(slide_analysis_path).read_text(encoding="utf-8"))
        result = schemas.validate_slide_analysis(doc)
        errors += [f"slide_analysis: {e}" for e in result.errors]
        warnings += [f"slide_analysis: {w}" for w in result.warnings]

    localization_doc = None
    if localization_path:
        if not language:
            return {"ok": False, "errors": ["language is required with localization_path"]}
        localization_doc = json.loads(Path(localization_path).read_text(encoding="utf-8"))
        result = schemas.validate_localization(localization_doc, language=language)
        errors += [f"localization[{language}]: {e}" for e in result.errors]
        warnings += [f"localization[{language}]: {w}" for w in result.warnings]

        for seg in localization_doc.get("segments", []):
            for text, label in ((seg.get("narration", ""), "narration"), (seg.get("caption", ""), "caption")):
                report = terminology.check_text(
                    text, language=language,
                    required_preserved_terms=seg.get("terminology", []),
                    project_terminology=project_terminology,
                    context=f"slide {seg.get('slide_id')} {label}",
                )
                for v in report.violations:
                    errors.append(f"terminology[{language}]: {v.kind} '{v.term}' ({v.context})")
            for t in seg.get("slide_translations", []):
                report = terminology.check_text(
                    t.get("text", ""), language=language,
                    project_terminology=project_terminology,
                    context=f"slide {seg.get('slide_id')} node {t.get('node_id')}",
                )
                for v in report.violations:
                    if v.kind == "forbidden_term":
                        errors.append(f"terminology[{language}]: {v.kind} '{v.term}' ({v.context})")

    if manifest_path and localization_doc is not None:
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        coverage = schemas.validate_node_coverage(localization_doc, manifest)
        errors += [f"node_coverage[{language}]: {e}" for e in coverage.errors]
        warnings += [f"node_coverage[{language}]: {w}" for w in coverage.warnings]

    return {"ok": not errors, "errors": errors, "warnings": warnings}
