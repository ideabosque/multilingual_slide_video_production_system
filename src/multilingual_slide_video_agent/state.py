"""Persistent pipeline state: the backbone of resume/retry/idempotency.

One JSON file per run at state/<run_id>.json, matching the shape in
README.md's "Planned CLI surface" section. Agent 4
(slide_video_orchestration) is the only skill that should mutate this
directly; Agents 1-3 report results back to it via their status
envelopes and Agent 4 records the outcome here.

STAGES models the per-language pipeline: analysis (Agent 1) -> translation
-> tts -> rendering -> validation -> publishing (Agents 2/3). Production is
animation-first (motion-engines-and-hardening-plan Part D2): `tts` is
`msv production narrate` (narration audio + the narration-driven slide
timing, no video), then `rendering` is `msv production render-motion`,
which renders the animated video against that timing - so tts has to come
first. Agent 2's work stays split into separate stages so a targeted rerun
of one (e.g. re-rendering after a template change, without regenerating
narration) is possible. Before 2026-10-22 the order was translation ->
rendering -> tts (static screenshots first, then a slideshow built around
the narration). A stage only becomes eligible to run once every earlier
stage for that language is "completed" or "skipped" (see `next_actions`).
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from multilingual_slide_video_agent.config import state_dir

# Identifies how `directory_fingerprint` is computed. Records without it
# were fingerprinted from file mtimes, which can't be compared against a
# content fingerprint - see `fingerprints_comparable`.
FINGERPRINT_ALGO = "content-v1"

# How long a state mutation waits for another process's lock on the same
# run before failing loudly (parallel language rollout contends here).
_LOCK_TIMEOUT_SECONDS = 30

STAGES = ["analysis", "translation", "tts", "rendering", "validation", "publishing"]
TERMINAL_OK_STATUSES = {"completed", "skipped"}
STAGE_STATUSES = {"pending", "in_progress", "completed", "failed", "skipped", "ready_for_review"}

# The first stage after analysis that non-default languages are held at
# until the default-language-first production gate opens (see
# `_production_gate_open`). Everything from here through `validation` is
# "production" for gating purposes.
_GATED_STAGE = "translation"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def directory_fingerprint(path: str | Path) -> str:
    """Content fingerprint used to detect a changed source deck (README
    "Idempotency and artifact reuse"). Hashes every file's relative path
    and full bytes under the deck directory, so it changes exactly when a
    slide/asset is edited, added, removed, or renamed - and not when a
    `git checkout`/copy merely touches mtimes (the previous mtime-based
    version reported false "deck changed" mismatches). Decks are small, so
    reading every byte is cheap."""
    p = Path(path)
    if not p.is_dir():
        return ""
    h = hashlib.sha256()
    for file_path in sorted(p.rglob("*")):
        if file_path.is_file():
            rel = file_path.relative_to(p).as_posix()
            h.update(f"{rel}\0".encode("utf-8"))
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            h.update(b"\0")
    return h.hexdigest()[:16]


def fingerprints_comparable(algo_a: str | None, algo_b: str | None) -> bool:
    """Two recorded fingerprints can only be compared if both were made by
    the current algorithm. A legacy (mtime-based, no algo recorded) value
    can't prove or disprove a content change."""
    return algo_a == FINGERPRINT_ALGO and algo_b == FINGERPRINT_ALGO


def text_fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _empty_language_state() -> dict[str, Any]:
    stages = {
        stage: {
            "status": "pending",
            "updated_at": None,
            "retry_count": 0,
            "artifacts": {},
            "error": None,
            "content_fingerprint": None,
        }
        for stage in STAGES
    }
    return {"stages": stages, "youtube_video_id": None, "youtube_url": None, "publish_approved": False}


