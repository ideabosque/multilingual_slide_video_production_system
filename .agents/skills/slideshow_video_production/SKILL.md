---
name: slideshow-video-production
description: Video production procedure for Agent 2 (followed by the slideshow-production orchestrator skill). Applies Agent 1's per-language slide translations back into the original English HTML deck, narrates it via OpenAI TTS, and renders the language's animated video in one pass with HyperFrames (playful GSAP motion, burned-in captions, narration). Use when producing, re-rendering, or re-recording narration/captions for one specific language of a slide deck.
---

# Slideshow Video Production Skill

Reference implementation source: adapted and generalized from the
`multilingual_video_production` skill in the sibling
`multilingual_demo_video_production_system` project, replacing
video-frame compositing with HTML-deck translation + browser rendering.

## Purpose

Convert Agent 1's structured, per-language localization output into the
final localized video: a translated HTML deck, narration audio,
synchronized captions, and an **animated** MP4 rendered in one pass —
without ever touching a previously translated or rendered deck as the
base.

**Animation-first (since 2026-10-22, plan Part D).** The language's video
is the animated render: `msv production narrate` (stage `tts`) then
`msv production render-motion` (stage `rendering`). There is no static
slideshow pass first. `msv production render-slideshow` (static slide
images held for their narration) remains only as a fallback, used when
the user explicitly asks for a static video or the motion engine is
unavailable. The review gates are unchanged: the default language is
reviewed before the other languages render, and nothing publishes
without approval.

## Non-negotiable rules

- Always apply translations onto the **original clean source deck**
  (`source_deck`), never onto a previously translated deck for this or
  any other language — every language's translated HTML is generated
  fresh from Agent 1's `slide_translations`, applied directly to the
  original deck's node IDs.
- Never render video frames from anything but the deck just produced by
  `msv slides apply-translations` for this run/language — never reuse
  another language's `rendered_<language>/` PNGs, and never layer new
  captions over an already-captioned slide image.
- Preserve terminology from `config/terminology.yaml` (product names,
  acronyms) — checked before any TTS spend (Agent 1 already tagged and
  checked this at the text level; re-verify via `msv slides validate` or
  equivalent before spending, since this is the last checkpoint before
  cost is incurred).
- Narration clips are cached per slide and reused only while still
  correct (idempotency / cost control).
  - Each `segments/<slide_id>.mp3` has a sidecar `<slide_id>.json` with a
    hash of narration text, voice, model and instructions. A mismatch
    regenerates the clip.
  - A clip without a sidecar predates this cache. In the default
    `segments/` folder it is regenerated once; in an explicitly supplied
    `--audio-dir` it is trusted as pre-generated audio.

## Responsibilities

- Receive the original source deck and Agent 1's
  `localization_<language>.json`.
- Apply that language's `slide_translations` back into the original
  deck's HTML, by node ID, preserving the original CSS/layout/design —
  never re-authoring markup, only replacing translatable text content.
- Render the translated deck to PNG screenshots via headless Chromium, at
  a fixed viewport size, one image per slide.
