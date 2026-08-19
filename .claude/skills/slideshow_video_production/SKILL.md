---
name: slideshow-video-production
description: Voice and slideshow production skill for Agent 2. Applies Agent 1's per-language slide translations back into the original English HTML deck, renders the translated deck to screenshots via headless Chromium, generates narration via OpenAI TTS, and assembles a publication-ready localized MP4 slideshow with FFmpeg. Use when producing, re-rendering, or re-recording narration/captions for one specific language of a slide deck.
---

# Slideshow Video Production Skill

Reference implementation source: adapted and generalized from the
`multilingual_video_production` skill in the sibling
`multilingual_demo_video_production_system` project, replacing
video-frame compositing with HTML-deck translation + browser rendering.

## Purpose

Convert Agent 1's structured, per-language localization output into the
final localized slideshow video: a translated HTML deck, rendered slide
images, narration audio, synchronized captions, and an assembled MP4 —
without ever touching a previously translated or rendered deck as the
base.

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
- If pre-generated per-slide narration audio is supplied
  (`--audio-dir`), reuse it instead of regenerating it (idempotency /
  cost control).

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
| `output_dir` | Where to write `slideshow.mp4`, `narration.mp3`, `captions.srt`, `production.json` |

Optional: `--audio-dir` (reuse pre-generated per-slide mp3s named
`<slide_id>.mp3`), `--no-burn-in` (soft-sub only). `render-slideshow`
itself takes no viewport option — the viewport used to screenshot
`slides_dir` (`msv slides render-images --viewport ...`, default
`1920x1080`) must simply match `VIDEO_RESOLUTION`'s width/height in
`config/video.yaml`, or the scale filter here will be doing real
resizing instead of a no-op (see `.env.example`'s `SLIDE_VIEWPORT`).

## Generated outputs

```
state/<run_id>/analysis/slides/
├── translated_<language>/slide_001.html   # msv slides apply-translations
└── rendered_<language>/slide_001.png      # msv slides render-images

output/<run_id>/<language>/
├── slideshow.mp4
├── narration.mp3        # full narration, concatenated in slide order
├── captions.srt
├── captions.ass         # only when burn_in is enabled
├── segments/*.mp3        # per-slide narration clips (reusable)
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
- `msv slides render-images --deck-dir <translated_<lang>_dir> --out <rendered_<lang>_dir> [--viewport 1920x1080]`
  — same Chromium screenshot tool Agent 1 uses, now against the
  translated deck; its output is the actual video frame source.
- `msv production render-slideshow --run-id ... --project-id ... --language ... --slides-dir ... --localization ... --output-dir ...`
  — the renderer described above.
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

1. Resolve `source_deck`. `msv slides apply-translations` always deletes
   and fully recreates `translated_<language>/` from the original deck
   before writing anything (`apply_translations.py`'s
   `shutil.rmtree`+`shutil.copytree`) — a leftover directory from a stale
   prior run is never partially reused or trusted, it's simply
   overwritten (see non-negotiable rules).
2. Load and validate the localization JSON
   (`multilingual_slide_video_agent.schemas.validate_localization`)
   against `slides/manifest.json` — this checks `title` is present, every
   `slide_translations` node ID resolves, and warns on overlong/duplicate
   captions.
3. Run the terminology check on every slide's narration, caption,
   translated text, and the title.
4. `msv slides apply-translations`, then `msv slides render-images` on
   the result.
5. For each slide: reuse or generate its narration clip; measure its
   real duration.
6. Compute each slide's on-screen duration
   (`narration_duration + pacing.slide_pause_seconds`) and resulting
   `start_time`/`end_time` in the assembled timeline (see "Slide duration
   is narration-driven").
7. Write `captions.srt` (always, including the title as its first cue)
   and `captions.ass` (if burn-in enabled — title in its own larger
   `Title` style, captions in `Default`, both auto-wrapping).
8. Render the final MP4 with `ffmpeg`: the title card held for a fixed
   duration, then each slide's PNG held for its computed duration with
   its narration audio, concatenated in slide order.
9. Concatenate segment clips into `narration.mp3` for reference/reuse.
10. Write `production.json` and print the status envelope.

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
