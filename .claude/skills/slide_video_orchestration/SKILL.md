---
name: slide-video-orchestration
description: Pipeline orchestration skill for Agent 4, the primary entry point for the whole multilingual slide video system. Determines which of Agents 1-3 need to run, in what order, for which languages, tracks persistent per-language/per-stage state for resume and retry, and enforces the human-review gate before YouTube publishing. Use for any end-to-end "produce localized slideshow videos" request, for checking pipeline status, or for rerunning a specific language or stage after a failure.
---

# Slide Video Orchestration Skill

## Purpose

Be the single entry point external requests go through. Decide what work
is left to do, drive Agents 1-3 (each via their own skill) to do it, and
never redo completed, still-valid work.

## Responsibilities

- Accept an original English HTML slide deck and load project
  configuration (`config/*.yaml`, `.env`).
- Determine target languages (`SUPPORTED_LANGUAGES`, or an explicit list).
- Create/resume a pipeline run and its persistent state
  (`state/<run_id>.json`, via the `msv pipeline` CLI).
- Invoke Agent 1 (slide_deck_localization), validate its output, create
  per-language jobs.
- Invoke Agent 2 (slideshow_video_production) directly for the run's
  default language, and for any single targeted rerun of one non-default
  language; invoke the Language Rollout Agent (multilingual_rollout) once
  the production-approval gate opens, to fan out to every other language
  in one dispatch — see "Default-language-first production gate".
- Invoke Agent 3 (youtube_video_publishing) only for language(s) the user
  has explicitly approved for publishing in conversation — see "Human
  review gate"; a `ready_for_review` status alone is never sufficient.
- Track errors, retry recoverable failures up to `PIPELINE_MAX_RETRIES`,
  resume interrupted runs, support rerunning one language or one stage.
- Maintain centralized logs (`logs/<run_id>.jsonl`) and produce a final
  execution report.

## Required inputs

`source_deck` (a directory of `slide_NNN.html` files), target `languages`
(optional — defaults to `SUPPORTED_LANGUAGES`), `project_id` (a short
slug for the deck/project), optionally `default_language` (defaults to
`DEFAULT_LANGUAGE`; must be one of `languages` — reviewed first, see
"Default-language-first production gate"), optionally an existing
`run_id` to resume.

## Pipeline commands

All backed by the `msv pipeline` CLI (installed via `pip install -e .` at
the repo root), which owns every read/write of `state/<run_id>.json`.
Every subcommand prints one JSON object and uses exit code 0/1 for
success/failure so this is safe to drive from Bash.

| Command | CLI | Purpose |
|---|---|---|
| `run_pipeline` | `msv pipeline init` then follow `next-actions` | Start a new run and execute until nothing is left to do (or publishing is held for review) |
| `resume_pipeline` | `msv pipeline next-actions --run-id ...` then execute | Continue an existing run from wherever it stopped |
| `get_pipeline_status` | `msv pipeline status` | Report state without doing any work |
| `rerun_language` | `msv pipeline rerun-language --language ...` | Reset one language from a given stage onward, then resume |
| `rerun_stage` | `msv pipeline rerun-stage --stage ...` | Reset one stage (one or all languages), then resume |
| `validate_pipeline` | `msv pipeline validate` | Consistency check: source deck still present/unchanged, no orphaned in-progress stages, retry budgets |
| *(production review)* | `msv pipeline approve-production` | Human-approved release of every non-default language's `translation`/`rendering`/`tts` stages, after reviewing the default language's render — see "Default-language-first production gate" |
| `publish_pending` | `msv pipeline approve-publish` then run `publishing` actions | Human-approved release of videos held at `ready_for_review` |

## The run loop (what `run_pipeline` / `resume_pipeline` actually do)

1. `msv pipeline init` (new run) or resolve an existing `--run-id`
   (resume). `init` fails loudly if the deck or a requested language is
   missing/unconfigured — fix that before any state is created.
2. Loop:
   a. `msv pipeline next-actions --run-id <id>` → a list of
      `{"language": ..., "stage": ...}` jobs, one per language, in
      dependency order (a language's stage is only offered once every
      earlier stage for that language is `completed`/`skipped`).
   b. If empty, stop — check `overall_status` in the report:
      `completed`, `awaiting_production_approval` (default language done,
      other languages held — see "Default-language-first production
      gate"), `ready_for_review` (publishing held pending human
      approval), or `failed`/`partially_failed`.
   c. For each action, dispatch to the owning skill per the dispatch
      table below — for the default language and single targeted
      reruns that means `slideshow-production-agent` directly; for the
      bulk "every other language" case (once the gate opens) that means
      one `language-rollout-agent` dispatch instead of looping yourself.
      Each language's outcome is still recorded via its own
      `msv pipeline set-stage` call (done by whichever agent actually
      produced it) so a failure in one language never blocks or corrupts
      another's progress.

