# AGENTS.md

Guidance for coding agents (Claude Code, Codex, Cursor, etc.) working in this
repository. `README.md` is the user-facing documentation; this file covers
how to change the code safely.

## What this project is

A Python CLI (`msv`) plus agent skills that turn one English HTML slide
deck into localized, narrated, captioned MP4s and optionally publish them to
YouTube. The split is deliberate:

- **Judgement lives in the skills** (`.agents/skills/`): reading slides,
  translating, writing narration and captions, and drafting YouTube
  metadata. No Python code calls an LLM; the only model call is OpenAI TTS
  in `production/render_slideshow.py`.
- **The mechanical work lives in the CLI** (`src/multilingual_slide_video_agent/`):
  text extraction, Chromium rendering, TTS, FFmpeg assembly, YouTube upload,
  and pipeline state.

## Layout

```
src/multilingual_slide_video_agent/
  cli.py                 msv entry point (slides / production / motion / publishing / pipeline)
  state.py               per-run pipeline state machine (state/<run_id>.json)
  slides/                node-ID text extraction, translation, Chromium rendering,
                         animation bundle (assets/animation_runtime.js, vendor/gsap.min.js)
  production/            render_slideshow.py (narrate_language = stage tts; render_language =
                         static fallback), captions.py, motion/ (stage rendering: the
                         animated video - clips.py's shared clip plan, the hyperframes and
                         remotion engines, post-pass, validation)
  slides/motion_design.py  the motion-design/v1 language: validator, steps, transitions
  slides/motion_checks.py  validate-motion guardrails and the per-slide render fallback
  slides/layout_map.py     inspect-layout: targetable elements, groups, SVG shapes, roles
  publishing/            YouTube upload / OAuth
config/                  languages, terminology, video, motion, design system, animation templates
.agents/skills/          all skills: 6 orchestrator skills + the procedure skills they follow
docs/                    development plans; the active one is motion-engines-and-hardening-plan.md
motion/                  pinned Node toolchain for the HyperFrames/Remotion engines
tests/                   pytest suite
state/ output/ logs/     runtime data (gitignored)
```

## Skills

Every skill lives in `.agents/skills/<dir>/SKILL.md`, a tool-neutral
location. There are no Claude Code subagent definitions (`.claude/agents/`);
the former agents are now orchestrator skills.

| Orchestrator skill (entry point, role + dispatch) | Procedure skill it follows |
|---|---|
| `pipeline_orchestrator` (start here for a full run) | `slide_video_orchestration` |
| `slide_analysis` | `slide_deck_localization` |
| `slideshow_production` | `slideshow_video_production` |
| `language_rollout` | `multilingual_rollout` |
| `youtube_publishing` | `youtube_video_publishing` |
| `motion_design` (custom per-deck motion + its approval gate) | `deck_motion_design` |

`gsap_animation_authoring` and `motion_design_principles` are loaded only
for template-library maintenance (see `slideshow_production`).

- **Dispatching a skill**, as orchestrator skills describe it, means
  running it in a subagent when the host supports subagents (pass the
  skill's `SKILL.md` path and its inputs), otherwise inline.
- Keep a role's guardrails (approval gates, one language per production
  run) in its orchestrator skill and the step-by-step procedure in the
  procedure skill.
- Python status envelopes and logs still name the roles
  `slideshow_production_agent` etc. Those are data identifiers, not file
  references; don't rename them.

## Setup and commands

```bash
python -m venv .venv && .venv\Scripts\activate      # source .venv/bin/activate on macOS/Linux
pip install -e ".[dev]"
playwright install chromium
msv motion install                                  # only needed for the Node-based motion engines
```

