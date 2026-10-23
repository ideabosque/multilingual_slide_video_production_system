# Motion Engines (HyperFrames + Remotion) and Pipeline Hardening — Development Plan

Status: **Phases 0 and 1 implemented** (Phase 0 committed on
`feature/phase0-hardening`; Phase 1, the engine seam, on
`feature/phase1-engine-seam`, including the review fixes below). **Phase 2a
(HyperFrames spike) done; results are in B4.** **Phase 2b (HyperFrames engine) built:** per-slide runtime entry points,
`hyperframes_engine.py`, `render-motion --engine hyperframes`. The 14-slide
reference deck renders cleanly (frame-exact, every slide passes, about real
time). **Direction changed 2026-10-22: animation-first, playful style (Part
D).** D1 (the playful style) is built, tuned more energetic, then calmed so
landed objects don't shake (no ambient float, no elastic wobble). D2
(one-pass production) is built: `msv production narrate` (tts), then
`render-motion` (rendering) records the animated `video.mp4` in
production.json; stage order is now tts before rendering; HyperFrames'
title card is animated from slide 1's markup; skills and README updated.
Both review gates are unchanged (requested 2026-10-22). Verified on the
full real deck in English (14 slides, 9:57, validation passing, narration on
every slide - a first run was silent because the render didn't know where
`--audio-dir` clips were; fixed by recording `segment_audio_dir` and failing
on a missing clip, plus a new audio check in validation).

**Also done 2026-10-22:**
- any rerun withdraws publish approval;
- `CLAUDE.md` imports `AGENTS.md`;
- the playful stat template no longer gives number-less slides a plain
  headline;
