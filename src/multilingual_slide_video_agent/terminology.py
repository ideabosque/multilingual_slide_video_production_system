"""Terminology preservation and forbidden-term checks.

Used by Agent 1 (before accepting a localization) and Agent 2 (before
rendering) so that acronyms/codes/brand names are never machine-translated
and stale/incorrect content never reaches a rendered video. See
config/terminology.yaml and the slide_deck_localization /
slideshow_video_production skills.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

from multilingual_slide_video_agent.config import terminology_config


@dataclass
class TerminologyViolation:
    kind: str  # "missing_preserved_term" | "forbidden_term"
    term: str
    context: str


@dataclass
class TerminologyReport:
    violations: list[TerminologyViolation] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.violations

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "violations": [v.__dict__ for v in self.violations],
        }


def _project_terms(project_terminology: dict | None) -> tuple[list[str], dict[str, list[str]]]:
    """Merge global terminology.yaml with an optional per-project override.

    project_terminology may supply additional `always_preserve` terms and
    `forbidden_terms` (keyed by language, "*" applies to all languages).
    """
    cfg = terminology_config()
    preserve = list(cfg.get("always_preserve", []))
    forbidden: dict[str, list[str]] = {
        lang: list(terms) for lang, terms in (cfg.get("forbidden_terms") or {}).items()
    }

    if project_terminology:
        preserve.extend(project_terminology.get("always_preserve", []))
        for lang, terms in (project_terminology.get("forbidden_terms") or {}).items():
            forbidden.setdefault(lang, [])
            forbidden[lang].extend(terms)

    return preserve, forbidden


def check_text(
    text: str,
    *,
    language: str,
    required_preserved_terms: Iterable[str] = (),
    project_terminology: dict | None = None,
    context: str = "",
) -> TerminologyReport:
    """Validate that `text` preserves required terms and contains no forbidden terms.

    `required_preserved_terms` are terms that MUST literally appear in this
    specific text (e.g. the terms referenced by a given slide). The broader
    `always_preserve` list from config is informational for callers that
    want to scan for accidental translation but is not enforced as
    "must appear in every segment" since not every segment references
    every term.
    """
    report = TerminologyReport()
    _, forbidden_by_lang = _project_terms(project_terminology)

    for term in required_preserved_terms:
        if term and term not in text:
            report.violations.append(
                TerminologyViolation("missing_preserved_term", term, context)
            )

    forbidden_terms = list(forbidden_by_lang.get("*", [])) + list(forbidden_by_lang.get(language, []))
    lowered = text.lower()
    for term in forbidden_terms:
        if term and term.lower() in lowered:
            report.violations.append(TerminologyViolation("forbidden_term", term, context))

    return report


def pronunciation_hints() -> dict[str, str]:
    return dict(terminology_config().get("pronunciation_hints", {}))


def always_preserve_terms() -> list[str]:
    return list(terminology_config().get("always_preserve", []))


def find_preserved_terms_in_text(text: str) -> list[str]:
    """Return which globally-preserved terms occur in `text` (whole-word match)."""
    found = []
    for term in always_preserve_terms():
        if re.search(rf"(?<![\w]){re.escape(term)}(?![\w])", text):
            found.append(term)
    return found