- Generate natural-sounding narration per slide via OpenAI TTS.
- Compute each slide's **on-screen duration from its own narration's
  actual length** plus a short fixed pause — there is no pre-existing
  timeline to anchor against or overrun (see "Slide duration is
  narration-driven" below); this is the single biggest structural
  difference from the video-source project's renderer.
- Burn in a **marketing title card** (from `localization.title`) as its
  own leading segment, distinct from per-slide captions.
- Generate a `.srt` subtitle sidecar for every render, and burn in
  auto-wrapped, localized captions when `captions.burn_in` is enabled.
- Render a single H.264/AAC MP4 with `+faststart`, concatenating the
  title card and every slide's image (held for its computed duration)
  with its narration audio.
- Validate slide coverage and caption presence before reporting success.
- Return a standard status envelope to Agent 4.

### Slide duration is narration-driven

Unlike the video-source project, there is no original recording whose
timeline narration must be anchored to, overrun, or pad against. Each
slide's on-screen duration is simply
`narration_duration_seconds + config/video.yaml: pacing.slide_pause_seconds`
(a short fixed pause, e.g. 0.5s, so consecutive slides don't feel
clipped). This makes the old video project's "non-overlapping narration"/
drift-tracking machinery unnecessary here — there's nothing to drift
*from*. `production.json.segment_timing` still records each slide's
actual `start_time`/`end_time` in the assembled output (useful for
captions/QA), but those are a **result** of concatenation, not a
constraint the renderer has to reconcile narration against.

### Caption wrapping

`config/video.yaml: captions.wrap_style` must stay `0` (smart auto-wrap)
— same rule and same reasoning as the video-source project: a caption
wider than the frame should break onto a second line, not overflow off
both edges. Combined with Agent 1 writing short highlight-style captions
(see that skill's "Caption vs narration"), wrapping should rarely even be
needed in practice, but the renderer must never depend on that being
true.

### Burn-in requires CFR (constant frame rate)

The silent slide video is built from one PNG per slide held for its
computed duration, via ffmpeg's `concat` image demuxer. When captions
are burned in (`captions.burn_in: true`, the default), the libass
subtitle filter is applied to that video stream. **The silent video must
be rendered at a constant frame rate (`-fps_mode cfr -r <fps>`), never
VFR (`-vsync vfr`).** With VFR, the ASS filter's output timestamps don't
align with the concat demuxer's VFR timing, and ffmpeg silently drops
most slide frames — observed failure mode: a 14-image deck produced a
202s / 10-frame video instead of 345s / ~1700 frames, with no ffmpeg
error (exit 0). CFR renders every slide image at `render.fps` (default
5, in `config/video.yaml`) for its full duration before the subtitle
filter runs, so no frames are dropped.

**5fps is the right default for this deck shape.** Every slide is a
static image held for its narration duration, and burned-in captions are
static text — nothing on screen animates, so a low fps cuts file size
roughly 5x (and encoding time with it) with no perceptible quality loss.
A 345s deck at 5fps is ~1700 frames / ~3 MB instead of 8633 frames /
14 MB at 25fps, and encodes proportionally faster. Do not raise this
back to 25/30fps "for smoothness" — there is no motion to smooth. Bump
`render.fps` only if a future deck style adds genuine per-frame motion
(fades, transitions, animated diagrams); verify the bumped render's
frame count and duration against `production.json.segment_timing` after
any change to this path. Do not reintroduce `-vsync vfr` here at any fps.

## Required inputs

| Input | Description |
|---|---|
| `run_id`, `project_id` | From Agent 4's pipeline state |
| `language` | Target language code, must exist in `config/languages.yaml` |
| `source_deck` | Path to the clean original deck directory |
| `localization` | Path to Agent 1's `localization_<language>.json` |
| `output_dir` | Where to write `video.mp4`, `narration.mp3`, `captions.srt`, `production.json` |
| animation bundle | `state/<run_id>/analysis/slides/animation` (`msv slides generate-animation`, once per deck) |

Optional: `--audio-dir` (reuse pre-generated per-slide mp3s named
`<slide_id>.mp3`). For the static fallback only: `--no-burn-in` (soft-sub
only), and `render-slideshow` takes no viewport option — the viewport used to screenshot
`slides_dir` (`msv slides render-images --viewport ...`, default
`1920x1080`) must simply match `VIDEO_RESOLUTION`'s width/height in
`config/video.yaml`, or the scale filter here will be doing real
resizing instead of a no-op (see `.env.example`'s `SLIDE_VIEWPORT`).

## Generated outputs

```
state/<run_id>/analysis/slides/
├── translated_<language>/slide_001.html   # msv slides apply-translations
├── animation/                             # msv slides generate-animation (once per deck)
└── rendered_<language>/slide_001.png      # static fallback only (msv slides render-images)

output/<run_id>/<language>/
├── video.mp4            # the animated video (render-motion) - what gets published
├── video.motion.json    # engine, style, per-slide timing, validation record
├── video_captions.srt
├── narration.mp3        # full narration, concatenated in slide order
├── captions.srt
├── slideshow.mp4        # static fallback only (render-slideshow)
├── captions.ass         # static fallback only, when burn_in is enabled
├── segments/*.mp3        # per-slide narration clips (reusable)
├── segments/*.json       # per-clip cache key sidecars (narration/voice/model/instructions hash)
└── production.json
```

`production.json` matches
`multilingual_slide_video_agent.schemas.validate_production_result` and
includes `source_deck_fingerprint` for Agent 2/4's idempotency and
"not-built-on-a-derivative" checks, plus `title` (rendered as the title
card) and `segment_timing` (each slide's resulting `start_time`/
`end_time`/`duration_seconds` in the assembled output).

## Available tools

The `msv` CLI, groups `msv slides` and `msv production`:

- `msv slides apply-translations --deck-dir <original_deck_dir> --localization <localization_<lang>.json> --out <translated_<lang>_dir>`
  — applies `slide_translations` back into the original HTML by node ID;
  fails loudly if a node ID in the localization file doesn't exist in the
  deck (structure changed since Agent 1 analyzed it).
- `msv production narrate --run-id ... --project-id ... --language ... --source-deck ... --localization ... --output-dir ...`
  — stage `tts`: narration, timing, captions, production.json (no video).
- `msv production render-motion --production ... --translated-deck-dir ... --animation-dir ... --localization ... [--engine hyperframes|remotion] [--motion-design ...]`
  — stage `rendering`: the animated video, recorded in production.json.
- `msv motion doctor` — checks Node, both engines, ffmpeg and Chromium.
- Static fallback: `msv slides render-images --deck-dir <translated_<lang>_dir> --out <rendered_<lang>_dir>`
  then `msv production render-slideshow --run-id ... --project-id ... --language ... --slides-dir ... --localization ... --output-dir ...`.
- `msv production validate --production output/<run_id>/<language>/production.json [--localization ...] [--run-id ...]`
  — post-render validation.
- OpenAI TTS API (`OPENAI_API_KEY`, `TTS_MODEL`/`config/languages.yaml`
  per-language `voice`).
- `ffmpeg`/`ffprobe` on `PATH`.

## Configuration

Environment (`.env`): `OPENAI_API_KEY`, `TTS_MODEL` (falls back to
`config/languages.yaml: default_tts.model`), `VIDEO_OUTPUT_FORMAT`,
`VIDEO_RESOLUTION`.

Files: `config/languages.yaml` (per-language voice/instructions),
`config/video.yaml` (render/audio/caption/pacing settings, including
`pacing.slide_pause_seconds`), `config/terminology.yaml` (preserved
terms, pronunciation hints).

## Execution procedure

One language per run. Stages in order: `translation` → `tts` → `rendering`
→ `validation`. Record each one with `msv pipeline set-stage`.

1. **`translation`:** `msv slides apply-translations --deck-dir <original>
   --localization <localization_<lang>.json> --out
   state/<run_id>/analysis/slides/translated_<lang>`. It always deletes and
   fully recreates `translated_<lang>/` from the original deck, so a
   leftover directory from a stale run is never partially reused (see
   non-negotiable rules).
2. **`tts`:** `msv production narrate --run-id ... --project-id ...
   --language <lang> --source-deck <original> --localization ...
   --output-dir output/<run_id>/<lang>`. It:
   - validates the localization and checks terminology on every
     narration, caption and the title, before any TTS spend;
   - reuses or generates each slide's narration clip (cached per slide by
     a hash of narration, voice, model and instructions);
   - lays out the narration-driven timeline (title card, then each slide
     for its narration plus `pacing.slide_pause_seconds`);
   - writes `captions.srt`, `narration.mp3` and `production.json` (with
     `output_video: null`). No video yet.
3. **`rendering`:** `msv production render-motion --production
   output/<run_id>/<lang>/production.json --translated-deck-dir
   state/<run_id>/analysis/slides/translated_<lang> --animation-dir
   state/<run_id>/analysis/slides/animation --localization ...`.
   - It uses the engine and style in `config/motion.yaml`: HyperFrames,
     playful. The animation bundle comes from `msv slides
     generate-animation`, run once per deck (see below).
   - `--engine remotion` renders the same animation with Remotion. Use it
     only when the user asks for it. It keeps the deck's own fonts, where
     HyperFrames substitutes its bundled ones. Remotion's free license
     covers individuals and companies of up to 3 people.
   - `--motion-design <motion_design.json>` plays the deck's motion design
     (schema `motion-design/v1`) instead of each slide's template. Pass
     it only when the user supplied one or asked for it; this skill does
     not write designs. Render every language from the same file. A
     design that is broken as a whole (header, wrong deck) fails before
     rendering: report the errors and stop. A slide whose design fails
     in this language plays its preset instead; report the envelope's
     fallback warnings with the result. Don't edit the design to make it
     pass.
   - Each slide animates for exactly its narration-driven duration; the
     title card is slide 1's own markup, blurred, behind the title.
   - Captions are burned in, the narration is muxed, and validation runs:
     exact length, no flash frames, and every slide visibly animates.
   - It writes `video.mp4` plus `video.motion.json`, and records the video
     in `production.json` (`output_video`, `video_kind: animated`,
     `duration_check_ok`).
4. **`validation`:** `msv production validate --production
   output/<run_id>/<lang>/production.json`.
5. Print the status envelope, including any pacing warnings.

**Animation bundle (once per deck):** `msv slides generate-animation
--deck-dir <original> --out state/<run_id>/analysis/slides/animation
[--slide-analysis ...]`. It assigns each slide a template (Agent 1's
`visual_role`, otherwise a deterministic heuristic). Reuse an existing
bundle that still matches the deck. The motion *style* is not in the
bundle: it comes from `config/motion.yaml` at render time.

**Static fallback** (only on explicit request, or when `msv motion doctor`
shows the engine unavailable): `msv slides render-images` on the translated
deck, then `msv production render-slideshow ... --slides-dir
<rendered_<lang>/>`. It writes `slideshow.mp4` and records it in
`production.json`.

## Validation criteria (enforced by `msv production validate`)

- `narration_audio`, `captions`, `output_video` all exist on disk.
- The output video is playable (`ffprobe` succeeds).
- Output duration matches the sum of the title card duration and every
  slide's computed duration, within a small tolerance.
- Every slide from the localization input appears in the rendered
  output's segment list (nothing silently dropped).
- `source_deck_fingerprint` in `production.json` matches the run's
  registered source deck in `state/<run_id>.json` — the concrete check
  for "not built on a previously translated derivative."
- Slide order in the output matches `slide_index` order from the
  localization input.

## Error handling & retry behavior

- Missing `OPENAI_API_KEY` or unsupported language: fail fast before any
  rendering work, with a clear error in the status envelope's `errors`.
- Terminology violations: fail before spending on TTS.
- A node ID in `slide_translations` that no longer resolves against the
  deck's current manifest (deck structure changed since Agent 1's
  analysis): fail loudly and name the missing node — do not guess which
  element it meant, and do not silently skip the slide.
- An individual slide's narration running dramatically longer than every
  other slide's: warns by default (recorded in
  `production.json.pacing_warnings`) rather than failing — see the
  `slide_deck_localization` skill's "Narration pacing" for the intended
  fix (usually splitting the source slide, not trimming narration here).
- `ffmpeg` failures propagate as a non-zero exit; Agent 4 should retry up
  to `PIPELINE_MAX_RETRIES` (env) before marking the `rendering` stage
  `failed` in pipeline state.
- Because each slide's narration clip and rendered image are
  content-addressed under `output_dir`/`state/<run_id>/analysis/slides/`,
  a retry after a transient TTS/ffmpeg failure reuses whatever already
  exists rather than regenerating everything.

## Render failures

A slide's script error fails the render loudly (HyperFrames' `check` runs
first) and names the slide. That's deliberately not a soft warning: a
silently broken animation (e.g. a selector that never matches) isn't
visible from the output file without frame-by-frame review.

## Handoff contract

On success, emits:

```json
{
  "agent": "slideshow_production_agent",
  "run_id": "run-20260818-001",
  "language": "zh-TW",
  "status": "completed",
  "outputs": { "...production.json fields..." },
  "warnings": [],
  "errors": []
}
```

Agent 4 records this in `state/<run_id>.json` under
`languages.<language>.stages.translation`, `.rendering`, and `.tts`, runs
`msv production validate`, and only then makes the `validation` stage
`completed` and becomes eligible to invoke Agent 3 for that language.