- **the Playwright live-capture engine is retired** (Phase 8's first item):
  live capture, the capture sentinel, lead-in detection,
  `render-marketing-animation` and their tests are removed. The generic
  exact-frame assembly moved to `production/motion/assembly.py`. HyperFrames
  is the only animated engine; the static slideshow remains the fallback.

**Phases 3 and 4 built (2026-10-22, done together at the user's request;
branch `feature/remotion-and-motion-language`).**

- **Phase 3, Remotion (deck-faithful mode, B5):** `motion/remotion/` (one
  `Slideshow` composition; each clip is the translated page in an iframe
  whose paused timeline is seeked to `frame / fps`) and
  `remotion_engine.py`. Pinned remotion 4.0.534 and react 19.3.0.
  `msv motion install` also downloads Remotion's chrome-headless-shell, and
  renders pass it explicitly, so they download nothing.
  - Reference deck, en-US: 14 slides, 9:57 rendered in 6:06, validation
    passing on every slide. For comparison, HyperFrames took 13:28 for the
    zh-TW render of the same deck.
  - Frame parity with HyperFrames: under 0.2% of pixels on the fixture
    deck, mid-transition included, **once both use the same fonts**. On
    the real deck they differ by 2-13% of pixels because of fonts (next
    item).
- **Finding: HyperFrames substitutes fonts.** On every render, HyperFrames
  0.8.140 rewrites system and generic font families to its bundled ones
  (Georgia becomes EB Garamond, Arial becomes Inter, `sans-serif` becomes
  `Inter, sans-serif`). It also looks up any other family on Google Fonts,
  sending the page's unique characters as a subsetting `text=` parameter.
  There is no switch for either. So HyperFrames' videos don't match the
  deck where it uses system fonts: the reference deck's Georgia headlines
  render lighter and smaller. Remotion renders the deck's fonts as
  Chromium does. **D1 decided by the user on 2026-10-22: `remotion` is the
  default engine** (`config/motion.yaml`). HyperFrames stays available with
  `--engine hyperframes`.
- **Phase 4, the motion language and interpreter (C3):**
  `slides/motion_design.py` (validator, resolution into runtime steps,
  transition planning, generated JSON Schema) and the runtime interpreter.
  - New seek-safe effects: `text_split` (word, char, line), `draw_svg`,
    `highlight` (sweep or colour, brand tokens only), `emphasis` (capped
    pulse), `path_connect` (arrow between two targets), `camera` (push-in
    or pan, scale ≤ 1.08) and a `reveal` blur.
  - Targets: `node`, `group`, `selector` and `role`. Both engines tag text
    elements with their extract-text node ids (`data-motion-node`).
  - Design step ids become timeline labels.
  - Transitions: crossfade, push and wipe.
  - `render-motion --motion-design`. Both engines build from one clip plan
    (`production/motion/clips.py`).
  - The 8 templates are the presets. A test checks every preset, in both
    styles, renders identically by name or as explicit steps.
  - Every new effect passes a seek-order test.
  - Exit sample: a hand-written design renders in both engines (fixture
    test). `docs/examples/motion_design.food-manufacturing.json` is a
    worked example for the reference deck. Rendered with Remotion, it
    passes validation in en-US (9:57, in 6:24) and zh-TW (11:27, in 7:09);
    every node target lands on the matching translated element.
  - Tests: 139 → 201.
- **Deviations from C3/B5 as written:**
  - Transitions don't use `@remotion/transitions` or
    `@hyperframes/shader-transitions`. Both engines play the same three
    DOM transitions from one plan. The incoming clip starts d/2 early and
    the outgoing one runs d/2 late, so every boundary and the total length
    stay put. A `TransitionSeries` would shorten the timeline instead.
  - SplitText and DrawSVG are not vendored. `text_split` and `draw_svg` are
    small seek-safe implementations: word spans grouped by laid-out line,
    and `stroke-dashoffset`.
  - `overlay` (React overlays) is not in v1. It needs the React component
    work deferred with D4.
  - Template `position` strings keep GSAP's own meaning, where an unknown
    label lands at the timeline's end, so presets render as before. Only
    design steps get labels.
  - The design's `deck_fingerprint` is required but not yet compared with
    the deck. That check is C5 #2, in Phase 5 with the other guardrails.
  - Remotion doesn't use `roles_<lang>.json`; the deck-faithful mode needs
    none. B5's template-name parity test and B8's
    `remotion_template_authoring` skill both maintain the D4 React
    templates, so they are deferred with them.
- **Fixed on the way:**
  - In a standalone page (Remotion's iframes) the camera zoomed around
    `<body>`'s centre, which is only as tall as its content, instead of
    the frame's.
  - A slide's script error now names the slide in both engines.
  - A missing bundle file, or a deck with no slides, now fails naming it.
  - Retiring the Playwright engine had removed `msv slides render`'s
    `json` import (fixed on the PR branch too).

**Phase 5 built (2026-10-22): layout map and guardrails (C4, C5).**

- `msv slides inspect-layout --deck-dir … --out layout_map.json
  [--annotate-dir …]` (`slides/layout_map.py`). Per slide it records:
  - text elements, with node ids, box, font size, colour and a number;
  - repeated sibling groups, each with a selector that matches exactly
    that group;
  - SVG shapes with their stroke lengths;
  - the runtime's resolved roles.

  The annotated screenshots number the elements and outline the groups.
  The deck itself is never modified.
- `msv slides validate-motion --design … --deck-dir … [--layout-map …]
  [--production …]…` (`slides/motion_checks.py`) checks:
  - schema;
  - targets: nodes, groups and selectors against the node-tagged deck
    HTML; roles against the layout map;
  - the deck fingerprint (content-v1);
  - brand colour tokens;
  - at most 3 flashes (`emphasis`/`highlight`) per second;
  - at most 6 elements moving at once;
  - the entrance settles within 40% of the shortest slide duration across
    the given languages;
  - no step after the slide's end, and beat steps fit before it.

  Every problem names the slide and step.
- Per-slide fallback at render time: `render-motion --motion-design` runs
  the same checks against that language's translated deck, timing and
  source fingerprint. A slide that fails plays its preset in that language
  only; the envelope's warnings and the manifest's `motion_design.fallback`
  name it. A broken design header or fingerprint fails the render.
- Exit criteria met by tests: bad target, bounce ease, 5 flashes per
  second and a beat past the end are each rejected with a slide-named
  error, and an end-to-end render falls back for one slide and passes
  validation. Tests: 201 → 222.
- The worked example passes every check against the real deck in en-US
  and zh-TW. Writing it had used the run state's legacy mtime fingerprint;
  the new fingerprint check caught that, and the example now carries the
  content-v1 value.
- **Deviations:**
  - A "flash" is any `emphasis` or `highlight` start; there is no
    luminance analysis.
  - The timing model mirrors the runtime's default durations and
    staggers, and counts a `text_split` block as one moving element.
  - Without a layout map, render-time checks skip role targets. A role
    that resolves to nothing still fails the render loudly, naming the
    step.

**Phase 6 built (2026-10-23): motion design skills and the approval gate
(C2, C6, C7).**

- Skills: the `motion_design` orchestrator (role, approval gate, never
  self-approves) and the `deck_motion_design` procedure:
  1. inspect-layout;
  2. `msv motion schema` as the language reference;
  3. write the design;
  4. validate-motion;
  5. preview, then inspect the filmstrip;
  6. at most 3 rounds, logged in `motion_design.review.md`;
  7. per-language check;
  8. register-motion and hand over.

  `pipeline_orchestrator`, `slide_video_orchestration`,
  `multilingual_rollout` and `slideshow_video_production` are wired to it.
- Gate: a `motion` block in run state (`design`, `fingerprint`, `status`
  draft/approved/rejected, `approved_fingerprint`, `notes`).
  - `msv pipeline register-motion` / `approve-motion` / `reject-motion
    --notes`, and `pipeline init --auto-approve-motion`
    (`PIPELINE_AUTO_APPROVE_MOTION`).
  - Within a run, `render-motion` refuses a non-default language unless
    the design file, as it is now, was approved. An edit reopens the gate,
    and approving an edited file requires registering it again.
  - The gate is keyed to the design file's sha256 (16 hex characters).
- Review tools:
  - `msv motion preview`: 640×360 at 12 fps by default, not held by the
    gate, never touches production.json. 80s for the 10-minute reference
    deck, against about 6 minutes for a full render.
  - `msv motion filmstrip`: one row per slide, at 0/15/30/60/95%.
- Exit criterion, as far as it goes so far. The skill was followed on a
  second real deck (`run-20260818-001`, A2A on Hermes Agent, 13 slides):
  - round 1 passed validation; its filmstrip showed an empty panel on
    slides 1 and 7;
  - round 2 fixed that and passed;
  - the design is registered, and the user approved it on first review
    (2026-10-23, `msv pipeline approve-motion`).

  "The rollout renders all languages from it": **skipped by the user's
  decision (2026-10-23)**. On the reference deck (`run-20260911-002`) the
  sample design was registered and approved, and passes
  `validate-motion` in all 9 languages (each translated deck with its own
  narration timing; no fallbacks). It had already rendered and validated
  in en-US and zh-TW.

  A full rollout was started and stopped after its first languages,
  because all 9 languages were already published. Re-rendering would
  only have replaced their recorded videos and withdrawn their publish
  approvals. Spanish, German and French were restored to their exact
  prior state; no video or YouTube upload changed.

  Lesson: stopping the background job left the script's own children
  (the render, then the next language's) running. A rollout must be
  stoppable as a whole.
- **Findings:**
  - `run-20260818-001`'s analysis predates the extractor fix for the stray
    doctype text. Its translated decks start with a stray "html", and its
    localization node ids are offset by one, so `apply-translations`
    rightly refuses it. That run needs re-analysis before any non-English
    render.
  - Page injection now copes with pages that parse without a `</head>`.
    It previously did nothing, and the slide's timeline never registered.
- **Deviation:** previews re-render the whole deck. "Re-preview only the
  affected slides" (C2) is done by limiting the filmstrip to those slides
  (`--slides`); at 80s a deck, a partial render wasn't worth the
  complexity yet.

**Phase 7 built (2026-10-23): QA, docs, decision.**

- `msv motion compare --a … --b … --out sheet.png`
  (`production/motion/compare.py`, B6 #5). Each contact-sheet row shows
  A, B and their difference at the slide's midpoint, plus the per-slide
  duration delta, which must be 0 ± 1 frame. The command fails naming
  any slide outside that.
- Cross-engine review of the reference deck (en-US, HyperFrames
  `video.mp4` vs Remotion `video_remotion.mp4`):
  - every slide's duration delta is 0 frames;
  - the difference column is dark except text outlines, at 3-13% of
    pixels per slide.

  So layout, positions and animation state match, and the remaining
  difference is HyperFrames' font substitution, as found in Phase 3.
- D1 decided by the user (2026-10-22): `default_engine: remotion`.
- `msv motion install` also runs `hyperframes browser ensure`, so neither
  engine downloads a browser during a render. It reports both browsers'
  paths.
- CI matrix, `.github/workflows/tests.yml`:
  - `python-only` has no ffmpeg, browser or Node toolchain; everything
    that needs one must skip;
  - `full` runs ffmpeg, Node 22, Playwright's Chromium and
    `msv motion install`, so both engines render.

  The python-only case was simulated locally (tools removed from PATH,
  an empty Playwright browser dir): 170 passed, 60 skipped. That
  simulation found the context tests building their fixture with ffmpeg;
  fixed with `write_production(with_audio=False)`.
- Docs (B8, C7):
  - the production skill's troubleshooting starts with
    `msv motion doctor` and covers `motion compare`;
  - `marketing-animation-pipeline-plan.md` is marked superseded;
  - README and AGENTS.md cover compare and CI.
- **Open:**
  - the user's sign-off;
  - the CI run itself, which needs a push to GitHub (no `gh` here to
    watch it);
  - Phase 6's rollout criterion, held at the user's request;
  - Phase 8 (optional).

Phase 8 (optional) is approved, not started. Open
decisions were accepted with their recommended defaults on 2026-10-13 (see
"Open decisions").

What Phase 1 delivered: `production/motion/` (context, engine protocol,
Playwright engine, shared post-pass, B6 checks 1–4), `msv production
render-motion --engine …` plus the `render-marketing-animation` alias, seek
mode in `animation_runtime.js`, `msv slides extract-roles`,
`config/motion.yaml`, and `msv motion install`/`doctor` with a committed
`motion/package-lock.json`. Tests: 97 → 127, all passing.

Fixed after the Phase 1 code review (2026-10-22), where the build differs
from the text below:

- **Count-up:** it had stopped counting (it read the stat parser's result
  as an array). In seek mode it also never updated, because GSAP's `seek()`
  suppresses `onUpdate`. The text is now written by the tweened property's
  setter, and t=0 is the same whatever the seek history. Tests seek
  mid-tween.
- **Per-slide validation:** checks 2 and 3 compared every slide with the
  *video's* last frame, so only the last slide was really checked. They now
  use each slide's own first and last frame. A blank start frame is
  accepted when it is just the slide's own background (a white deck before
  its fade-in). Check 3 measures the fraction of pixels that changed by
  more than 24 levels, not a whole-frame mean, which shrinks with content
  area. Settled-frame encoder noise was measured at exactly 0.
- **Lead-in trim:** blank-frame detection couldn't tell a white deck's
  first frames from `about:blank` and trimmed into the entrance. Live
  capture now shows a 600ms magenta sentinel before the timeline plays (in a
  scratch copy of the deck, never the translated deck). The trim keys on
  the sentinel-to-content transition. If no sentinel was recorded, it trims
  nothing. The probe decodes only the first `lead-in + 2s`, downscaled.
- **Exact frame boundaries:** segments were encoded by seconds from a 25fps
  webm, so they came out a frame short or long at random, and a
  carry-forward pushed the error into the next slide. Segments are now
  encoded to exact frame counts rounded from the absolute timeline
  (`segment_frame_counts`). A wrong count fails loudly. With this and the
  trim fix, the fixture deck went from about 50% to 20/20 clean renders
  (dark and white) on this machine.
- **Stale runtime from old bundles:** capture copied `animation_runtime.js`
  from the run's animation bundle. On the first real-deck render
  (`run-20260911-002`, bundle from September), that old runtime never cleared
  the new sentinel, and validation refused every slide. Runtime code now
  always comes from the installed package; bundles supply per-deck data
  only.
- **Dead role selectors on a real deck:** with the stale runtime fixed, the
  same render was exact-length with no flash frames, but the per-slide
  check refused 3 of 14 slides, correctly:
  - slides 5 and 7 mark their big number `.stat-num` and have no `h1`/`h2`,
    so `stat_highlight` resolved neither `stat` nor `title`;
  - slide 10 headlines with `h3`.

  The old whole-video comparison would have passed all three, so earlier
  marketing videos likely had silently static slides. The fixes:
  - `stat` also matches `.stat-num`, `.stat-number`, `.stat-value` and
    `.metric-value`;
  - `title` falls back to `h3` only when no `h1`/`h2` exists, so existing
    decks resolve as before;
  - `count_up` rewrites only the digits' text node, so styled children such
    as `60<span class="unit">%</span>` survive.

  Tests reproduce each pattern.
- **Smaller fixes:**
  - The manifest is `<output stem>.motion.json`, so engines no longer
    overwrite each other's.
  - `extract-roles` injects seek mode into a temporary copy.
  - The legacy wrapper raises `MarketingAnimationError` again.
  - `motion install` has a lockfile and explains a missing one.

**Known limit:** Playwright's screencast delivers few frames during the
first ~500ms of a slide, so live capture records only a few frames of each
entrance animation. Validation catches it when nothing visibly changes.
This is the live-capture weakness HyperFrames' frame-exact seeking is meant
to remove (D1).

What Phase 0 actually changed, where it differs from the text below:

- **A2:** the `--audio-dir` contract is kept. An mp3 *without* a sidecar is
  trusted when it comes from an explicitly passed `--audio-dir`, and is
  regenerated once when it's in the default `segments/` folder. A sidecar
  whose key doesn't match always regenerates.
- **A3:** verified with 8 processes making 25 updates each. The old
  unlocked pattern kept 35 of 200 updates and crashed one process with a
  Windows `PermissionError`; the locked transaction kept all 200.
  `test_sustained_parallel_updates_lose_nothing` covers this.
- **A7:** libass does **not** honour `\\` as an escape (verified by burning
  test captions). A literal backslash is instead followed by an invisible
  U+2060 WORD JOINER. `\{` and `\}` work as described.
- **Publish approval on rerun (decided 2026-10-22):** any rerun of a
  language now withdraws its `publish_approved`, so a re-rendered video, or
  changed metadata, waits for a fresh human review before publishing.
  Phase 0 had left this unchanged pending the decision.
- **Tests:** 68 → 97, all passing, including the ffmpeg smoke test.

This plan covers two pieces of work that can ship separately:

- **Part A: hardening.** It fixes nine defects found in a code review of the
  current pipeline. Two of them change what gets produced: every slideshow is
  encoded twice, and edited narration can still play stale audio. One loses
  state during parallel rollout.
- **Part B: motion engines.** It makes the animated output
  (`marketing_animation.mp4`) renderable by **HyperFrames** or **Remotion**,
  alongside the current Playwright wall-clock capture, behind one engine
  interface.

- **Part C: per-deck custom motion design.** Claude designs each deck's
  motion itself, instead of the deck only being assigned one of eight fixed
  templates per slide. The design is a validated declarative file that every
  engine plays, and it goes through a human approval step.

Part A is deliberately done first (Phase 0). The motion engines build on code
it touches: the segment-audio cache, caption escaping and the concat helpers.

Relationship to `docs/marketing-animation-pipeline-plan.md`: that plan
deferred Remotion (§4.1a) and kept HyperFrames only as a fallback backend
(§4). It also already settled the two prerequisites this plan needs:

- Remotion licensing is fine under the current single-user scope (§5
  Decision 3).
- Adding Node.js to the stack is acceptable (§5 Decision 4).

This document picks both tools up. Its §5 Decision 2 still holds: motion
stays a marketing side artifact, and `slideshow.mp4` is untouched. See
Open decision D3 below.

---

## Part A — Hardening fixes

Each fix lists the file, the change, and the test that proves it. Fixes A1
and A2 change rendered output, so any run currently in flight should
re-render affected languages once they land.

### A1. Slideshow video encoded twice

- **Where:** `production/render_slideshow.py:221-222`. It contains two
  identical `subprocess.run(cmd, ...)` calls.
- **Change:** delete one.
- **Impact:** every slideshow currently pays for its most expensive encode
  twice (CFR, `-g 1`, CRF 18), so the main render takes roughly twice as long
  as it should.
- **Test:** monkeypatch `subprocess.run` in a unit test of
  `_build_silent_captioned_video` and assert exactly one ffmpeg invocation.

### A2. TTS cache ignores narration changes

- **Where:** `render_slideshow.py:319`. The check
  `if not seg_audio.exists()` uses the slide ID as the only cache key.
- **Problem:** after editing a slide's narration, a re-render silently reuses
  the old audio.
- **Change:** keep filenames stable as `segments/<slide_id>.mp3`. Both
  `render_marketing_animation.py:286` and the `--audio-dir` contract depend on
  that name. Add a sidecar `segments/<slide_id>.json`:
  ```json
  {"key": "<sha256>", "narration": "...", "voice": "...", "model": "...", "instructions_sha": "..."}
  ```
  The key is a hash of `narration`, `voice`, `model` and the fully resolved TTS
  instructions (profile instructions plus pronunciation hints).
  - Regenerate when the sidecar is missing or its key differs.
  - Write the mp3 to a temp file and rename it, so a crash never leaves a
    truncated clip that looks cached.
  - For backwards compatibility, an mp3 with no sidecar counts as stale. It
    regenerates once, after which the sidecar exists.
  - Record each slide's key in `production.json` under
    `segment_audio_keys`, so validation can detect audio and localization
    drifting apart.
- **Tests:**
  - With a stubbed `_generate_segment_tts`, assert it is called again after the
    narration changes.
  - Assert it is not called when nothing changed.
  - Assert it is called once for a legacy mp3 that has no sidecar.

### A3. Parallel rollout loses state updates

- **Where:** `state.py`'s `PipelineState.load()` → mutate → `save()`, called
  from `msv pipeline set-stage` and the other mutating commands.
- **Problem:** the `multilingual_rollout` skill runs per-language production
  concurrently. Atomic replace prevents a corrupted file but not a lost update:
  the last writer wins and overwrites other languages' stage changes.
- **Change:** add a `PipelineState.transaction(run_id)` context manager that:
  1. takes an exclusive lock on `state/<run_id>.json.lock`,
  2. loads fresh state,
  3. yields it for mutation,
  4. saves and releases.

  Every mutating CLI command (`set-stage`, `rerun-*`, `approve-*`) goes
  through it, and `save()` outside a transaction logs a warning. Use the
  `filelock` package (one small pure-Python dependency, works on Windows and
  POSIX) instead of hand-rolling `O_EXCL` lockfiles. Lock timeout: 30s, then
  fail loudly.
- **Test:** 8 processes (`multiprocessing`) each run `set-stage` for a different
  language against the same run. All 8 updates must be present afterwards.
  This test fails on today's code.

### A4. Deck fingerprint changes without any content change

- **Where:** `state.py:46` `directory_fingerprint`. It hashes path, size and
  `mtime`.
- **Problem:** `git checkout`, `git pull` or copying the deck changes `mtime`
  without changing content. That produces false "source deck changed"
  warnings and a hard fingerprint-mismatch error in
  `production validate --run-id`.
- **Change:**
  - Hash each file's relative path plus its bytes (sha256, streamed). Decks are
    small, so the cost is negligible.
  - Store `source_deck_fingerprint_algo: "content-v1"` in state and in
    `production.json`.
  - Legacy records without the algo field get a mismatch downgraded to a
    warning ("legacy fingerprint, re-render to upgrade") rather than an error.
- **Tests:**
  - `touch` every file and assert the fingerprint is unchanged.
  - Change one byte and assert it changed.
  - A legacy `production.json` mismatch produces a warning, not an error.

### A5. Whitespace lost around inline elements when translating

- **Where:** `slides/apply_translations.py`.
- **Problem:** `node.replace_with(translation)` replaces the whole node,
  including its leading and trailing whitespace. In
  `Fast <b>and</b> simple`, the node `"Fast "` becomes `"Rapide"`, which glues
  words together.
- **Change:** keep the original node's leading and trailing whitespace runs
  and wrap the stripped translation in them. Add a per-language
  `inline_word_spacing` flag in `config/languages.yaml`:
  - `false` for zh-TW, zh-CN, ja-JP: the whitespace is dropped, since these
    languages don't separate words with spaces.
  - `true` for all other languages.
- **Tests:** a fixture slide with inline `<b>`/`<a>`. Assert the French output
  keeps the spaces and the Japanese output doesn't.

### A6. Any rerun clears the YouTube video id

- **Where:** `state.py:276`. The condition
  `from_stage == "publishing" or STAGES.index("publishing") >= idx` is always
  true.
- **Problem:** every rerun, even TTS only, wipes `youtube_video_id`. A
  metadata-only republish then uploads a duplicate instead of calling
  `--existing-video-id`.
- **Change:**
  - Rerun of `publishing` only: keep the id, so the publish agent does a
    metadata-only update.
  - Rerun of any earlier stage: the video file will change, and YouTube cannot
    replace a video's file. Move the current id/url into a new
    `previous_youtube_videos` list (with a timestamp) instead of discarding it.
  - Surface that list in `pipeline report`, so a human can unlist or delete the
    superseded upload. It is never deleted automatically.
- **Tests:**
  - Rerun from `publishing` keeps the id.
  - Rerun from `tts` archives the id and clears the current one.

### A7. Caption text not escaped for ASS

- **Where:** `_write_ass` in `render_slideshow.py` and `_write_clip_ass` in
  `render_marketing_animation.py`.
- **Problem:** a `{`, `}` or `\` in a translated caption or title is parsed as
  an override tag by libass, so text can vanish or change style.
- **Change:** one shared `ass_escape(text)` helper in a new
  `production/captions.py`:
  - `\` → `\\`
  - `{` → `\{`
  - `}` → `\}`
  - newline → `\N`

  Both renderers use it, as does Part B's shared caption pass.
- **Test:** round-trip `"Use {curly} and C:\\path"` through the helper and
  assert the escaped output.

### A8. Concat lists break on paths containing `'`

- **Where:** `_write_image_concat_list` and the narration concat list in
  `render_slideshow.py`.
- **Change:** quote with ffmpeg's concat escaping, replacing `'` with `'\''`
  inside the single-quoted path. Use one shared `concat_quote(path)` helper.
- **Test:** a path containing `O'Brien` survives a real ffmpeg concat. Mark the
  test `requires_ffmpeg`.

### A9. Small correctness and cleanup items

- `production/validate.py`:
  - Collapse the redundant nested slide-order condition.
  - Treat an empty `slides` list as an error instead of a silent pass.
- `render_slideshow.py`: move the function-local `import os` to module level.
- **New smoke test** (`tests/test_render_smoke.py`, marked `requires_ffmpeg`):
  1. Generate 2 PNGs and 2 short sine-wave mp3s with ffmpeg's `lavfi`.
  2. Stub TTS.
  3. Run `render_language`.
  4. Assert the output exists, its duration is within tolerance, and the SRT
     has the right cue count.

  This end-to-end check is what would have caught A1.

**Part A exit criteria:**

- The full suite passes, including the new concurrency and smoke tests.
- Re-rendering one real deck language produces a byte-identical narration
  track when narration is unchanged.
- That re-render takes about half the previous wall-clock time.

---

## Part B — Motion engines: HyperFrames and Remotion

### B1. What changes and what doesn't

**Unchanged:**

- Agent 1's localization.
- Node-ID translation.
- `slideshow.mp4` and its tracked pipeline stages.
- Narration-driven timing. `production.json`'s `segment_timing` remains the
  single source of truth for every slide's start and end.
- The template library (`config/animation_templates.yaml`) and the template
  choice per slide (`spec.json`, from `visual_role` or the heuristic). This
  holds for Part B only. Part C turns the templates into presets inside
  Claude's per-deck design.

**Changes:**

- *How* the animated video is rendered. Today there is one way: Playwright
  plays each slide live in real time and records it. That relies on
  wall-clock timing and on the lead-in trim workaround in `render.py`, which
  measures and cuts the blank frames recorded before the page appears.
- After this work there are three engines behind one interface:

| Engine | Authoring model | Visual result | Determinism | License |
|---|---|---|---|---|
| `playwright` (existing) | Translated deck HTML + GSAP, played live | Deck-faithful | Wall-clock; relies on the lead-in trim | n/a (already in stack) |
| `hyperframes` | Translated deck HTML + GSAP, **paused and seeked per frame** | Deck-faithful | Frame-exact | Apache-2.0 |
| `remotion` | React components fed structured slide content as props | Rebuilt motion-graphics look in the brand system, not a copy of the deck | Frame-exact (pure function of the frame number) | Remotion License (free for individuals and companies of 3 or fewer people) |

These are not two ways of producing the same video:

- **HyperFrames is the deck-faithful engine.** It consumes the translated HTML
  almost as-is, so text reflow per language still comes from the deck's own
  CSS. This is the natural successor to the Playwright engine.
- **Remotion is the rebuild engine.** It re-lays out each slide's *content*
  (title, subtitle, cards, stat) in React. This allows richer motion (charts,
  layered parallax, shared-element transitions) at the cost of a second
  layout implementation. Its value is a distinct look, not parity.

### B2. Architecture

```
production.json (segment_timing, narration segments)
translated_<lang>/ deck  ─┐
animation/spec.json      ─┼─► MotionRenderContext ─► MotionEngine.render() ─► silent.mp4 (exact total duration)
localization_<lang>.json ─┤                                                          │
design_system.yaml       ─┘                                                          ▼
                                       shared post-pass (Python/ffmpeg): burn ASS captions + mux narration
                                                                                     │
                                                                                     ▼
                                     output/<run>/<lang>/marketing_<engine>.mp4 + marketing_<engine>.motion.json
```

New module `production/motion/`:

- **`context.py`** defines `MotionRenderContext`, a dataclass:
  - run, language, resolution, fps
  - `timing` (from `production.json`)
  - `slides`: a list of `{slide_id, template, start, end, roles}`
  - title card info
  - paths to the translated deck, the animation bundle and the segment audio
  - resolved design tokens
  - the CJK font files for the language (reusing `slides/cjk_fonts.py`'s
    resolution)
- **`base.py`** defines the `MotionEngine` protocol:
  - `name`
  - `check_available() -> list[str]`: missing prerequisites; an empty list
    means ready.
  - `render(ctx, work_dir) -> Path`: returns a **silent** video whose duration
    equals `ctx.total_duration` within one frame.
- **`playwright_engine.py`** wraps today's `render_deck_animation_clips`
  unchanged, so it keeps working as the reference engine.
- **`hyperframes_engine.py`** and **`remotion_engine.py`** are the new engines
  (B4 and B5).
- **`post.py`** is the shared post-pass: ASS caption burn-in plus the
  narration mux. Everything is factored out of `render_marketing_animation.py`
  and uses A7's `ass_escape`.

**Why audio and captions stay in Python, not inside the engines:**

- Narration bytes and caption timing stay identical across all three engines
  and `slideshow.mp4`. Only the visual track differs, which keeps parity
  checks honest.
- Caption burn-in already handles CJK fonts and wrapping (`wrap_style: 0`).
  Re-implementing that in two more renderers multiplies the places it can
  break.
- Each engine only has to produce an exact-length silent video, which is the
  easiest contract to verify.

In-composition captions (styled, animated) are a later option; see Open
decision D2.

### B3. Shared prerequisites

**1. Seekable animation runtime.** Today `animation_runtime.js`'s `run()`
plays the timeline immediately. Add a mode flag:

- `window.__MOTION_MODE__ = "live"` (default, for the Playwright engine) keeps
  today's behaviour.
- `"seek"` builds the same timeline `{paused: true}`, makes the page visible
  immediately (no reveal race in a seeked renderer), and registers it as
  `window.__timelines[<slide_id>]`. That is the registration convention
  HyperFrames expects; the Remotion IFrame fallback (B5) uses it too.

The templates and effect primitives don't change; only the timeline's
creation and start do. One caveat: `count_up`'s `onUpdate` must derive its
displayed value from the tween's progress rather than accumulating per tick.
Otherwise seeking backwards or jumping ahead renders the wrong number. Audit
every effect primitive for wall-clock or per-tick state, and add a test page
that seeks to t = 0, 0.5, 0.25 and checks the DOM values.

**2. Role extraction (`msv slides extract-roles`).** This is the content
contract for Remotion and a validation aid for HyperFrames.

- It loads each translated slide in Playwright and runs the runtime's existing
  `roleElements()`/`resolveRole()` logic, exposed as
  `window.__extractRoles()`.
- It writes `roles_<lang>.json`, one entry per slide:
  ```json
  {"slide_id": "...", "template": "...",
   "roles": {"title": "...", "subtitle": "...", "body": ["..."],
             "nodes": [{"text": "...", "children": []}], "stat": {"prefix": "", "value": 40, "suffix": "%"},
             "media": [{"type": "svg|img", "src": "..."}]}}
  ```
- Running the same JS resolver keeps one definition of "what is the title of
  this slide" for all engines. There is no second Python reimplementation to
  drift. Text comes from the already-translated DOM, so it is localized
  automatically.

**3. Node toolchain, pinned and offline-capable.** Add a top-level `motion/`
directory:

```
motion/
├── package.json          # exact versions, no ^ or ~; package-lock.json committed
├── hyperframes/          # composition template + build helpers (B4)
└── remotion/             # Remotion project (B5)
```

- Python invokes binaries from `motion/node_modules/.bin/` via `subprocess`,
  never through an unpinned `npx <pkg>`. This prevents silent upgrades,
  supply-chain drift, and network access at render time.
- `msv motion install` runs `npm ci` in `motion/`.
- `msv motion doctor` reports the Node version (≥ 22, required by
  HyperFrames), ffmpeg, Chromium availability, and each engine's
  `check_available()`.
- `pyproject.toml` stays Python-only. A missing Node toolchain only disables
  the two new engines; nothing else breaks.

**4. Config: `config/motion.yaml`.**

```yaml
default_engine: playwright   # flip to hyperframes after Phase 4 parity sign-off (D1)
fps: 30                      # animation needs real fps, unlike slideshow.mp4's 5fps
encode: { crf: 19, preset: medium, pix_fmt: yuv420p }
engines:
  hyperframes: { workers: auto, timeout_seconds: 1800 }
  remotion: { concurrency: auto, timeout_seconds: 1800, composition_id: Slideshow }
```

**5. CLI.**

- New command: `msv production render-motion --engine
  playwright|hyperframes|remotion --production ... --translated-deck-dir ...
  --animation-dir ... --slides-dir ... [--localization ...] [--output-name ...]`.
- `render-marketing-animation` stays as an alias for
  `render-motion --engine playwright`, so existing skills and docs don't
  break.
- Output is `marketing_<engine>.mp4` plus a `<output stem>.motion.json` manifest: engine,
  engine version, fps, per-slide timing, frame-check results, and duration
  drift.

### B4. HyperFrames engine

HyperFrames renders HTML compositions into video by pausing the page's
animations and seeking them to each exact frame before capture. It needs
Node 22+ and FFmpeg, and is licensed Apache-2.0.

Its composition format:

- a root stage element carrying `data-composition-id`, `data-start`,
  `data-width` and `data-height`;
- timed children with `class="clip"` plus `data-start`, `data-duration` and
  `data-track-index`;
- paused GSAP timelines registered on `window.__timelines[<id>]`.

Rendering uses `hyperframes render --output <file>`.

**Phase 2a spike results (2026-10-22, HyperFrames 0.8.140).** The spike
ran on small hand-built test compositions outside the repo. Every finding
below was observed, not taken from the docs.

| Question | Finding |
|---|---|
| Version and install | `hyperframes@0.8.140` pinned exact in `motion/package.json` and the lockfile. That is the newest release at least two weeks old; releases ship almost daily (539 versions, 0.8.186 on the day of the spike). It is Apache-2.0, from `heygen-com/hyperframes`, and has no install scripts. It uses `puppeteer-core` with a cached `chrome-headless-shell`, so Chrome is not bundled. `hyperframes doctor` passes for Node, FFmpeg, Chrome and Docker. |
| Telemetry | **On by default.** It sends anonymous usage, linked to a HeyGen account if signed in. The engine must set `HYPERFRAMES_NO_TELEMETRY=1` and `DO_NOT_TRACK=1` on every call. The spike did this and left the user's global setting untouched. |
| Render flags | `render [DIR] -o <file> -f <fps> -q draft\|looks\|delivery` (or `--crf`), `-w <n\|auto>`, `--resolution`, `--strict` (fail on lint errors), `--docker` (pinned Chrome and fonts for deterministic production renders), `--quiet`. |
| Nested compositions | Each slide is its own file `compositions/<id>.html`: exactly one bare `<template>` whose root carries `data-composition-id="<id>"`. `index.html` mounts it with `<div class="clip" data-composition-id="<id>" data-composition-src="compositions/<id>.html" data-start=… data-duration=…>`. Every `<style>` and `<script>` must sit inside the template. |
| CSS isolation | **Works**, including the selectors real decks use. Two slides styling `h1` differently stay separate. A slide's `body`, `html` and `:root` rules (backgrounds, inherited colour, CSS variables) are rewritten onto that slide's root and do not leak to other slides. `vw` units resolve against the composition size. One rule: style the template root via `#root`, never via a class on it. |
| Scripts | **Not isolated.** Slides are cloned into one shared document, so a slide's script sees the whole page. Our runtime is a single page-wide IIFE that reads `window.__ANIMATION_TEMPLATE__` and `document.querySelectorAll`, so it needs a per-slide entry point scoped to that slide's root (see "Build step" below). |
| Timelines | Paused GSAP timelines registered at `window.__timelines["<id>"]` are **local to the clip**: a fade at the clip's t=0.5 renders 0.5s after `data-start`. The setter-based `count_up` showed exactly 20% halfway through a 0→40 tween. The old `onUpdate` version would not have changed under seeking. |
| Assets | Served **over HTTP** (`location.protocol` is `http:`), with the project root as the base URL. Paths must be root-relative (`assets/…`, not `../assets/…`; `lint` flags the latter). A local `@font-face` font and an `<img>` both load, so CJK fonts can ship as plain files under the project. The `file://` font workaround in `cjk_fonts.py` isn't needed here. |
| Audio | A composition with no audio element produces **no audio stream at all**, only H.264 video. That fits B2: the shared post-pass muxes narration. |
| JS errors | `lint` does **not** catch runtime errors (exit 0). `render` does fail (exit 1) and names the slide (`composition script error: slide_b ReferenceError …`), but only after waiting 45s for the timeline to register. `check` (which replaces the deprecated `validate`) reports the same error in seconds with exit 1. The engine runs `check` first, then `render`. |
| Determinism | Two renders of the same project were **byte-identical**: all 180 decoded frames matched. |
| Speed | 60s at 1080p30 (1800 frames, 20 sub-compositions) rendered in **30s** on this machine (3 auto workers, hardware-GPU capture, about 2× real time). Live Playwright capture can never beat 1×, since it records each slide as it plays. *Not yet measured on the 13-slide reference deck*; that needs Phase 2b's generator. |

**Build step (`hyperframes_engine.build_project`), from the spike:**

1. **Project layout** in `work_dir/hf/`:
   - `index.html`: a root of `data-width`/`data-height` at the target
     resolution, a black base background, GSAP loaded once, and an empty
     paused `root` timeline;
   - `compositions/title.html` and `compositions/<slide_id>.html`;
   - `assets/`: the translated deck's assets, copied root-relative.
2. **Title clip:** a template showing `slide_001.png` full-bleed, with
   `data-start` 0 and the title duration. It is static, matching the other
   engines.
3. **One sub-composition per slide**, converted from the translated slide's
   full HTML document:
   - its head `<style>` blocks and stylesheet links (paths rewritten
     root-relative) move inside the `<template>`;
   - its body children go under `<div id="root" data-composition-id="<slide_id>">`;
   - `body`, `html` and `:root` rules can stay as they are, since the spike
     showed HyperFrames scopes them;
   - prefix authored ids with `<slide_id>-` if two slides could collide.
4. **Clip timing:** `data-start` and `data-duration` come from
   `segment_timing`, using the same whole-frame rounding as
   `segment_frame_counts`, so slide boundaries match the Playwright engine
   frame for frame.
5. **Animation:** split `animation_runtime.js` into a pure library plus a
   per-slide entry point, `window.__motionRunSlide(rootEl, {template, slideId,
   mode})`. Role resolution queries `rootEl`, not `document`. In
   `mode: "seek"` it registers `window.__timelines[slideId]` and leaves page
   visibility alone. Each slide template's inline script calls it for its own
   root.
   - The live Playwright path keeps working by calling the same entry point
     with `document.documentElement`.
   - The seek-determinism test then also covers the HyperFrames path.
6. **No `<audio>`** (B2).
7. **Render:** with `HYPERFRAMES_NO_TELEMETRY=1` and `DO_NOT_TRACK=1` set,
   run `hyperframes check work_dir/hf`, then `hyperframes render work_dir/hf -o
   silent.mp4 -f <fps> --crf <crf> -w <workers> --strict --quiet`, with
   timeouts from `motion.yaml`. Any non-zero exit fails loudly with its output.
   Record `hyperframes --version` in the motion manifest.
8. **Docker** (`--docker`) is an option for production renders, as it pins
   Chrome and fonts; the default stays local. Revisit in Phase 7.

**What this removes:** the wall-clock capture, the capture sentinel, the
`html{visibility:hidden}` reveal and the lead-in detection and trim. All of
them exist only because live recording isn't frame-addressable. They stay in
the Playwright engine for as long as that engine exists.

### B5. Remotion engine

Remotion authors video as React components. Timing is in frames
(`useCurrentFrame()`), and each frame is a pure function of the frame number.

**Project (`motion/remotion/`):**

- **`src/Root.tsx`** registers a composition `Slideshow`. Its
  `calculateMetadata` sets `durationInFrames` from the input props' timing
  (`ceil(total_duration * fps)`) and the width and height from the resolution.
- **`src/Slideshow.tsx`** renders a `<Sequence>` per timing item, with `from`
  and `durationInFrames` derived from `segment_timing` (round to frames,
  carrying the remainder forward so cumulative drift stays under one frame).
- **`src/templates/*.tsx`** has one component per template name in
  `config/animation_templates.yaml`. These are `TitleReveal`,
  `FeatureCallout`, `StatHighlight`, `DiagramBuild`, `Closing`,
  `QuoteTestimonial`, `ComparisonVersus` and `TimelineRoadmap`. Each takes
  `roles` from `roles_<lang>.json`.
  - A build-time test asserts the component map's keys equal the YAML's
    template names, so adding a template in YAML without a Remotion
    component fails CI instead of failing at render time.
- **`src/tokens.ts`** is generated from `config/design_system.yaml` by
  `msv motion sync-tokens`, so brand colors, type scale and motion durations
  have one source. Easing follows the brand's ease-out register from
  `design_system.yaml`: `interpolate(..., {easing: Easing.out(...)})`, with no
  springs or bounce unless the design system changes.
- **Fonts:** brand fonts are vendored under `public/fonts/` and loaded with
  `@font-face` via `staticFile()`. CJK fonts are copied in per render from
  `cjk_fonts.py`'s resolution, with `delayRender` used until they load.
- **Media:** the slide's SVG and image assets are copied into `public/` and
  referenced with `staticFile()`.

**Render:** `motion/node_modules/.bin/remotion render src/index.ts Slideshow
work_dir/silent.mp4 --props=<props.json> --muted --codec=h264 --crf=<crf>
--concurrency=<n>`. Here `props.json` holds `MotionRenderContext` serialized:
timing, roles, tokens and asset paths. The rendered video is silent, and
audio is added in B2's post-pass. If more control is needed later, a small
Node script calling `@remotion/renderer`'s `renderMedia` can replace the CLI
call without changing the Python side.

**Deck-faithful Remotion mode (needed for Part C).** In this mode Remotion
shows an `<IFrame>` of each translated slide (same-origin via `staticFile`).
On every frame, `useCurrentFrame()` drives
`iframe.contentWindow.__timelines[id].seek(frame / fps)`, reusing B3's seek
mode. A `delayRender` call holds rendering until the slide and its fonts have
loaded.

Part C's custom designs target elements in the deck's own DOM, so this is the
only way Remotion can render them. That makes it the **primary** Remotion
mode, and the "rebuilt motion graphics" template components above become an
optional alternate look (Open decision D4).

What Remotion still adds over HyperFrames in this mode is a layer *around*
the slide:
- `@remotion/transitions` for transitions between slides;
- React overlays such as charts, lower-thirds and a progress bar, which C3's
  `overlay` effect can request.

**Licensing:** per `marketing-animation-pipeline-plan.md` §5 Decision 3, the
current single-user scope uses Remotion's free license. Re-check before any
of the following:

- the owning company grows past 3 people;
- this pipeline is offered as an automated service, which falls under
  Remotion's per-render "Automators" company license;
- upgrading to Remotion 5.0, whose license terms are announced to change.

`msv motion doctor` prints a one-line reminder of this. The Remotion engine is
also never the `default_engine` unless that is decided explicitly.

### B6. Validation (all engines)

`production/motion/validate.py`, run automatically after every
`render-motion`, writes its results into the `.motion.json` manifest:

1. **Duration:** the silent video's duration equals `total_duration` within
   one frame, and the final video's within the existing
   `max_duration_drift_seconds`.
2. **No blank frames at boundaries:** extract frames at each slide's
   `start + 1 frame` and `end − 1 frame`. Fail if a frame is near-uniform white
   or black (mean and stddev thresholds), which catches regressions of the
   flash bugs documented in the earlier plan.
3. **Animation actually happened:** for each slide, the frames at start + 10%
   and at end must differ by more than a threshold. This catches selectors
   that silently resolve to nothing, the worst failure mode that plan
   identified.
4. **Engine errors:** JS console errors (Playwright), HyperFrames lint/check
   output, and Remotion render errors all fail the render, naming the slide
   where possible.
5. **Cross-engine parity (manual, used in Phase 4):** `msv motion compare
   --a ... --b ...` writes a contact sheet (one frame per slide midpoint per
   engine) for human review, plus the per-slide duration delta, which must be
   0 ± 1 frame.

### B7. Testing strategy

- **Unit tests (no Node or ffmpeg):**
  - building `MotionRenderContext` from fixture JSON;
  - the HyperFrames `index.html` generator (assert clip
    `data-start`/`data-duration` values against timing, and timeline
    registration);
  - Remotion props serialization and frame rounding (cumulative drift under
    one frame over 50 slides);
  - the template-name parity check between YAML and the Remotion component
    map, done by parsing an exported `templates.json` that the Remotion
    project build emits;
  - token sync.
- **Integration tests**, marked `requires_node` and `requires_ffmpeg` and
  skipped when those are missing: render the existing 2-slide fixture deck
  with each engine at 720p and 10 fps, and run B6's checks 1–4.
- **Runtime test:** seek-mode determinism page. Seek to a set of times twice
  in different orders and assert identical DOM state.
- **CI:** a job matrix with and without Node, so the Python-only path stays
  green.

### B8. Skills, agents and docs

- `slideshow_video_production/SKILL.md`: rewrite "Optional alternate output"
  around `render-motion --engine`, including engine selection guidance (B1's
  table) and `msv motion doctor` as the first troubleshooting step.
- `gsap_animation_authoring/SKILL.md`: add the seek-mode rules (no wall-clock
  state, no `Math.random()`, derive values from progress), because
  HyperFrames breaks quietly when they are violated.
- A new skill, `remotion_template_authoring`, scoped narrowly to maintaining
  `motion/remotion/src/templates/`, the counterpart of
  `gsap_animation_authoring`. Do not install third-party Remotion or
  HyperFrames agent skills project-wide. Review them as reference, and copy in
  only what applies, following the earlier plan's approach of
  project-authored skills.
- Update `pipeline-orchestrator.md` and `slideshow-production.md`
  dispatch tables.
- Update README: Install (`msv motion install`), the CLI list, and an
  architecture note.
- `marketing-animation-pipeline-plan.md`: add a status line pointing here,
  since §4.1a and the HyperFrames-fallback note are superseded.

---

## Part C — Per-deck custom motion design by Claude

### C1. What changes

Today, and in Parts A–B, a deck's motion comes from a fixed library: each
slide gets one of eight templates, and no AI designs the motion. That earlier
plan made this choice deliberately (§4.1 there), because a fixed library is
consistent, on-brand and testable. The cost is that every deck looks like
the same eight shots.

**New behaviour:** Claude designs the motion for each deck after reading it.
It decides:
- which elements move, in what order and with what choreography;
- what to emphasise while the narration plays;
- how slides hand off to each other;
- which elements get special treatment, such as drawing an architecture
  diagram's connectors or splitting a headline into words.

**What does not change:** the safeguards. A custom design must stay:
- deterministic, so it can be seeked frame by frame (B3);
- on-brand (`design_system.yaml`);
- valid in every language;
- validated before it renders.

That rules out letting Claude write free-form animation JavaScript as the
primary mechanism. Instead:

> **Claude writes a per-deck `motion_design.json` in a declarative motion
> language (C3). A single interpreter in `animation_runtime.js` turns it into
> GSAP timelines. The interpreter runs in the Playwright engine (live), in
> HyperFrames (seeked) and in Remotion (seeked inside an IFrame, B5).**

This keeps one design and three engines. Validation runs on the design file
before any render, and anything a design asks for that the language can't
express fails validation instead of producing a silently wrong video.

The eight existing templates become **presets** written in the same
language. Claude can use a preset as-is, adjust it per slide, or ignore it.
If a slide's custom design fails validation, the renderer falls back to that
slide's preset, so a deck never fails to render because of one slide's
design.

### C2. Where it sits in the pipeline

```
Agent 1: slide_analysis.json + localization_*.json        (unchanged)
   │
   ▼
NEW motion-design orchestrator skill (once per deck, language-independent)
   inputs:  original-deck screenshots, slide_analysis.json,
            layout_map.json (C4), default-language segment durations if available,
            design_system.yaml, the preset library
   output:  state/<run>/analysis/slides/animation/motion_design.json
   loop:    validate → low-res preview render → inspect frames → revise (max 3 rounds)
   │
   ▼
Motion approval gate (human): preview video + contact sheet; approve, or give notes in plain language
   │
   ▼
render-motion --engine … for each language (Part B), playing the approved design
```

**Language independence.**
- The design is made once, against the original English deck.
- Targets use stable node IDs and structural selectors from `layout_map.json`,
  never text.
- Timings are relative: entrances are in seconds from the slide's start, and
  later beats are fractions of the slide's duration. The same design
  therefore fits each language's different narration length (see
  `beat_at` in C3).
- A per-language check (C6) catches the cases where a translation changes
  layout enough to matter.

**Approval.**
- The motion design is a creative output, so it gets its own run-level gate,
  mirroring `approve-production`. It is stored in a new `motion` block in the
  run state with `status` (`draft`, `approved` or `rejected`), a design
  fingerprint and `approved_at`.
- Run `msv pipeline approve-motion --run-id …` to approve.
- `render-motion` refuses to render a non-default language until the design
  is approved, unless `PIPELINE_AUTO_APPROVE_MOTION=true`.
- Editing `motion_design.json` changes its fingerprint and reopens the gate.
- Motion stays outside the six tracked per-language stages, consistent with
  the earlier plan's §5 Decision 2, so this does not change `next_actions`
  for `slideshow.mp4`.

**Revising by conversation.** After a preview, you can say things like
"slide 3 feels busy, calm it down" or "draw the arrows on slide 5 one at a
time". The agent edits `motion_design.json`, re-validates, re-previews only
the affected slides and asks for approval again. No one hand-writes JSON or
prompts unless they want to.

### C3. Motion design language (`motion_design.json`, schema v1)

The language is a superset of today's template `steps`, so the presets
migrate with little change. Outline:

```json
{
  "schema": "motion-design/v1",
  "deck_fingerprint": "<content-v1 fingerprint of the source deck>",
  "style": { "energy": "calm|balanced|lively", "notes": "why these choices, for the reviewer" },
  "transitions": { "default": { "type": "cut|crossfade|push|wipe", "duration": "slide_exit" } },
  "slides": [
    {
      "slide_id": "slide_004",
      "preset": "diagram_build",
      "intent": "Build the gateway architecture left to right, then highlight the tenant boundary when narration reaches it",
      "steps": [
        { "id": "hdr",   "target": {"node": "slide_004#n0"}, "effect": "text_split", "by": "word",
          "from": {"y": 24, "opacity": 0}, "stagger": 0.04, "duration": "slide_enter" },
        { "id": "cards", "target": {"group": "layer-stack > .layer"}, "effect": "reveal",
          "from": {"x": -40, "opacity": 0}, "stagger": 0.12, "position": "hdr+=0.1" },
        { "id": "wires", "target": {"selector": "svg path.connector"}, "effect": "draw_svg",
          "stagger": 0.15, "position": "cards" },
        { "id": "focus", "target": {"node": "slide_004#n7"}, "effect": "highlight",
          "beat_at": 0.55, "duration": "base" }
      ],
      "camera": { "effect": "push_in", "scale": 1.04, "over": "slide" },
      "transition_out": { "type": "push", "direction": "left" }
    }
  ]
}
```

**Targets.** Every target must resolve to at least one element in
`layout_map.json`, or validation fails. A target is one of:
- `node`: an `extract-text` node ID;
- `group`: a repeated-sibling group from the layout map;
- `selector`: a CSS selector checked against the layout map;
- `role`: today's semantic roles.

**Effects vocabulary (v1).** Each effect is implemented once in the runtime
as a seek-safe primitive:

| Effect | Purpose | Notes |
|---|---|---|
| `reveal` | opacity, translate, scale, blur or clip-path entrance | today's primitive, more parameters |
| `accent_line` | drawn underline or rule | today's |
| `count_up` | number count-up | today's; seek-safe per B3 |
| `text_split` | per line, word or char entrance (GSAP SplitText) | `by: word` falls back to `char` or `line` for CJK per `languages.yaml` |
| `draw_svg` | stroke drawing of SVG paths, connectors and icons (DrawSVG) | |
| `highlight` | background sweep, glow or color shift for emphasis | brand accent colors only |
| `emphasis` | brief scale or pulse at a beat | amplitude capped |
| `path_connect` | animated arrow between two targets | for diagrams without SVG connectors |
| `camera` | slow push-in or pan of the whole slide (Ken Burns) | scale ≤ 1.08 |
| `exit` | leave animation before a transition | |
| `overlay` | Remotion-only React overlay, e.g. a chart from slide data | ignored with a warning by other engines |

GSAP's former bonus plugins, SplitText and DrawSVG among them, have been
free for commercial use since GSAP 3.13. They are vendored from the same
pinned `gsap` package as `gsap.min.js`.

**Timing.**
- `duration` uses design-system tokens (`fast`, `base`, `slow`,
  `slide_enter`, `slide_exit`) or seconds within bounds.
- `position` uses GSAP position syntax, relative to other step IDs.
- `beat_at: 0–1` places a step at a fraction of the slide's duration. The
  interpreter resolves it per language from `segment_timing`.

**Transitions.**
- They happen inside the existing `slide_pause_seconds` window, or as an
  overlap that takes equal time from both sides. Either way the total
  duration still equals the narration-driven sum, and B6's duration check
  still holds.
- HyperFrames renders transitions with `@hyperframes/shader-transitions`
  where it can. Otherwise, and in the Playwright engine, it uses DOM
  crossfades.
- Remotion uses `@remotion/transitions`.

### C4. New inputs Claude needs to design well

- **`msv slides inspect-layout --deck-dir … --out layout_map.json`.** This runs
  the original deck in Playwright and records, for each slide, an element
  tree:
  - node IDs and short selectors;
  - bounding boxes;
  - computed font size and color;
  - repeated-sibling groups;
  - SVG paths and their lengths;
  - `extract-roles` results.

  A screenshot only shows *what* a slide looks like. This file gives Claude
  the means to target elements precisely and design spatial motion, such as
  left-to-right builds and connectors between real boxes. It is also the
  ground truth that C5 validates targets against.
- **Annotated screenshots** (optional, produced by the same command): each
  slide's PNG with numbered boxes drawn on targetable elements, so Claude can
  map visual intent to IDs reliably.
- **Default-language segment durations**, when the default language has
  already been produced, so Claude can pace choreography against real slide
  lengths. Without them, the design uses fractions only.

### C5. Validation and guardrails (`msv slides validate-motion`)

These checks run before any preview or render. A failing slide is reported
by name and falls back to its preset at render time.

1. **Schema:** the file matches `motion-design/v1`, and every effect,
   parameter and token is known.
2. **Targets:** every target resolves in `layout_map.json`. A design whose
   `deck_fingerprint` doesn't match the current deck is rejected, the same
   rule as for translations.
3. **Brand:**
   - eases come only from the design system's ease-out family (no bounce,
     elastic or spring unless `design_system.yaml` allows them);
   - colors come only from brand tokens;
   - durations stay within token bounds.
4. **Comfort and accessibility:**
   - no more than 3 flashes per second (WCAG 2.3.1);
   - camera scale ≤ 1.08;
   - a cap on simultaneously moving elements (default 6);
   - each slide's entrance choreography settles within 40% of its shortest
     expected duration, so the viewer has time to read.
5. **Timing:** no step starts after the slide's end. Steps placed with
   `beat_at` must leave at least their own duration before the slide ends.
6. **Determinism:** guaranteed by the language, since it offers no
   free-form code, no randomness and no wall-clock time. Seek-safety is
   tested once per effect primitive in the runtime, not per design.

### C6. Self-review loop and per-language check

**Self-review (inside the agent, at most 3 rounds).**
1. `msv motion preview --engine hyperframes --res 640x360 --fps 12`, or the
   Playwright engine before Phase 2b lands.
2. Extract a filmstrip per slide: frames at 0%, 15%, 30%, 60% and 95%.
3. Claude inspects the frames for clipped or overflowing elements,
   motion that never visibly happened, clutter and readability, then revises
   the design.
4. Each round's findings go in `motion_design.review.md` for the human
   reviewer.

**Per-language check (automatic, before approval).**
- Render the preview in three languages: the default, the longest
  translation (typically de-DE) and one CJK language.
- Rerun C5's target checks against each translated deck's layout, because
  translated text can change line breaks and group sizes.
- Run B6's checks on each preview.
- Problems are reported per slide and language. A slide that fails in only
  one language falls back to its preset in that language only.

### C7. Skills

All skills live in `.agents/skills/`. The former `.claude/agents/` subagents
became orchestrator skills on 2026-10-22, so the motion designer is two
skills, following the same pattern:

- **New orchestrator skill `.agents/skills/motion_design/`** (the role,
  its approval gate and what it dispatches) and **new procedure skill
  `deck_motion_design`**. The procedure skill covers:
  - the process (C2, C6);
  - the language reference (C3), generated from the JSON schema so the docs
    can't drift from it;
  - the guardrails (C5);
  - design guidance: one focal point per beat, motion follows the narration's
    argument, restraint on dense slides.

  It also tells the agent to use the existing `motion_design_principles` and
  `gsap_animation_authoring` skills as background knowledge.
- **`pipeline-orchestrator`:** dispatch motion design after Agent 1
  when motion output is requested, report the motion gate in `pipeline
  status`, and add `approve-motion` to its human-gate handling.
- **`language-rollout`:** render motion for remaining languages only
  once the motion gate is approved.
- **Optional, unattended runs:** `msv motion design --headless` calls the
  Claude API with the same skill text. It exists for scheduled or
  server-side use without Claude Code, and needs an API key; it is not part
  of the core phases.

### C8. Escape hatch: custom code (deferred)

Some effects won't fit the language: a bespoke particle background, or
morphing one logo into another. For those, a later phase can allow a
per-slide `custom_code` step containing GSAP JavaScript. These steps:
- are allowed only in the HyperFrames and Playwright engines;
- must register a paused timeline and use no `Math.random()` or `Date`;
- must pass an automated seek-determinism test (render selected frames
  twice, out of order, and compare pixels);
- are always flagged in the approval contact sheet.

Not in v1. The recommendation is to see what the language can't express in
real decks first (Open decision D5).

---

## Part D — Animation-first production with a playful style (decided 2026-10-22)

**Decision.** The animated video becomes the production output, rendered in
one pass, and its motion style becomes playful. This supersedes Open
decision D3 ("motion for the canonical video, later") and the earlier
plan's §5 Decisions 0 and 2 (motion as a side artifact rendered after a
static slideshow). The reasons given: the two-pass flow (static video first,
animation second) is unwanted, and the calm animation looked dull.