### Dispatch table

| Stage | Skill invoked | What Agent 4 does |
|---|---|---|
| `analysis` | `slide_deck_localization` | Follow that skill's procedure once per run (its output covers every language); on success, `set-stage` each language's `analysis` to `completed` with the `localization_<language>.json` path as an artifact |
| `translation` + `rendering` + `tts` (default language, or a single targeted rerun) | `slideshow_video_production` | Dispatch `slideshow-production-agent` directly for that one language; it runs `msv slides apply-translations`/`render-images` and `msv production render-slideshow`/`validate`, and records its own `translation`/`rendering`/`tts`/`validation` stages |
| `translation` + `rendering` + `tts` (every other language, bulk) | `multilingual_rollout` | Once the production gate opens (see below), dispatch `language-rollout-agent` **once** — it fans out to `slideshow-production-agent` per remaining language itself; do not loop through these languages yourself |
| `validation` | (this skill, or already handled above) | `slideshow-production-agent` validates as part of its own dispatch (both for the default language and via the rollout agent); only re-run `msv production validate`/`msv slides validate` yourself if you need an independent re-check |
| `publishing` | `youtube_video_publishing` | Only reached once `PIPELINE_AUTO_PUBLISH=true`, or the user has explicitly approved in conversation and the language was released via `approve-publish` (see "Human review gate" — never call `approve-publish` yourself just because a language reached `ready_for_review`); draft metadata, validate, `msv publishing upload`, then `set-stage --stage publishing --status completed --youtube-video-id ... --youtube-url ...` |

Because `analysis` covers every language in one deck-understanding pass,
treat it as a single unit of work the first time a run needs it — but
still record it per-language in state (so `rerun_language` can later
regenerate just one language's localization without repeating slide
analysis).

## Default-language-first production gate

`next_actions` never offers a non-default language's `translation` stage
until the run's `default_language` (`state.to_report()["default_language"]`,
normally `DEFAULT_LANGUAGE`) has finished `validation` **and** a human has
approved production for the run. This exists for the same reason it
exists in the video-source sibling project: a bug visible in one
language's render (narration pacing, caption formatting, a layout issue
where translated text overflows its slide) is almost always present in
every language's render — catching it after only the default language has
been produced, instead of after all N, is the whole point.

Practical effect on the run loop: the first pass of `next-actions` for a
fresh run will only ever return `{"language": default_language, "stage":
"translation"}` (plus every language's `analysis`, since that's ungated
and covers all languages at once) — no other language's `translation`
action appears until the gate opens. Dispatch that one action to
`slideshow-production-agent` directly, as normal. Once the default
language reaches `ready_for_review` or `completed`, report it to the
user/reviewer explicitly (video path, title, any pacing warnings) and
stop — do not proceed to other languages on your own initiative, and do
not dispatch `language-rollout-agent` speculatively "in case" approval is
about to happen. Resume once a human:
- sets `PIPELINE_AUTO_APPROVE_PRODUCTION=true` for all future runs, or
- calls `msv pipeline approve-production --run-id ...` to release every
  other language for this run.

Once approval lands (`report.production_approved: true`), dispatch
**`language-rollout-agent` once** — not a loop of
`slideshow-production-agent` calls yourself — and let it fan out to every
remaining language and report back one consolidated per-language result
(see the `multilingual_rollout` skill). This is the entire reason that
skill and agent exist: catching a systemic bug in one language's render
before it's repeated (and TTS-billed) across every other one is only
worth doing if the "produce everyone else" step is a single, deliberate,
gated action — not something that happens implicitly as a side effect of
looping `next-actions`.

`approve-production` fails cleanly (not a crash) if the default language
isn't at `ready_for_review`/`completed` yet — nothing to have reviewed.
Rerunning the default language from `analysis` or `translation` onward
(`rerun_language --language <default_language>`) automatically re-locks
this gate (`production_approved` resets), since whatever was reviewed no
longer exists — the next `language-rollout-agent` dispatch (if any is in
flight or attempted) will find the gate closed again and refuse.

## Human review gate

When `PIPELINE_AUTO_PUBLISH=false` (the default), `next_actions` never
offers a `publishing` job — languages sit at `ready_for_review` in
`msv pipeline status` once `validation` completes.

