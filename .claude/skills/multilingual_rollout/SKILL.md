---
name: multilingual-rollout
description: Rollout skill for a dedicated Language Rollout Agent. Once a run's default language has been produced and a human has approved production, fans out slideshow production to every other configured language by dispatching the slideshow_video_production skill (slideshow-production-agent) once per remaining language. Use only after the default-language-first production gate has actually opened - never to decide whether it should open.
---

# Multilingual Rollout Skill

## Purpose

Apply the already-approved production process to every language other
than a run's default language, in one dispatch instead of Agent 4 looping
through each language itself. This skill owns *fan-out*, not *approval* —
the decision that it's safe to proceed was already made once, at the
default-language-first production gate (`slide_video_orchestration`
skill); this skill's only job is to act on that decision efficiently and
consistently across every remaining language.

This exists as a separate skill/agent from `slideshow_video_production`
on purpose: that skill's job is "produce one language, correctly" and
should stay exactly that — simple, directly testable, reusable for a
single targeted rerun. This skill's job is "produce every language that's
now cleared to run," which is a coordination concern, not a rendering
one. Keeping them apart means a targeted single-language rerun (e.g.
`rerun_language --language zh-TW`) still goes straight to
slideshow-production-agent, while the bulk post-approval rollout goes
through here.

## Non-negotiable rule

**Never dispatch a non-default language's production without first
confirming, from `msv pipeline` state, that the gate is actually open**
(default language `ready_for_review`/`completed` **and**
`production_approved` true in the run's report). If invoked before the
gate opens — by mistake, or because a caller assumed approval that hasn't
happened — refuse and report why, rather than proceeding. Re-checking
this yourself (not just trusting the caller) matters for the same reason
it matters in the video-source project this pattern is reused from: the
whole point of the gate is catching a systemic rendering bug before it's
repeated (and TTS-billed) across every language, not just the default
one.

## Responsibilities

- Confirm the production-approval gate is open for the given run.
- Determine which non-default-language jobs are actually outstanding via
  `msv pipeline next-actions` (not by assuming "every other language" —
  some may already be `completed` from a prior partial rollout, and using
  `next-actions` means this skill automatically inherits the state
  machine's existing resume/retry/stage-ordering logic instead of
  reimplementing any of it).
- Dispatch `slideshow-production-agent` once per non-default language with
  outstanding work, in parallel, each following its own skill
  (`slideshow_video_production`) exactly as it would for any other
  invocation — including recording its own pipeline state.
- Never let one language's failure block or delay another's — dispatch
  independently, collect results independently.
- Return one consolidated report to Agent 4: per-language outcome.

## Required inputs

| Input | Description |
|---|---|
| `run_id`, `project_id` | From Agent 4's pipeline state |
| `source_deck` | Path to the clean original deck directory (same one registered for the run) |

## Available tools

- `msv pipeline status --run-id ...` — gate confirmation (`default_language`, `production_approved`, per-language status).
- `msv pipeline next-actions --run-id ...` — the authoritative list of outstanding jobs; filter to `language != default_language`.
- The Task tool, to dispatch `slideshow-production-agent` (see `.claude/agents/slideshow-production-agent.md` and `.claude/skills/slideshow_video_production/SKILL.md`) once per language with outstanding work. Do not reimplement rendering here — dispatch it.

## Execution procedure

1. `msv pipeline status --run-id <id>`. Confirm `report.default_language`
   is set and that language's status is `ready_for_review` or
   `completed`, and `report.production_approved` is `true`. If either is
   false, stop and report exactly which condition failed — do not
   proceed "just this once."
2. `msv pipeline next-actions --run-id <id>`. Group the returned actions
   by `language`, dropping any entry whose `language` equals
   `default_language` (that language's work is already handled elsewhere
   — by Agent 4 directly, before this skill is ever invoked).
3. If the filtered list is empty, report that there is nothing to roll
   out (every non-default language is already at or past its next stage)
   and stop — this is a normal, successful outcome, not an error.
4. For each remaining language, dispatch `slideshow-production-agent`
   (Task tool) with that language's `run_id`/`project_id`/`source_deck`
   and its `localization_<language>.json` path — the same inputs Agent 4
   would pass directly. Send all dispatches in one batch so they run
   concurrently rather than one at a time.
5. Wait for every dispatch to report back. Do not retry a failed one
   yourself — that's Agent 4's `PIPELINE_MAX_RETRIES` policy, applied on
   a later pass (including a later invocation of this same skill, which
   will pick the failed language back up via `next-actions` once Agent 4
   has decided to retry it).
6. Build the consolidated report (see "Handoff contract") and return it.

## Validation criteria

- The gate was confirmed open (step 1) before any dispatch happened —
  the single most important check this skill performs.
- Every language identified in step 2 has a definitive outcome in the
  final report (`completed` or `failed` with a reason) — none silently
  unaccounted for.
- No dispatched language's outcome is reported as `completed` unless the
  corresponding `slideshow-production-agent` invocation itself reported
  success (this skill does not mark anything completed on its own
  authority — it relays what actually happened).

## Error handling & retry behavior

- Gate not open: fail immediately with a clear message naming which
  condition wasn't met (default language not ready, or not approved).
  Do not dispatch anything.
- One language's `slideshow-production-agent` dispatch failing: record it
  as failed in the consolidated report; continue collecting the others
  normally. Do not abort the batch.
- This skill performs no retries of its own — a failed language stays
  `failed` in pipeline state (as recorded by `slideshow-production-agent`
  itself) until Agent 4 decides to retry it, whether by re-invoking this
  skill (which will pick it back up via `next-actions`, since a `failed`
  stage is not a terminal-ok status) or by dispatching
  `slideshow-production-agent` directly for just that one language.

## Handoff contract

Consolidated report back to Agent 4:

```json
{
  "agent": "language_rollout_agent",
  "run_id": "run-20260818-001",
  "default_language": "en-US",
  "status": "completed",
  "languages": {
    "es-ES": {"status": "completed"},
    "de-DE": {"status": "completed"},
    "fr-FR": {"status": "completed"},
    "ja-JP": {"status": "completed"},
    "ko-KR": {"status": "completed"},
    "zh-CN": {"status": "completed"},
    "zh-TW": {"status": "failed", "error": "TTS request timed out"}
  },
  "warnings": [],
  "errors": []
}
```

`status` at the top level is `completed` only if every language's status
is `completed`; otherwise `partially_failed`. Agent 4 reads this the same
way it reads any other stage outcome — per-language, never collapsed —
and surfaces `zh-TW` as needing a retry rather than treating the whole
rollout as failed.
