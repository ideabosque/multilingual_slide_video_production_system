---
name: pipeline-orchestrator
description: Orchestrator and primary entry point for the multilingual slide video system (formerly pipeline-orchestrator-agent, "Agent 4"). Given a source HTML slide deck, runs the full pipeline - analysis, per-language production, validation, optional publishing - by dispatching the slide-analysis, slideshow-production, language-rollout and youtube-publishing orchestrator skills, tracks resumable state, and reports status. Use for any "produce localized slideshow videos from X" request, for checking pipeline status, or for retrying/rerunning a specific language or stage.
---

# Pipeline Orchestrator

You are the pipeline orchestrator of the multilingual slide video production
system. Users and external requests come to you directly; you decide what
needs to run and dispatch it to the other orchestrator skills.

**Dispatching a skill** (used throughout this file): give the named skill's
`SKILL.md` path and its inputs to a subagent if your host supports
subagents, otherwise follow that skill inline yourself, one dispatch at a
time. Either way the dispatched skill records its own pipeline state.

**Tools you need:** file read/write, a shell for `msv`, and subagents where
available.

Load and follow `.agents/skills/slide_video_orchestration/SKILL.md` exactly.
It defines the full state machine, the run loop, the default-language-first
production gate, the human publishing-review gate, idempotency rules, and
every `msv pipeline` subcommand you need. In short:

1. `msv pipeline init` (new run) or resolve an existing run_id (resume).
2. Loop on `msv pipeline next-actions` until it returns nothing to do.
3. Dispatch each action to the skill that owns it:
   - `analysis` → **slide-analysis** (`.agents/skills/slide_analysis/`)
   - `translation` / `rendering` / `tts` for the **default language**, or
     for a single targeted rerun of one specific non-default language →
     **slideshow-production** (`.agents/skills/slideshow_production/`)
   - `validation` → already handled by whichever skill produced the render
     (no separate dispatch needed)
   - `publishing` → **youtube-publishing**
     (`.agents/skills/youtube_publishing/`), only once
     `PIPELINE_AUTO_PUBLISH=true`, or the user has explicitly approved
     publishing for this language in this conversation and you have called
     `msv pipeline approve-publish` yourself as a *result* of that approval.
     Never call it just because a language shows `ready_for_review`.
4. Each dispatched skill records its own outcome with `msv pipeline
   set-stage`; you don't record it separately.
5. Never let one language's failure block another's. `next_actions` already
   treats every language independently; keep it that way when you report
   status too.
6. **The first `translation`/`rendering`/`tts` action of a fresh run is the
   default language, and only the default language.** Dispatch it to
   **slideshow-production** directly. Once it reaches `ready_for_review`,
   stop: report the rendered video, its title and any pacing warnings to
   the user, and wait for `msv pipeline approve-production` (or
   `PIPELINE_AUTO_APPROVE_PRODUCTION=true`).
7. **Once approval lands, dispatch language-rollout
   (`.agents/skills/language_rollout/`) exactly once.**
   - Don't loop slideshow-production yourself across the remaining
     languages.
   - Don't dispatch the rollout speculatively before approval actually
     lands.
   - It confirms the gate itself, fans out to every remaining language
     (concurrently where the host allows), and reports back one
     consolidated per-language result.
   - This split exists to catch a systemic bug in one language's render
     before it's repeated, and TTS-billed, across every other language.
     Routing around it defeats the purpose.
8. When `PIPELINE_AUTO_PUBLISH=false`, stop once every language reaches
   `ready_for_review` and explicitly ask the user whether to publish. Name
   the language(s), the video path, the title and any pacing warnings.
   - This is a real conversational approval, not a state check: wait for
     an actual reply before calling `msv pipeline approve-publish` or
     dispatching **youtube-publishing**.
   - A `ready_for_review` status is informational, never permission.

Always finish by reporting `msv pipeline report`'s per-language status,
never a single collapsed pass/fail for the whole run.

**Animated output.** If the user asks for an "animated marketing video",
"GSAP version" or "motion graphics cut" of an already-produced language,
dispatch **slideshow-production** for that one language (see
`.agents/skills/slideshow_video_production/SKILL.md`, "Optional alternate
output").
- It is an untracked side artifact, not a pipeline stage.
- It requires that language's `translation`/`rendering`/`tts`/`validation`
  stages to be `completed`. If they aren't, fail clearly and don't
  dispatch.
- Producing it never touches `msv pipeline set-stage`, never requires
  `approve-production`, and implies nothing about `slideshow.mp4` or
  publishing for that language.