**GSAP stays.** It is the animation library HyperFrames renders: HyperFrames
seeks paused GSAP timelines frame by frame. Remotion in deck-faithful mode
seeks the same timelines. The dull look came from the calm template set
(brand ease-out only, a half-second fade, then a static hold for the rest
of a 30–40s slide), not from GSAP. What retires is the Playwright
live-capture engine, which becomes a fallback.

### D1. Playful motion style (built)

- `config/animation_templates_playful.yaml`: the same 8 template names as
  the calm set, selected by `animation_style: playful` in
  `config/motion.yaml`.
- New seek-safe effects in `animation_runtime.js`:
  - `pop`: springy scale-in;
  - `words`: kinetic headline, word by word, or character by character for
    CJK;
  - `beats`: items pop in across the narration, with the first item within
    1.2s;
  - `float`: gentle ambient bob;
  - `drift`: slow push-in on the whole slide;
  - `exit`: fade-up before the cut;
  - `count_up` with a springy entrance.
- `beat:<fraction>` positions, laid out against each slide's real duration,
  which both engines now pass to the runtime.
- Only the first entrance step claims an element. This prevents the GSAP
  double-`.from()` bug that leaves an element invisible.
- Both engines generate `templates_config.js` from config for the
  configured style, instead of the bundle's snapshot.