@dataclass
class PipelineState:
    run_id: str
    project_id: str
    source_deck: str
    source_deck_fingerprint: str
    languages: dict[str, Any] = field(default_factory=dict)
    source_deck_fingerprint_algo: str | None = FINGERPRINT_ALGO
    auto_publish: bool = False
    default_language: str = "en-US"
    auto_approve_production: bool = False
    production_approved: bool = False
    # The deck's motion design and its approval gate (plan C2): see
    # register_motion / approve_motion / motion_gate.
    motion: dict[str, Any] | None = None
    auto_approve_motion: bool = False
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    skill_versions: dict[str, str] = field(default_factory=dict)

    # ---------- persistence ----------

    @property
    def path(self) -> Path:
        return state_dir() / f"{self.run_id}.json"

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        project_id: str,
        source_deck: str,
        language_codes: list[str],
        auto_publish: bool = False,
        default_language: str = "en-US",
        auto_approve_production: bool = False,
        auto_approve_motion: bool = False,
    ) -> "PipelineState":
        state_dir().mkdir(parents=True, exist_ok=True)
        state = cls(
            run_id=run_id,
            project_id=project_id,
            source_deck=source_deck,
            source_deck_fingerprint=directory_fingerprint(source_deck),
            languages={lang: _empty_language_state() for lang in language_codes},
            auto_publish=auto_publish,
            default_language=default_language if default_language in language_codes else language_codes[0],
            auto_approve_production=auto_approve_production,
            auto_approve_motion=auto_approve_motion,
        )
        state.save()
        return state

    @classmethod
    def load(cls, run_id: str) -> "PipelineState":
        path = state_dir() / f"{run_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"No pipeline state for run_id '{run_id}' at {path}")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        state = cls(
            run_id=data["run_id"],
            project_id=data["project_id"],
            source_deck=data["source_deck"],
            source_deck_fingerprint=data.get("source_deck_fingerprint", ""),
            source_deck_fingerprint_algo=data.get("source_deck_fingerprint_algo"),
            languages=data.get("languages", {}),
            auto_publish=data.get("auto_publish", False),
            default_language=data.get("default_language", "en-US"),
            auto_approve_production=data.get("auto_approve_production", False),
            production_approved=data.get("production_approved", False),
            motion=data.get("motion"),
            auto_approve_motion=data.get("auto_approve_motion", False),
            created_at=data.get("created_at", _now()),
            updated_at=data.get("updated_at", _now()),
            skill_versions=data.get("skill_versions", {}),
        )
        return state

    @classmethod
    @contextmanager
    def transaction(cls, run_id: str) -> Iterator["PipelineState"]:
        """Load, mutate, and save one run's state under an exclusive
        cross-process lock. Every mutating CLI command goes through this:
        language rollout runs per-language production in parallel, and a
        plain load()-mutate-save() lets the last writer silently discard
        another language's concurrent stage update (atomic replace only
        prevents a corrupt file, not a lost update)."""
        from filelock import FileLock, Timeout

        state_dir().mkdir(parents=True, exist_ok=True)
        lock = FileLock(str(state_dir() / f"{run_id}.json.lock"), timeout=_LOCK_TIMEOUT_SECONDS)
        try:
            lock.acquire()
        except Timeout as e:
            raise RuntimeError(
                f"timed out after {_LOCK_TIMEOUT_SECONDS}s waiting for the state lock on run '{run_id}' - "
                "another msv process is holding it (or crashed holding it; filelock releases on process exit)"
            ) from e
        try:
            state = cls.load(run_id)
            yield state
            state.save()
        finally:
            lock.release()

    @classmethod
    def exists(cls, run_id: str) -> bool:
        return (state_dir() / f"{run_id}.json").exists()

    @classmethod
    def latest_run_for_project(cls, project_id: str) -> str | None:
        state_dir().mkdir(parents=True, exist_ok=True)
        candidates = []
        for path in state_dir().glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if data.get("project_id") == project_id:
                candidates.append((data.get("updated_at", ""), data["run_id"]))
        if not candidates:
            return None
        candidates.sort()
        return candidates[-1][1]

    def save(self) -> None:
        self.updated_at = _now()
        state_dir().mkdir(parents=True, exist_ok=True)
        payload = {
            "run_id": self.run_id,
            "project_id": self.project_id,
            "source_deck": self.source_deck,
            "source_deck_fingerprint": self.source_deck_fingerprint,
            "source_deck_fingerprint_algo": self.source_deck_fingerprint_algo,
            "auto_publish": self.auto_publish,
            "default_language": self.default_language,
            "auto_approve_production": self.auto_approve_production,
            "production_approved": self.production_approved,
            "motion": self.motion,
            "auto_approve_motion": self.auto_approve_motion,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "skill_versions": self.skill_versions,
            "languages": self.languages,
        }
        # Atomic write so a crash mid-save never corrupts state we'd need
        # to resume from.
        fd, tmp_path = tempfile.mkstemp(dir=str(state_dir()), suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, self.path)

    # ---------- language / stage management ----------

    def ensure_language(self, language: str) -> None:
        """Add a language job without disturbing any existing language's progress."""
        if language not in self.languages:
            self.languages[language] = _empty_language_state()

    def get_stage(self, language: str, stage: str) -> dict[str, Any]:
        return self.languages[language]["stages"][stage]

    def set_stage(
        self,
        language: str,
        stage: str,
        status: str,
        *,
        artifacts: dict[str, Any] | None = None,
        error: str | None = None,
        content_fingerprint: str | None = None,
        increment_retry: bool = False,
    ) -> None:
        if status not in STAGE_STATUSES:
            raise ValueError(f"Invalid stage status '{status}'. Must be one of {sorted(STAGE_STATUSES)}")
        self.ensure_language(language)
        entry = self.languages[language]["stages"][stage]
        entry["status"] = status
        entry["updated_at"] = _now()
        entry["error"] = error
        if artifacts:
            entry["artifacts"].update(artifacts)
        if content_fingerprint is not None:
            entry["content_fingerprint"] = content_fingerprint
        if increment_retry:
            entry["retry_count"] = entry.get("retry_count", 0) + 1
        self.save()

    def approve_production(self) -> None:
        """Human sign-off releasing every non-default language's
        `translation` stage after reviewing the default language's render.
        Run-level, not per-language: production for the whole run either
        hasn't been reviewed yet or has - there's no partial state here by
        design, so a bug caught in the default language's render is caught
        once, before it's repeated (and TTS-billed) across every other
        language."""
        self.production_approved = True
        self.save()

    # ---------- motion design gate (plan C2) ----------
    #
    # The deck's motion design is a creative output with its own run-level
    # approval, like production. The gate is keyed to the design file's
    # content: editing an approved design reopens it, so what renders in
    # every language is exactly what a human approved.

    def register_motion(self, design_path: str, fingerprint: str) -> None:
        """Record the deck's motion design as a draft awaiting review. Re-
        registering the approved file unchanged keeps its approval."""
        current = self.motion or {}
        if current.get("status") == "approved" and current.get("approved_fingerprint") == fingerprint:
            current.update({"design": design_path, "fingerprint": fingerprint, "updated_at": _now()})
        else:
            current = {"design": design_path, "fingerprint": fingerprint, "status": "draft",
                       "approved_fingerprint": None, "approved_at": None, "notes": None, "updated_at": _now()}
        self.motion = current
        self.save()

    def approve_motion(self, fingerprint: str) -> None:
        """Approve the registered design as its file is now (`fingerprint`)."""
        if not self.motion:
            raise ValueError("no motion design registered for this run (msv pipeline register-motion)")
        if fingerprint != self.motion["fingerprint"]:
            raise ValueError("the motion design changed since it was registered; register it again and review "
                             "the new preview before approving")
        self.motion.update({"status": "approved", "approved_fingerprint": fingerprint, "approved_at": _now(),
                            "updated_at": _now()})
        self.save()

    def reject_motion(self, notes: str) -> None:
        """A reviewer's notes in plain language; the design goes back for revision."""
        if not self.motion:
            raise ValueError("no motion design registered for this run (msv pipeline register-motion)")
        self.motion.update({"status": "rejected", "approved_fingerprint": None, "approved_at": None,
                            "notes": notes, "updated_at": _now()})
        self.save()

    def motion_gate(self, language: str, fingerprint: str) -> str | None:
        """Why `language` may not render this design yet, or None when it
        may. The default language renders a draft (that's how the design is
        reviewed); every other language needs this exact file approved,
        unless PIPELINE_AUTO_APPROVE_MOTION was set for the run."""
        if language == self.default_language or self.auto_approve_motion:
            return None
        motion = self.motion or {}
        if not motion:
            return "this run has no registered motion design (msv pipeline register-motion, then approve-motion)"
        if motion.get("approved_fingerprint") == fingerprint:
            return None
        if motion.get("status") == "approved":
            return "the motion design changed after it was approved; it needs a fresh review (msv pipeline approve-motion)"
        return f"the motion design is {motion.get('status', 'draft')}, not approved (msv pipeline approve-motion)"

    def approve_publish(self, language: str) -> None:
        """Human sign-off to release one language's `publishing` stage when
        PIPELINE_AUTO_PUBLISH is false (`publish_pending` command). Does
        not affect any other language."""
        self.ensure_language(language)
        self.languages[language]["publish_approved"] = True
        self.save()

    def set_youtube_result(self, language: str, video_id: str, url: str) -> None:
        self.ensure_language(language)
        self.languages[language]["youtube_video_id"] = video_id
        self.languages[language]["youtube_url"] = url
        self.save()

    def invalidate_from(self, language: str, from_stage: str) -> list[str]:
        """Reset `from_stage` and every downstream stage to pending, clearing
        their artifacts, so they regenerate on the next run. Earlier stages
        and other languages are untouched.

        Any rerun also withdraws this language's publish approval: what was
        approved is being replaced, so publishing waits for a fresh human
        review of the new video or metadata (decided 2026-10-22)."""
        if from_stage not in STAGES:
            raise ValueError(f"Unknown stage '{from_stage}'")
        self.ensure_language(language)
        self.languages[language]["publish_approved"] = False
        idx = STAGES.index(from_stage)
        reset = []
        for stage in STAGES[idx:]:
            entry = self.languages[language]["stages"][stage]
            entry["status"] = "pending"
            entry["artifacts"] = {}
            entry["error"] = None
            reset.append(stage)
        lang_data = self.languages[language]
        if from_stage != "publishing" and lang_data.get("youtube_video_id"):
            # An earlier stage reruns, so the video file itself will change
            # and YouTube can't replace an uploaded video's file - the next
            # publish must be a fresh upload. Keep the superseded upload on
            # record (never delete it automatically) so a human can unlist
            # or remove it. A rerun of `publishing` alone keeps the id, so
            # the publish agent does a metadata-only update instead of
            # uploading a duplicate.
            lang_data.setdefault("previous_youtube_videos", []).append({
                "youtube_video_id": lang_data["youtube_video_id"],
                "youtube_url": lang_data.get("youtube_url"),
                "superseded_at": _now(),
                "reason": f"rerun from '{from_stage}'",
            })
            lang_data["youtube_video_id"] = None
            lang_data["youtube_url"] = None
        if language == self.default_language and STAGES.index("validation") >= idx:
            # The previously-approved default-language render no longer
            # exists; every other language's `translation` stage re-locks
            # until a human reviews the redone default and approves again.
            self.production_approved = False
        self.save()
        return reset

    # ---------- planning ----------

    def is_stage_ready(self, language: str, stage: str) -> bool:
        """A stage is ready to run once every prior stage is completed/skipped."""
        idx = STAGES.index(stage)
        for prior in STAGES[:idx]:
            if self.languages[language]["stages"][prior]["status"] not in TERMINAL_OK_STATUSES:
                return False
        return True

    def _production_gate_open(self) -> bool:
        """Whether non-default languages are cleared to start
        `translation`/`rendering`/`tts`: the default language must have
        finished (and passed) validation, and a human must have explicitly
        approved production via `approve_production` (or
        PIPELINE_AUTO_APPROVE_PRODUCTION=true) - see `approve_production`'s
        docstring for why this is run-level."""
        default_stages = self.languages.get(self.default_language, {}).get("stages", {})
        default_ready = default_stages.get("validation", {}).get("status") in TERMINAL_OK_STATUSES
        return default_ready and (self.auto_approve_production or self.production_approved)

    def next_actions(self, languages: list[str] | None = None) -> list[dict[str, str]]:
        """Return the ordered list of (language, stage) jobs that still need
        to run to complete the pipeline, skipping anything already
        completed. This is what `resume_pipeline`/`run_pipeline` execute.

        The default language's `translation` stage is always offered as
        soon as its `analysis` is done. Every other language's
        `translation` stage is held until the default language has been
        produced and a human has approved it (`approve_production`) - see
        `_production_gate_open`.
        """
        actions = []
        target_languages = languages or list(self.languages.keys())
        production_gate_open = self._production_gate_open()
        for language in target_languages:
            self.ensure_language(language)
            for stage in STAGES:
                status = self.languages[language]["stages"][stage]["status"]
                if status in TERMINAL_OK_STATUSES:
                    continue
                if (
                    stage == _GATED_STAGE
                    and status == "pending"
                    and language != self.default_language
                    and not production_gate_open
                ):
                    # Held until the default language is produced and
                    # approved (see _production_gate_open) - reported as
                    # blocked_pending_production_approval, not queued.
                    continue
                if (
                    stage == "publishing"
                    and status == "pending"
                    and not self.auto_publish
                    and not self.languages[language].get("publish_approved")
                ):
                    # Held for human approval until explicitly released via
                    # `publish_pending`. Reported as ready_for_review, not
                    # queued as a runnable action.
                    continue
                if not self.is_stage_ready(language, stage):
                    break
                actions.append({"language": language, "stage": stage})
                break  # one actionable stage per language per planning pass
        return actions

    def language_status(self, language: str) -> str:
        stages = self.languages[language]["stages"]
        statuses = {s["status"] for s in stages.values()}
        if statuses == {"completed"} or statuses == {"completed", "skipped"}:
            return "completed"
        if any(s["status"] == "failed" for s in stages.values()):
            return "failed"
        pre_publish_stages = [s for s in STAGES if s != "publishing"]
        if (
            all(stages[s]["status"] in TERMINAL_OK_STATUSES for s in pre_publish_stages)
            and stages["publishing"]["status"] == "pending"
            and not self.auto_publish
            and not self.languages[language].get("publish_approved")
        ):
            return "ready_for_review"
        if (
            language != self.default_language
            and stages["analysis"]["status"] in TERMINAL_OK_STATUSES
            and stages[_GATED_STAGE]["status"] == "pending"
            and not self._production_gate_open()
        ):
            return "blocked_pending_production_approval"
        if any(s["status"] == "in_progress" for s in stages.values()):
            return "in_progress"
        return "pending"

    def overall_status(self) -> str:
        per_language = [self.language_status(lang) for lang in self.languages]
        if not per_language:
            return "pending"
        if all(s == "completed" for s in per_language):
            return "completed"
        if any(s == "failed" for s in per_language):
            return "partially_failed" if any(s == "completed" for s in per_language) else "failed"
        if all(s in {"completed", "ready_for_review"} for s in per_language):
            return "ready_for_review"
        if any(s == "blocked_pending_production_approval" for s in per_language):
            return "awaiting_production_approval"
        return "in_progress"

    def to_report(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "project_id": self.project_id,
            "source_deck": self.source_deck,
            "auto_publish": self.auto_publish,
            "default_language": self.default_language,
            "production_approved": self.production_approved or self.auto_approve_production,
            "motion": ({**self.motion, "auto_approve": self.auto_approve_motion} if self.motion
                       else {"status": "none", "auto_approve": self.auto_approve_motion}),
            "overall_status": self.overall_status(),
            "updated_at": self.updated_at,
            "languages": {
                lang: {
                    "status": self.language_status(lang),
                    "stages": {s: st["status"] for s, st in data["stages"].items()},
                    "youtube_video_id": data.get("youtube_video_id"),
                    "youtube_url": data.get("youtube_url"),
                    "previous_youtube_videos": data.get("previous_youtube_videos", []),
                }
                for lang, data in self.languages.items()
            },
        }