**This is a real conversational approval gate, not just a CLI flag
check.** When a run reaches this point, stop and explicitly ask the user
in the conversation whether to publish — do not call
`msv pipeline approve-publish` or dispatch `youtube-publishing-agent`
until they have actually said so in a reply. Report enough for them to
decide: which language(s) are ready, the rendered video path, the title,
and any pacing warnings from production — the same level of detail used
for the default-language-first production gate. Treat "ready_for_review"
in `msv pipeline status` as informational, not as license to proceed on
your own initiative; the CLI will happily let you call `approve-publish`
without ever having asked anyone, which is exactly the failure mode this
gate exists to prevent — a video going live because a state check passed,
not because a human actually agreed to publish it.

Once the user has explicitly approved (in this conversation, for this
run):
- call `publish_pending` (`msv pipeline approve-publish --run-id ... [--languages ...]`)
  to release the approved language(s) for this run, then dispatch
  `youtube-publishing-agent` for each; or
- if the user says they want this to stop requiring a per-run ask going
  forward, that's a `.env` change (`PIPELINE_AUTO_PUBLISH=true`) they make
  themselves or explicitly ask you to make — don't set it on their behalf
  as a shortcut to skip asking on a future run.

## Idempotency and artifact reuse

- `msv pipeline init` records a fingerprint of the source deck
  (`multilingual_slide_video_agent.state.directory_fingerprint`, hashed
  over every file's relative path/size/mtime under the deck directory —
  every `slide_NNN.html` plus shared `styles.css`/`assets/`);
  `validate_pipeline` warns if the deck on disk has since changed, so a
  stale resume doesn't silently mix artifacts from two different deck
  versions.
- Every stage's artifacts stay in `state/<run_id>/...` or
  `output/<run_id>/<language>/...`, keyed by run/language/stage — a
  completed stage is never redone by `next_actions` unless explicitly
  invalidated via `rerun_language`/`rerun_stage`.
- Changing only `metadata_<language>.json` and re-publishing does not
  require Agents 1-2 to run again: `rerun_stage --stage publishing` (or
  targeting one language) leaves `analysis`/`translation`/`rendering`/
  `tts`/`validation` untouched, and `msv publishing upload
  --existing-video-id` updates metadata without a reupload.
- Changing only one language's narration: `rerun_language --language zh-TW --from-stage analysis`
  resets just that language; `en-US`/`ja-JP` artifacts and state are
  untouched.
- Changing only the deck's translated HTML (a typo fix, not a narration
  change) does not require re-running TTS: `rerun_stage --stage rendering
  --language zh-TW` re-applies translations and re-screenshots without
  regenerating narration audio, as long as `--audio-dir` is passed
  pointing at the existing `segments/` clips.

## Validation criteria

`validate_pipeline` (`msv pipeline validate`) checks: source deck still
exists and is unchanged since the run started; no language has a stage
stuck `in_progress` from an interrupted process (safe to `rerun-stage`);
no stage has exhausted `PIPELINE_MAX_RETRIES` without being flagged.
Before advancing a language past a stage, Agent 4 also re-runs that
stage's own skill-level validation command (`msv slides validate`,
`msv production validate`, `msv publishing validate`) — this skill's job
is run-level consistency, not re-implementing per-stage checks.

## Error handling & retry behavior

- A failed stage is recorded via `set-stage --status failed --error ... --retry`
  (increments `retry_count`). Re-attempt the same stage up to
  `PIPELINE_MAX_RETRIES` (env, default 3) before leaving it `failed` and
  surfacing it in the report — do not silently skip a language.
- A stage's failure never touches earlier, already-`completed` stages for
  that language, and never touches other languages — `next_actions` keeps
  offering every language independently.
- If a Claude Code session is interrupted mid-run, the next
  `resume_pipeline` call picks up exactly where `state/<run_id>.json` left
  off; `validate_pipeline` flags any stage left `in_progress` so it can be
  rerun rather than assumed complete.

## Logging and observability

Every `msv` command appends structured JSON lines to `logs/<run_id>.jsonl`
via `multilingual_slide_video_agent/logging_utils.py` (run_id,
project_id, agent, skill, stage, language, timing, status, retry_count,
artifacts, warnings, errors). Secrets are redacted by key-name and by
pattern before a line is ever written — nothing in `.env` should ever
appear in `logs/`.

## Handoff / final report

`msv pipeline report --run-id <id>` (or the `report` field any other
command returns) is the final execution report:

```json
{
  "run_id": "run-20260818-001",
  "project_id": "product-launch-deck",
  "overall_status": "ready_for_review",
  "languages": {
    "en-US": {"status": "ready_for_review", "stages": {"...": "completed"}},
    "zh-TW": {"status": "ready_for_review", "stages": {"...": "completed"}},
    "ja-JP": {"status": "failed", "stages": {"translation": "failed", "...": "pending"}}
  }
}
```

This is what gets surfaced back to the user/external caller — always
report per-language status individually; never collapse a partial
failure into a single pass/fail for the whole run.