- Validation:
  - checks 2 and 3 use each slide's settled frame, 0.6s before the cut,
    because a playful slide ends on its exit;
  - "blank" means near-zero content pixels, not a low stddev, which misread
    small text on white.
- **Sample:** 4 real slides of `run-20260911-002` (title, diagram, stat,
  `h3` cards) rendered with HyperFrames in 210s for 152s of video; validation
  passes. Output: `output/run-20260911-002/en-US/playful_sample/`.
- **Known gap:** `drift` changes every frame slightly, so check 3 ("did
  anything animate") passes even on a slide whose content steps resolved
  nothing. Add a static check that each slide has at least one content
  step resolving (via `extract-roles`) before relying on check 3 for the
  playful style.

### D2. One-pass production pipeline (next)

1. **Narration as its own step.** Factor TTS and slide timing out of
   `render_slideshow.py` into `msv production narrate`. It writes
   `production.json` (`segment_timing`, segment audio, narration track)
   without rendering any video. This is the decoupling the earlier plan's
   Decision 0 rejected at the time.
2. **Stage order** becomes `analysis → translation → tts → rendering →
   validation → publishing`. `rendering` is `render-motion` (default engine
   HyperFrames), producing the language's video directly. `render-slideshow`
   stays as a fallback command, not a stage.
3. **Title card** rendered as an animated HyperFrames composition from slide
   1's markup, instead of the static `slide_001.png`.
4. **Static screenshots** are still needed for the slide-analysis step's
   view of the original deck. Translated-deck screenshots are no longer
   needed for production.
5. **Skills:** update `slideshow_production` and
   `slideshow_video_production` for the new step order. Publishing uploads
   the animated video.
6. **Migration:** existing runs keep their state; new runs use the new
   order. `pipeline validate` flags a run created with the old order.

### D3. Then

- Tune the playful templates on feedback from the sample, then render the
  full reference deck in English and one CJK language.
- Part C (Claude designs each deck's motion) builds on this vocabulary.
- Remotion (Phase 3) is unchanged.

## Phased plan

| Phase | Work | Exit criteria | Size |
|---|---|---|---|
| **0 — Hardening** | A1–A9 | Part A exit criteria met; all existing and new tests green | 2–3 days |
| **1 — Engine seam** | `production/motion/` (context, base, post, playwright engine); `render-motion` CLI and alias; seek mode in `animation_runtime.js` with a determinism test; `extract-roles`; `motion.yaml`; `motion/` scaffold with `install`/`doctor`; B6 checks 1–4 | `render-motion --engine playwright` output is visually identical to today's `render-marketing-animation` on the reference deck; validation catches a deliberately broken selector | 4–5 days |
| **2a — HyperFrames spike** | Answer every question in B4's spike list against a pinned version, using the 2-slide fixture deck | Answers recorded in this document; go/no-go on the nested-composition approach | 1 day |
| **2b — HyperFrames engine** | `hyperframes_engine.py`, composition generator, font handling, integration test | 13-slide reference deck renders in 2 languages (one Latin-script, one CJK); B6 passes; boundary frames are clean without any lead-in trim | 4–5 days |
| **3 — Remotion engine** | `motion/remotion/` project in deck-faithful IFrame + seek mode (B5), `@remotion/transitions`, `remotion_engine.py`, font and asset handling. The rebuilt-look template components are deferred (D4). | Reference deck renders in 2 languages; B6 passes; output matches HyperFrames frame-for-frame apart from transitions and overlays | 4–5 days |
| **4 — Motion language and interpreter** (C3) | `motion-design/v1` JSON schema; interpreter in `animation_runtime.js` replacing the per-template engine; new seek-safe effects (`text_split`, `draw_svg`, `highlight`, `emphasis`, `path_connect`, `camera`, `exit`); transitions in all engines; migrate the 8 templates to presets; vendor SplitText and DrawSVG from the pinned `gsap` | All 8 presets render identically to before; every new effect passes the seek-determinism test; a hand-written sample design renders in all engines | 6–8 days |
| **5 — Layout map and validation** (C4, C5) | `inspect-layout` (element tree, boxes, groups, SVG paths, annotated screenshots); `validate-motion` with every C5 guardrail; per-slide fallback to preset at render time | Deliberately invalid designs (bad target, bounce ease, 5 flashes per second, beat past the slide's end) are each rejected with a slide-named error; fallback verified | 4–5 days |
| **6 — Motion design skills and gate** (C2, C6, C7) | `motion_design` orchestrator skill and `deck_motion_design` procedure skill; `motion preview` and filmstrips; self-review loop; per-language check; `approve-motion` gate and `motion` state block; orchestrator and rollout wiring | On 2 real decks the agent produces a design that passes validation within 3 rounds and is approved by a human on first or second review; the rollout renders all languages from the approved design | 6–8 days |
| **7 — QA, docs, decision** | `motion compare`, contact-sheet review across engines, B8 and C7 doc updates, CI matrix | Human sign-off; D1 decided and `default_engine` set | 2–3 days |
| **8 — Optional** | Retire the Playwright capture engine if HyperFrames becomes the default; C8 custom-code escape hatch (D5); `motion design --headless`; Remotion rebuilt look (D4); revisit D2 and D3 | Gated on evidence from Phase 7 | — |

Phase 0 can merge on its own and should not wait for Part B. Once Phase 1
lands:
- Phases 2 and 3 (the engines) can run in parallel with Phases 4 and 5 (the
  motion language and validation).
- Phase 6 needs Phase 4, Phase 5, and at least one engine (Playwright is
  enough for preview).

Total for Phases 0–7 is about 6–8 weeks for one developer.

---

## Risks

| Risk | Mitigation |
|---|---|
| HyperFrames is young; flags and composition syntax may differ from the docs or change between versions | Phase 2a spike before building; exact version pin plus lockfile; `motion doctor` prints the engine version into `motion.json` |
| Deck CSS collides when slides share one HyperFrames document | Prefer per-slide sub-compositions (keeps each slide's HTML untouched); fall back to scoped containers; boundary-frame and contact-sheet review |
| Remotion layouts don't fit long translations (German) or dense CJK, since the layout is re-implemented, not the deck's CSS | Templates use fit-text (`@remotion/layout-utils`' `fitText`) with min and max sizes; fixture slides with the longest real translations; contact-sheet review per language |
| Two layout systems (deck CSS and Remotion) drift apart in brand look | Both read `design_system.yaml` (tokens synced, not copied); brand review is a Phase 3 exit criterion |
| Effect primitives with hidden per-tick state render wrong under seeking | B3 audit plus a determinism test that seeks out of order |
| Remotion license scope changes (headcount, automation offering, 5.0) | Re-check triggers listed in B5; `doctor` reminder; never the default engine without an explicit decision |
| Node supply chain | Exact pins, committed lockfile, `npm ci`, no `npx` fetches at render time |
| Custom designs are worse than the presets (busy, distracting, inconsistent between decks) | C5's restraint guardrails; the self-review loop; a human approval gate with a contact sheet; `style.energy` set per deck; presets as the fallback floor; a "use presets only" option per run |
| A design valid in English breaks in another language (reflowed lines, a different group size) | Targets use node IDs and groups, not text; C6 checks every target in three languages; fallback to preset per slide and language |
| The motion language is too limited, so Claude can't express what a deck needs | Log each unmet request in `motion_design.review.md`; grow the effect vocabulary from real gaps; C8 escape hatch only if gaps persist |
| Design time and cost per deck (preview renders, 3 review rounds) | Low-res, low-fps previews; re-preview only changed slides; the design is made once per deck and reused for every language |
| The engine seam and the motion language both rewrite `animation_runtime.js` | Phase 1 adds only the seek mode. Phase 4 replaces the engine with the interpreter, and its exit criterion is identical preset output. |

---

## Open decisions

**Accepted on 2026-10-13:** D1, D4, D5, D6 and D7 take the recommendation
stated in each item below. D2 and D3 stay deferred to Phase 8 as
recommended. Revisit any of them with evidence from the phase noted.

Each of these is needed before the phase noted.

- **D1 — Default engine (before the end of Phase 4).** The recommendation is
  `hyperframes` if it passes Phase 2b and 4. It keeps the deck-faithful look
  users already approved and removes the most fragile code in the current
  path. Remotion would be an explicitly chosen alternate style.
- **D2 — Captions inside the composition (Phase 5).** Moving captions into
  HTML or React would allow animated, brand-styled captions. The cost is
  losing the single shared caption path (B2) and re-solving CJK wrapping per
  engine. The recommendation is to defer.
- **D3 — Motion for the canonical `slideshow.mp4` (Phase 5).** This reopens
  the earlier plan's §5 Decision 2. HyperFrames' frame-exact rendering makes
  it more plausible than with live capture, but it should wait until motion
  output has production mileage.
- **D4 — Remotion look (recommendation updated for Part C).** Build the
  deck-faithful IFrame + seek mode first. Claude's custom designs target the
  deck's DOM, so this is the only mode that can play them. The "rebuilt
  motion graphics" look moves to Phase 8 as an optional style.
- **D5 — Custom-code escape hatch (Phase 8).** Allow per-slide GSAP code
  (C8), or keep the declarative language only. The recommendation is the
  language only until real decks show gaps it can't express.
- **D6 — Motion approval (before Phase 6).** A human approves every deck's
  motion design (the plan's default), or `PIPELINE_AUTO_APPROVE_MOTION=true`
  lets validated designs render unattended. The recommendation is human
  approval for at least the first several decks.
- **D7 — Who designs motion when there's no Claude Code session.** Either
  Claude Code agents only (the core plan) or also the headless Claude API
  path (`motion design --headless`, Phase 8), which needs an Anthropic API
  key and per-deck API spend.

## References

- HyperFrames: [repository](https://github.com/heygen-com/hyperframes),
  [docs](https://hyperframes.heygen.com/introduction),
  [HyperFrames vs Remotion](https://hyperframes.heygen.com/guides/hyperframes-vs-remotion)
- GSAP: [3.13 release, all plugins free](https://gsap.com/blog/3-13/)
- Remotion: [license](https://www.remotion.dev/docs/license),
  [pricing](https://www.remotion.dev/docs/license/pricing)
- `docs/marketing-animation-pipeline-plan.md`: prior evaluation and decisions
  (§4.1a, §5 Decisions 2–4).
