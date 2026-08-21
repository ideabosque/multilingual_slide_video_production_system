# Marketing Animation Pipeline — Development Plan

Status: **implemented — Phases 0-4 are built and verified end-to-end**
(real render against both a 2-slide fixture deck and the 13-slide
`a2a-hermes-agent-docker-gateway-deployment` deck; see "What actually got
built" below). This document evaluates eight external animation/video
tools against this project's actual pipeline and records how
`render_marketing_animation.py`'s original procedural (PIL/numpy) approach
was replaced with genuine motion-design animation, without losing what
already works (node-ID HTML translation, narration-driven pacing, the
five-agent structure).

## What actually got built

- **`.claude/skills/gsap_animation_authoring/SKILL.md`** and
  **`.claude/skills/motion_design_principles/SKILL.md`** — project-authored
  (not verbatim copies — see each file's own note on this), informed by
  `gsap-skills`/`motion-design-skill`'s public READMEs.
- **`src/multilingual_slide_video_agent/slides/vendor/gsap.min.js`** —
  the real GSAP 3.15.0 core build, fetched via `npm pack gsap` (see
  `GSAP_LICENSE.txt` alongside it) — free for all use since Webflow's 2024
  GreenSock acquisition.
- **`slides/design_system.py`** — loads `config/design_system.yaml`
  (§4.2) and exposes it as CSS custom properties for injection.
- **`slides/animation_templates.py`** + **`slides/assets/animation_runtime.js`**
  — five named shot templates (`title_reveal`/`feature_callout`/
  `stat_highlight`/`diagram_build`/`closing`, this project's own design —
  see §4.1a) and the role-selection heuristic that picks one per slide.
  Element targeting uses common semantic HTML (h1/h2, li/p, svg/img) with
  an escape hatch for explicit `.slide-*` classes if a deck defines them,
  since real decks predate this feature and aren't authored with
  animation-specific classes.
- **`slides/generate_animation.py`** (`msv slides generate-animation`) —
  materializes one deck's animation bundle once, per §4.1.
- **`slides/render.py`'s `render_deck_animation_clips`** — injects the
  bundle into a translated deck and captures each slide via Playwright's
  native video recording, failing loudly on any browser console error.
- **`production/render_marketing_animation.py`** (`msv production
  render-marketing-animation`) — fully rewritten: captures animated clips,
  muxes each with its own narration segment and caption, concatenates with
  a static title card (unchanged from the original design).
- 15 new tests (`test_animation_templates.py`, `test_design_system.py`,
  `test_generate_animation.py`), all passing alongside the existing 32.
- Skill/agent docs updated: `slideshow_video_production/SKILL.md` (new
  "Optional alternate output" section), `slide_video_orchestration/SKILL.md`
  (dispatch table row), both `pipeline-orchestrator-agent.md` and
  `slideshow-production-agent.md`.

**Reconsidered during the build:** `video-shotcraft` was removed from the
primary path entirely (§4.1a) after confirming it has no
renderer-independent form — see that section for why "port the knowledge,
skip the Remotion renderer" turned out not to hold up.

**Not yet done:** wiring this into the actual `.claude` skill/agent
*workflow* end-to-end via a live agent conversation (this build validated
the CLI/rendering mechanics directly, via Bash, against real run data —
not via a dispatched `slideshow-production-agent` conversation), and
everything in §6 Phase 5 (still deferred, gated on production evidence).

### Follow-up fixes and enhancements (post-Phase-4)

Found and fixed after the initial build, via real production output on
the 13-slide deck, not caught by the fixture-deck testing above (that
fixture has a white page background, which made a white flash
indistinguishable from the deck itself):

- **Flash-of-unstyled-content fix.** Each captured clip's first frame(s)
  briefly showed the slide at its *final* animated state before GSAP's
  `.from()` tween applied the starting state — a visible flash at every
  slide boundary. Fixed with a render-blocking `html{visibility:hidden}`
  inline style, revealed synchronously right after the timeline is built
  (`animation_runtime.js`'s `run()`, `render.py`'s injection — see
  `gsap_animation_authoring/SKILL.md`'s "Injection point", which was
  rewritten to document this, having been inaccurate since before Phase
  2/3 were implemented). Verified via frame extraction at slide
  boundaries on the real (dark-themed) deck — no flash.
- **Richer entrances**, per explicit follow-up request (`gsap_animation_authoring`/
  `motion_design_principles` updated to match):
  - A **repeated-sibling-group selector fallback** (`animation_runtime.js`'s
    `findRepeatedSiblingGroup`) — turned out to matter more than any single
    new effect. Real decks commonly express card/row/layer grids as N
    sibling `<div>`s sharing one class (e.g. this deck's
    `.layer-stack > .layer`), not `<li>`/`<p>`, which the original
    selectors (semantic-tag-only) never matched — meaning most of the
    deck's actual content wasn't animating at all before this fix, not a
    cosmetic gap.
  - **Real number count-up** for `stat_highlight` (parses prefix/number/suffix,
    e.g. `"40%"`, `"3x faster"`, `"$1.2M saved"`; falls back to a plain
    scale-in if no number is found).
  - **Staggered per-card reveal** for `diagram_build`, using the same
    repeated-sibling detection, instead of one fade of the whole diagram
    block.
  - **Drawn accent-line underline** beneath headlines
    (`title_reveal`/`feature_callout`/`diagram_build`/`closing`; decorative
    only, `stat_highlight` skips it to keep focus on the number).
  - Verified via frame extraction on the real deck: a mid-stagger frame
    (`a2a_settings` row still translucent while three earlier rows had
    already settled) and an accent line visibly drawn under a real
    headline.

**Decided:** `render_marketing_animation.py` is fully replaced (not kept as
a selectable alternate style) by the GSAP+Playwright approach in §4, using
a fixed template library selected per slide by a deterministic heuristic,
not agent-generated code (§4.1 — confirmed and corrected from the
original intent after the fact), built against a design system derived
from `ideabosque.ai_website`'s real brand tokens (§4.2,
`config/design_system.yaml`). `render_slideshow.py`/`slideshow.mp4` — the
canonical, pipeline-tracked, already-published-to-9-languages output — is
left untouched for now (§5 Decision 2), and the animated version stays
sequentially dependent on that slideshow already existing (§5 Decision 0).
Remotion licensing is clear under a single-user scope and Node.js is an
accepted addition to the stack (§5 Decisions 3-4), so the Remotion secondary
path and the HyperFrames-as-backend fallback in §4 are both available on
pure engineering merit if ever needed — neither is a blocker, and neither is
required by the primary path.

## 1. Where things stand today

Two renderers currently exist under `src/multilingual_slide_video_agent/production/`:

- **`render_slideshow.py`** — the canonical per-language output
  (`slideshow.mp4`). Each slide is a **static PNG** (Playwright screenshot of
  the translated HTML deck) held on screen for
  `narration_duration + slide_pause_seconds`, concatenated via ffmpeg's image
  concat demuxer, with burned-in ASS captions. No animation of any kind
  in-frame — the only motion is the hard cut between slides.
- **`render_marketing_animation.py`** — an optional, unwired-into-the-pipeline
  variant (`marketing_animation.mp4`) that **procedurally draws frames with
  PIL/numpy** (gradient background, node/arrow diagrams, animated progress
  bar, wrapped headline/sub text) and pipes raw RGB frames into ffmpeg,
  reusing the same narration track and `segment_timing` from
  `production.json`.

The problem this plan addresses: `render_marketing_animation.py`'s visual
vocabulary (`_label_for`, `_tags_for`, `_visual_kind`) is **hardcoded to one
deck's keywords** ("tenant", "rls", "hermes", "gateway", ...) — it produces a
good result for the A2A/Hermes deck it was built against, but does not
generalize to a new deck's content without editing Python source. It's also
visually simple (linear eases, a handful of node/arrow/pill shapes) compared
to what a real motion-graphics tool produces. The user asked whether one of
several externally-available animation tools/skills should replace this.

## 2. What was evaluated

All eight URLs were fetched and read directly (GitHub READMEs / Remotion's
docs site / Remotion's LICENSE.md); nothing below is guessed.

| Project | Type | Renders to | Stack | License | Used in this plan? |
|---|---|---|---|---|---|
| [heygen-com/hyperframes](https://github.com/heygen-com/hyperframes) | CLI + library + agent skill + cloud (Lambda) render | Deterministic MP4 from HTML/CSS compositions | Node.js 22+, Puppeteer, ffmpeg; animation via GSAP/CSS/Lottie/Three.js/Anime.js/Web Animations API | **Apache 2.0** | **Not now — deferred fallback.** §4: adopt only as a rendering *backend* (shelled out to, like ffmpeg) if native Playwright video capture proves insufficient. Not part of Phase 0-4. |
| [greensock/gsap-skills](https://github.com/greensock/gsap-skills) | Agent skill (knowledge only, no renderer) | N/A — teaches an agent to write correct GSAP code | GSAP (JS animation lib), React/Vue/Svelte/vanilla | **MIT** (skill); GSAP itself became free for all use after Webflow's 2024 acquisition of GreenSock — worth a final check of GSAP's own license page before shipping, not re-derived here | **Yes — Phase 0.** Installed into `.claude/skills/` as authoring guidance for the agent that generates each deck's GSAP timeline (§4.1). |
| [nolangz/pixel2motion](https://github.com/nolangz/pixel2motion) | Agent skill + commercial service | Animated SVG + HTML motion demo (not video, though it can export GIF/video previews) | Python 3.10+, Pillow, NumPy, Playwright/Chromium | **MIT** | **Not used.** Scope is logo-only, doesn't cover full-deck animation. Revisit narrowly only if/when a brand-mark animation for the title card is separately wanted. |
| [remotion.dev/docs/ai/skills](https://www.remotion.dev/docs/ai/skills) | Agent skill collection for the Remotion framework | Video via React components | React, Remotion, optional Mapbox/CesiumJS, Bun | See LICENSE.md row below — **not plain open source** | **Not now — deferred secondary path.** §4/§5 Decision 3: licensing is clear (single-user scope), but this is only picked up if the primary GSAP+Playwright path's output quality proves insufficient (§6 Phase 5, gated on evidence). |
| [haidrrrry/claude-remotion-skill](https://github.com/haidrrrry/claude-remotion-skill) | Claude agent skill | Motion-graphics MP4 (springs, staggered choreography, captions, sound design) via Remotion, self-verifies by extracting/inspecting frames | Remotion (React+TS), ffmpeg | **MIT** (skill); still requires a Remotion license — see below | **Not now — same deferred secondary path as above.** Would be the natural starting reference if/when Remotion is picked up. |
| [Vincentwei1021/video-shotcraft](https://github.com/Vincentwei1021/video-shotcraft) | Claude/Codex agent skill | Cinematic *product* videos (152 shot recipes, 209 motion previews, beat-synced editing, sound design, CapCut/JianYing export) via Remotion | Remotion (React+TS), Node 22, Chromium | **Apache 2.0** (skill); still requires a Remotion license | **Not used, including its design knowledge.** Reconsidered after confirming it has no renderer-independent form — its shot recipes and motion templates are implemented *as* Remotion React/TSX compositions, not portable concepts with a separate reference doc, so "port the knowledge, skip the renderer" would still mean reverse-engineering Remotion-specific code. Fully deferred to the secondary Remotion path (§4.1a) alongside the other three Remotion-based projects — revisit only if that path is ever picked up. |
| [lottiefiles/motion-design-skill](https://github.com/lottiefiles/motion-design-skill) | Agent skill (knowledge only, no renderer) | N/A — teaches timing/easing/choreography/Disney-animation-principles, implementation-agnostic (CSS, Framer Motion, GSAP, Lottie, Spring) | none (pure guidance) | **MIT** | **Yes — Phase 0.** Installed into `.claude/skills/` alongside `gsap-skills`, same purpose: improves the quality of agent-authored timelines regardless of renderer. |
| [gnipbao/story-to-handdrawn-video](https://github.com/gnipbao/story-to-handdrawn-video) | Standalone Remotion renderer + agent skill | Silent hand-drawn-style MP4 (20 visual styles, vertical 3:4) for later voiceover | Node 20+, Python 3.10+, Remotion, ffmpeg | **MIT** (+ SIL OFL for bundled font); still requires a Remotion license | **Not used.** Stylistic niche (hand-drawn story illustration) that doesn't fit a marketing video; kept only as a pattern reference (agent skill + Remotion renderer + silent-track-for-voiceover shape mirrors this project's own narration separation). |

**Remotion's actual license** (from `remotion-dev/remotion/LICENSE.md`,
fetched directly): free only for an individual, a **for-profit organization
with 3 or fewer employees**, a non-profit, or someone evaluating it for
possible commercial use. Anyone larger must buy a paid Company License
(pricing lives at remotion.pro, not disclosed in the license file itself).
**Four of the eight items evaluated (Remotion's own skills, claude-remotion-skill,
video-shotcraft, story-to-handdrawn-video) sit on top of Remotion and inherit
this constraint.** This was a business decision, not an engineering one —
now resolved, see §5 Decision 3.

## 3. Fit against this project's actual architecture

Two things distinguish this project from a generic "make a marketing video"
task, and they should drive the choice more than which tool has the flashiest
demo:

1. **The deck is already localizable HTML**, translated by stable DOM node
   ID (`slides/extract_text.py`, `slides/apply_translations.py`). Any
   animation approach that works *inside that same HTML* (CSS/GSAP timelines
   triggered on the existing translated markup) gets translation for free —
   text still reflows correctly per-language because the browser is still
   laying it out live. An approach that pre-bakes raster/vector assets per
   language (e.g. Pixel2Motion's per-language logo SVGs, or hand-authored
   Remotion compositions with hardcoded English strings) would need its own
   localization pass bolted on.
2. **Playwright/Chromium is already a hard dependency** (`slides/render.py`)
   for exactly the same reason all of these tools use headless Chrome/Puppeteer:
   deterministic, pixel-accurate HTML rendering. Playwright can record a
   page's own video natively (`browser.new_context(record_video_dir=...)`),
   which is architecturally the same trick HyperFrames performs with
   Puppeteer — we may not need a second browser-automation stack at all.

This makes **HyperFrames's approach** (not necessarily HyperFrames the Node
CLI itself) the closest conceptual match: HTML/CSS + a JS animation library,
captured deterministically, muxed with ffmpeg — which is exactly this
project's existing shape, just static instead of animated today.

**Remotion's approach** is a different paradigm: video is authored as React
*components*, not as the same HTML deck files Agent 1/2 already translate. It
is the most mature and best-supported option for AI-agent-authored motion
graphics (that's what 4 of the 8 results are built on), but adopting it means
running two parallel content representations (the translated HTML deck for
`slideshow.mp4`, and a separate React composition for the animated variant),
plus the licensing question above.

## 4. Recommendation (decided)

**Animate the existing translated HTML decks with GSAP, capture with
Playwright's native video recording, keep ffmpeg for final mux — no new
runtime. This fully replaces `render_marketing_animation.py`'s PIL/numpy
approach; `render_slideshow.py` is untouched.**

Concretely:

- GSAP (loaded via `<script>` tag in the deck template, or bundled locally —
  no build step required, no Node.js needed to *use* it) driving each
  slide's enter/hold/exit motion, authored as reusable timeline templates
  keyed by a slide's *role* (title, feature, diagram, closing) rather than
  hardcoded keyword-matched content like today's `_label_for`/`_tags_for`.
- `slides/render.py` gains a video-capture mode (Playwright
  `record_video_dir`) alongside its existing static-screenshot mode, so a
  slide's animated sequence is captured deterministically at a fixed
  resolution/fps, the same way `slides/render.py` already captures static
  PNGs today.
- `production/render_marketing_animation.py` is rewritten to concatenate
  those captured per-slide animation clips (instead of PIL frames) and mux
  with the existing narration/caption pipeline it already has — the
  narration generation, `segment_timing`, and caption logic it already has
  do not need to change.
- Adopt **`gsap-skills`** and **`motion-design-skill`** into
  `.claude/skills/` now, regardless of timeline — both are pure
  documentation/knowledge (MIT, no code dependency, no license risk). See
  §4.1 for what they actually inform, which changed from the original
  intent below once §4.1 was implemented and the scope was confirmed.
- Evaluate **HyperFrames itself** as an optional *rendering backend* (shelled
  out to as a subprocess, the same way `ffmpeg`/`ffprobe` already are) only
  if native Playwright-video capture proves insufficient — e.g. if its
  caption/audio-mixing/Lambda cloud-render tooling turns out to save more
  effort than the Node.js dependency costs. Treat this as a fallback, not a
  starting assumption.

### 4.1 Where the animation code comes from (decided — revised from the original intent)

**As originally written, this section said an agent would generate the
GSAP timeline per deck, at runtime, using `gsap-skills`/`motion-design-skill`
as authoring guidance.** That's not what got built, and after the
follow-up conversation that confirmed it explicitly (see "Follow-up fixes
and enhancements" above): **the animation code is a fixed, hand-written
template library, not agent-generated per deck.** This is the confirmed,
final architecture, not a stopgap:

- **`slides/assets/animation_runtime.js`** holds five named shot templates
  (`title_reveal`/`feature_callout`/`stat_highlight`/`diagram_build`/`closing`)
  as static JavaScript — written once, reviewed, tested, reused unmodified
  across every deck. No LLM call writes or modifies this file at pipeline
  run time; `generate_deck_animation()` makes zero LLM calls (verified by
  reading the code, not assumed).
- **`slides/animation_templates.py`'s `choose_template`** — a deterministic
  Python heuristic, not an agent — assigns each slide one of the five
  template *names* by slide position (first → `title_reveal`, last →
  `closing`) and keyword-matching its `slide_analysis.json` description
  (`"%"` → `stat_highlight`, `"architecture"`/`"diagram"` → `diagram_build`,
  else `feature_callout`).
- `msv slides generate-animation` (Agent 1, alongside `slide_analysis.json`)
  runs this heuristic once per deck and writes the resulting `spec.json`
  (slide → template name) plus the static JS/CSS bundle — same
  cache-once-reuse-across-languages shape as originally planned, just with
  a fixed library instead of generated code underneath it.
- An agent (or a human) *can* override the heuristic's choice via
  `--spec <file.json>` — but only to pick among the five existing template
  *names* per slide, never to author new motion design. Extending the
  template library itself (a 6th template, retuning an existing one) is a
  manual code change, reviewed like any other code, not a per-run
  operation.

**What `gsap_animation_authoring`/`motion_design_principles` are actually
for, given this:** template-library *maintenance* guidance, not per-deck
runtime authoring. They matter when someone (human or agent) is asked to
add a new template or retune an existing one in `animation_runtime.js` —
not on a normal `generate-animation`/`render-marketing-animation` run,
which never loads either skill.

**Implemented: improved *selection* quality, since generation is
intentionally fixed.** The one real lever for better output is which
template a slide gets assigned; the keyword-matched heuristic alone was
crude and disconnected from Agent 1's own (already-LLM-driven) judgment
about each slide. `slide_analysis.json` now supports an optional
`visual_role` field (one of `TEMPLATE_NAMES`) that `slide-analysis-agent`
assigns per slide as part of the analysis work it already does
(`slide_deck_localization/SKILL.md` updated accordingly). `choose_template`
uses it in preference to the position/keyword heuristic when present and
valid — overriding even the "first slide → title_reveal" rule, since an
explicit judgment call is a stronger signal than position — and falls
back to the heuristic for decks analyzed before this field existed, or
where it's absent. An invalid `visual_role` value fails
`generate_deck_animation()` loudly (naming the slide and the bad value),
the same "fail loudly, not silently" standard as everything else in this
pipeline — never silently ignored the way a missing field is. 7 new tests
cover the priority ordering and the loud-failure case; `spec.json` now
also records `visual_role_used` per slide for auditability. This improved
selection quality without reopening whether an agent should write GSAP
code — that stays fixed, reviewable, and testable.

**Validation surface that stays true regardless of selection mechanism:**
browser console errors during capture (a bug in a template, or a selector
that doesn't resolve) fail loudly, the same way a missing translated node
ID does today — capturing a silently-broken animation is a worse failure
mode than a script error, because nothing about the output MP4 itself
would look obviously wrong without frame-by-frame review.

### 4.1a Secondary path (optional, deferred): Remotion

`claude-remotion-skill`, `video-shotcraft`, and `remotion.dev/docs/ai/skills`
remain fully deferred per §6 Phase 5 — licensing is no longer the gate (§5
Decision 3, resolved), but the primary GSAP+Playwright path is still
untested, so adopting a second renderer stack is evaluated only after the
primary path has real output to judge against, not before. `video-shotcraft`
was briefly considered for a knowledge-only port into the primary path
(porting its shot-recipe/motion-template *concepts* without its Remotion
*code*) but that was reconsidered and reversed: its shot recipes and motion
templates are implemented as Remotion React/TSX compositions, not documented
as a separate, renderer-independent taxonomy — "port the knowledge" would in
practice mean reverse-engineering Remotion component code to extract
concepts, not adapting a reference doc. Not worth the risk for a primary
path explicitly meant to avoid a Remotion dependency; it now sits fully
alongside the other three Remotion-based projects in this deferred path.

The named shot templates the primary path actually uses
(`title_reveal`/`feature_callout`/`stat_highlight`/`diagram_build`/`closing`,
see `slides/animation_templates.py`) are this project's own design,
informed by general motion-design categorization (`motion_design_principles`
skill) rather than ported from any of the eight evaluated projects.

**Not recommended as a dependency (but noted as reference):**
`story-to-handdrawn-video` (a specific stylistic niche — hand-drawn story
illustration — not a marketing-video fit) and `pixel2motion` (logo-only;
revisit narrowly if/when a brand-mark animation for the title card is
wanted, not for full-deck animation).

### 4.2 Design system (set up)

The GSAP timeline templates in §4.1 need an actual style reference, not
ad-hoc choices per deck (the current PIL renderer's failure mode). Rather
than invent one, tokens were pulled directly from
`ideabosque.ai_website/app/app.css`'s `@theme`/`:root` block — the real,
already-shipping brand system — and written to **`config/design_system.yaml`**
in this repo:

- **Typography**: `Inter` / "IBM Plex Sans" as the sans stack, "JetBrains
  Mono" for anything monospace/technical, and the site's actual type scale
  (64px hero headline down to 13px uppercase labels) mapped onto slide
  roles (title/subtitle/lead/body/label) so a generated timeline picks a
  size by *role*, not by guessing.
- **Color**: the full page/surface/text/brand/accent/border/semantic
  palette (`#0F4D4A` brand primary, `#D87C2C` accent, the warm off-white
  `#F8F5EE` page background, etc.), plus two colors used consistently
  throughout `app.css` but never formally tokenized there (`#9E5519` label
  accent, the dark hero-panel gradient `#173f3b`→`#0a3b38`) — included and
  flagged as informally-sourced rather than silently treated as equal to
  the formal tokens.
  One value **could not be resolved and is left `null` with a TODO**:
  `--radius-lg`, referenced in `app.css` (`.hero-rfq-visual`) but never
  defined in the `@theme` block — likely a Tailwind default, not verified.
- **Spacing/radius/layout**: the site's actual 10-step spacing scale,
  border-radius steps, and max-width breakpoints, copied as-is.
- **Motion**: `app.css` has no formal motion tokens, but its ~30 hover/
  focus/active transitions are consistent enough to read as an intentional
  system once collected: **120ms** for pressed/active feedback, **160ms**
  for most hover/focus transitions, **200ms** for larger surface changes
  (card hovers), always plain `ease-out` — no bounce/elastic/spring easing
  anywhere on the real site. This matters directly for §4.1: GSAP timelines
  built for slide animation should default to the same `ease-out` register
  the brand already uses everywhere else, not introduce a springier motion
  language the rest of the brand doesn't have. Two additional values
  (`slide_enter_ms: 480`, `slide_exit_ms: 320`) are proposed, not derived —
  `app.css` has no slide/video precedent to pull from — and should be
  treated as a starting point for review in Phase 1, not a settled value
  the way everything else in the file is.

This file is pure data — nothing in the pipeline reads it yet. It's the
concrete input Phase 1's timeline template system is meant to consume.

## 5. Decisions

0. ~~Sequential, or independently requestable from scratch?~~ **Resolved:
   sequential — kept as-is.** The animated renderer stays dependent on
   `production.json` from an already-completed `render_slideshow.py` run
   for that language (narration audio + `segment_timing`); it cannot be
   requested "from the beginning" without the standard slideshow existing
   first. This matches the *existing, already-shipped* code's behavior
   (`render_marketing_animation.py` already requires `--production
   <production.json>` and has no TTS/timing logic of its own) and
   `slideshow_video_production/SKILL.md`'s existing wording ("an already
   rendered language"), so this plan changes nothing about that contract —
   it only replaces what happens *after* that input is available (PIL
   frames → captured GSAP animation clips). The alternative considered and
   rejected here: decoupling TTS/timing generation into a shared step both
   renderers call independently, which would allow requesting the animated
   version without ever producing `slideshow.mp4`, at the cost of a real
   refactor (extracting that logic out of `render_slideshow.py`). Revisit
   only if "animation without the static version" becomes an actual,
   recurring request.
1. ~~Scope: replace, or add alongside?~~ **Resolved: replace.** The new
   GSAP+Playwright renderer fully replaces `render_marketing_animation.py`'s
   PIL/numpy approach — no `--style procedural` fallback kept. Trade-off
   accepted: the procedural renderer's one advantage (no Chromium
   dependency, since Pillow/numpy are already in `pyproject.toml`) is given
   up; Playwright/Chromium is already a hard dependency for the rest of the
   pipeline, so this isn't adding a new failure mode, just extending an
   existing one.
2. ~~Should animation extend to `slideshow.mp4` itself, or stay
   marketing-only?~~ **Resolved, for now: stays marketing-only.**
   `render_slideshow.py` (the canonical, pipeline-tracked, already-published
   9-language deliverable) is not touched by this plan. Reasoning: it's the
   thing that actually ships today, and the new animated approach is
   unbuilt and unproven — replacing a working, validated pipeline with an
   unproven one in the same change would be the wrong order of operations.
   **This is deferred, not eliminated as an option** — once the animated
   renderer has real production mileage, revisit whether it's good enough
   (and whether the narration-pacing-vs-animation-timing reconciliation
   this would require, not yet designed, is worth doing) to become the
   canonical generator.
3. ~~Remotion licensing.~~ **Resolved: single-user license scope, not a
   blocker.** Confirmed this operates under one user license — Remotion's
   free tier already covers an individual (see §2's license summary), so
   the secondary Remotion path in §4 needs no purchase to prototype or use
   if it's ever reached. Re-check this if the org's structure changes (more
   than 3 employees on a for-profit entity would require a paid Company
   License), but it is not a blocker today.
4. ~~Node.js in the stack.~~ **Resolved: acceptable.** A second language
   runtime alongside Python is fine. This removes the only reason §4's
   HyperFrames-as-backend fallback or the Remotion secondary path would
   have needed extra justification — both can be adopted purely on
   engineering merit (does it produce a better result / save more effort
   than it costs) without a stack-purity objection in the way.
5. ~~Brand/style guide.~~ **Resolved: derive it from
   `ideabosque.ai_website`'s real design system.** See §4.2 — tokens were
   pulled directly from that project's `app/app.css` `@theme`/`:root` block
   (colors, typography, spacing, radii) plus its actually-used transition
   durations (not invented), and written to
   `config/design_system.yaml` in this repo.

## 6. Proposed phased plan

| Phase | Work | Rough size |
|---|---|---|
| 0 | Add `gsap-skills` + `motion-design-skill` to `.claude/skills/`; spike one hand-authored animated HTML slide using `config/design_system.yaml`'s tokens, confirm Playwright's `record_video_dir` captures it cleanly at target fps/resolution, and confirm a deliberately-broken timeline produces a detectable console error | ~1 day |
| 1 | Design the GSAP timeline template system (enter/hold/exit, keyed by slide *role* via structural CSS classes, not content keywords or per-language text) against the design system in §4.2 — own design (§4.1a), not ported from any evaluated project; resolve the `--radius-lg` TODO and the two proposed (not brand-derived) `slide_enter_ms`/`slide_exit_ms` values as part of this | ~1 week |
| 2 | Build the `msv slides generate-animation` step (§4.1) — Agent 1 generates the timeline once per deck, cached under `state/<run_id>/analysis/slides/animation/`; add console-error capture as a validation gate | ~1 week |
| 3 | Extend `slides/render.py` with the per-language video-capture mode, applying the one cached animation to each language's translated deck | ~3-4 days |
| 4 | Rewrite `render_marketing_animation.py` to concatenate captured clips instead of PIL frames, reusing existing narration/caption/mux logic; update `slideshow_video_production` / `slide_video_orchestration` SKILL.md and the two agent `.md` files to describe the new mechanism | ~3-5 days |
| 5 (deferred, not scheduled) | Only after Phase 4 has real production mileage: revisit Decision 2 in §5 (whether this should become the canonical `slideshow.mp4` generator) | unscoped — gated on evidence, not on a date |

No pipeline code has changed as part of this plan — `config/design_system.yaml`
is the one concrete artifact created so far, and it's inert data nothing
reads yet. All six decisions in §5 are resolved; Phase 0 can start
immediately.