- External tools: `ffmpeg`/`ffprobe` on PATH, and Node 22+ for the motion
  engines (`msv motion doctor` reports what's missing).
- Run the tests with `.venv/Scripts/python -m pytest -q`. Tests that need a
  tool are marked `requires_ffmpeg`, `requires_browser` or `requires_node`,
  and `tests/conftest.py` skips them when the tool is absent. A full run with
  everything installed takes about a minute.
- Directories resolve from `MSV_ROOT_DIR` (default: current directory). Tests
  isolate themselves with `MSV_STATE_DIR` and `MSV_LOGS_DIR`; new tests that
  touch state or logs must do the same.

## Conventions that matter here

**CLI**
- Every `msv` command prints exactly one JSON object and exits 0/1. Failures
  are `{"ok": false, "errors": [...]}`, not tracebacks. Agents parse this
  output.
- Fail loudly and name the slide. A silently wrong video is the worst
  outcome here, because nothing in the output reveals it without
  frame-by-frame review. Prefer raising with the slide id over skipping or
  defaulting.

**Pipeline state**
- Mutate run state only through `PipelineState.transaction(run_id)`, never a
  bare `load()`/`save()`. Language rollout runs in parallel, and the unlocked
  pattern loses updates.
- Any rerun of a language withdraws its publish approval
  (`invalidate_from`). A changed video or changed metadata always needs a
  fresh human review before publishing; don't carry an old approval over.
- Never translate from an already-translated deck. Translations apply by
  node ID onto a fresh copy of the original deck, and `source_deck_fingerprint`
  (content-based, `FINGERPRINT_ALGO`) guards this.

**Rendering**
- Text written into ffmpeg/libass inputs goes through
  `production/captions.py`: `ass_escape()` for caption text and
  `concat_quote()` for concat-list paths. Don't hand-escape.
- Don't modify a translated deck in place for rendering or analysis. Inject
  animation assets into a scratch copy or a separate project, as
  `extract_deck_roles` and the HyperFrames engine do.

**Motion engines**
- Each engine returns an exact-length silent video, and `motion/post.py`
  adds narration and captions. Keep audio and captions out of the engines.
- Segment boundaries are whole frames rounded from the absolute timeline
  (`segment_frame_counts`). Don't encode segments by seconds.
- Both engines (`hyperframes`, `remotion`) build from one clip plan,
  `production/motion/clips.py`: boundaries, a motion design's steps, and
  transition overlaps. Change timing there, not in one engine. Transitions
  overlap neighbouring clips by equal halves, so no boundary moves.
- Remotion renders with the chrome-headless-shell `msv motion install`
  downloads, passed explicitly so a render never downloads anything. It is
  the default engine (`config/motion.yaml`), by the user's decision of
  2026-10-22 (D1): it renders the deck's own fonts. Don't change the
  default without the user. License: free for individuals and companies
  of up to 3 people.
- HyperFrames substitutes system and generic fonts with its bundled ones
  and queries Google Fonts for other families while rendering. A
  cross-engine comparison must use embedded fonts, or it measures fonts,
  not motion.
- Validation (`motion/validate.py`) checks each slide's own first and last
  frames. Don't relax a threshold to make a render pass without
  understanding why it failed; look at the frames first.

**Animation runtime** (`slides/assets/animation_runtime.js`)
- Effects must render correctly when the timeline is seeked, not just
  played. Write DOM from tweened-property setters, never from `onUpdate`,
  because `seek()` suppresses callbacks. Avoid wall-clock time and
  randomness. See `.agents/skills/gsap_animation_authoring/SKILL.md`.
- Templates are declarative data in `config/animation_templates.yaml`.
  Adding or tuning a template is a YAML change, not a JS change.
- Motion designs (`motion-design/v1`) are played by the same step runner.
  The templates are their presets and must keep rendering identically
  whether named or expanded into steps (a test checks all of them). Design
  steps fail loudly on a target that matches nothing; template steps skip.

**Animation bundles**
- A run's animation bundle (`generate-animation` output) supplies per-deck
  data only: `spec.json`, `templates_config.js` and `design_tokens.css`.
  Runtime code (`animation_runtime.js`, `gsap.min.js`) is always injected
  from the installed package, because old bundles carry stale copies.

**Node toolchain** (`motion/`)
- Exact version pins only, with the committed `package-lock.json`.
  Install via `msv motion install` (`npm ci`). Never `npx <pkg>` at render
  time.
- HyperFrames collects telemetry by default. Every `hyperframes` invocation
  must run with `HYPERFRAMES_NO_TELEMETRY=1` and `DO_NOT_TRACK=1` in its
  environment. Don't run `hyperframes telemetry …`, which changes the user's
  global settings.
- HyperFrames composition rules (from the Phase 2a spike, plan B4): asset
  paths are root-relative, `<style>`/`<script>` go inside the sub-composition
  `<template>`, and scripts share one document, so scope DOM queries to the
  slide's root.

## Working on the plan

`docs/motion-engines-and-hardening-plan.md` is the source of truth for the
current phased work: HyperFrames and Remotion engines, then Claude-designed
per-deck motion. Its status block says what is built.

- Check the plan before starting a phase.
- Record any deviation from the plan in that status block.
- Open decisions (D1–D7) have recorded defaults. Don't re-decide them; raise
  a change with the user.

## Things not to do

- Don't call an LLM from the Python package. Judgement belongs in the
  skills and agents.
- Don't publish to YouTube, change OAuth credentials, or run
  `msv publishing upload` without explicit user approval. Publishing is
  outward-facing.
- Don't commit `.env`, client-secret JSON files, or anything under `state/`,
  `output/` or `logs/`.
- Production is animation-first (plan Part D): a language's video is the
  animated render, produced in one pass (`narrate` then `render-motion`).
  Don't reintroduce a static-video-first step, and keep both review gates
  (default language first, approval before publishing). Landed elements
  hold still: no continuous bobbing or elastic wobble in the playful
  style (feedback: it read as shaking).
