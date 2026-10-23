---
name: gsap-animation-authoring
description: GSAP (GreenSock Animation Platform) authoring guidance for generating slide-deck animation timelines. Use when writing or reviewing the GSAP JS/CSS injected into a translated slide deck by `msv slides generate-animation` (marketing_animation_pipeline_plan §4.1/§4.1a) — never for animating anything outside that pipeline.
---

# GSAP Animation Authoring Skill

Project-authored guidance, informed by GreenSock's own documentation and by
[greensock/gsap-skills](https://github.com/greensock/gsap-skills)'s public
README (fetched during research for
`docs/marketing-animation-pipeline-plan.md`) — **not a verbatim copy of that
repo's files**, which weren't directly accessible during this build. Treat
this as this project's own distilled version of the same authoring
discipline, scoped tightly to one job: writing correct, brand-consistent
GSAP timelines for `msv slides generate-animation`
(`slides/animation_templates.py` / `slides/generate_animation.py`).

## Purpose

When an agent (or `slides/generate_animation.py`'s default heuristic) picks
a named timeline template for a slide, the actual GSAP code that HyperFrames
seeks frame by frame in headless Chrome must be correct, deterministic, and cheap to
verify — a silently-broken selector is a worse failure than a script error
(see `marketing_animation_pipeline_plan.md` §4.1's validation note). This
skill exists to keep that code disciplined.

**Two different jobs, most of the time only the first applies:**

1. **Adding or tuning a template** — the common case. Templates
   (`title_reveal`, `feature_callout`, `stat_highlight`, `diagram_build`,
   `closing`, `quote_testimonial`, `comparison_versus`, `timeline_roadmap`,
   or a new one) are declarative data in `config/animation_templates.yaml`,
   not JS — see "Template config schema" below. Editing that file is the
   whole job; no code changes.
2. **Adding a new *effect primitive*** — rare. Only needed when a template
   or a motion design needs a kind of motion the existing effects can't
   express as parameters. This means a real JS change in
   `slides/assets/animation_runtime.js`'s `EFFECTS` registry, plus the
   matching Python-side name: `animation_templates.py`'s `_KNOWN_EFFECTS`
   for templates, and `slides/motion_design.py`'s `EFFECT_PARAMS` (with the
   parameters a design may give it) for motion designs. Add a case to
   `tests/test_motion_design_runtime.py`'s seek-safety test. The rules
   below (rule 1 especially) apply to that JS, not to the YAML.

**Motion designs** (`motion-design/v1`, plan C3) are per-deck JSON that the
same step runner plays; `slides/motion_design.py` validates them and turns
them into runtime steps. What differs from templates: a design step names a
`target` (`node`, `group`, `selector` or `role`) and fails loudly when it
matches nothing, since the design was written for this deck; a step's `id`
becomes a timeline label, so `"hdr+=0.2"` really means 0.2s after `hdr`
starts; durations may be seconds. Designs have their own effects on top of
the templates': `text_split` (word, char, line), `draw_svg`, `highlight`,
`emphasis`, `path_connect` and `camera`.

## Template config schema

`config/animation_templates.yaml` — see that file's own header comment for
the authoritative field reference; summarized here:

- **Top-level key** = template name. Selected per-slide by `visual_role` in
  `slide_analysis.json`, a `--spec` override, or `animation_templates.py`'s
  position/keyword heuristic.
- **`steps`** = an ordered list played into one `gsap.timeline()` by the
  generic engine (`runTemplateSteps` in `animation_runtime.js`). Each step:
  - `role` — one of `title, subtitle, body, diagram, stat, cta, nodes`
    (an `animation_runtime.js` `roleElements()` key), or a list tried in
    order, first non-empty wins (e.g. `[stat, title]`).
  - `effect` — `reveal` (fade/slide/scale, singular or array target,
    optional `stagger`), `accent_line` (drawn underline after the target),
    or `count_up` (number count-up, regex-parsed from the target's text).
    Any other name fails loudly at bundle-generation time
    (`AnimationTemplateConfigError`), not silently at render time.
  - `duration` — a token (`fast/base/slow/slide_enter/slide_exit`)
    resolved against `config/design_system.yaml`'s motion values, never a
    literal number.
  - `position` / `position_if_first` — GSAP timeline position parameter;
    the `_if_first` variant only applies when this step turns out to be
    the first one in the template that actually finds an element (earlier
    steps were skipped) — needed because a relative position like
    `">-0.1"` isn't meaningful with nothing before it yet.
  - `min_count`, `id`, `skip_if_ran` — support the "N repeated cards, else
    one fallback element" either/or pattern (see `diagram_build`'s
    `nodes` → `diagram` fallback).
- A step whose `role` resolves to nothing (element missing) is skipped,
  same "missing optional element ≠ broken selector" principle as before
  (self-check item 5).

Adding a sixth template, or changing how a card grid staggers in, is
normally just a new/edited entry in that YAML file — verified by this
project's own tests in `tests/test_animation_templates.py` and a real
HyperFrames render (`tests/test_hyperframes_engine.py`), not by
hand-reading JS.

## Core GSAP rules for this pipeline

These rules govern the fixed engine and effect primitives in
`animation_runtime.js` — the code most template work never touches (see
"Purpose" above). They still matter when adding a genuinely new effect.

- **`gsap.timeline()`, not ad hoc `gsap.to()` calls.** Every slide's
  animation is one timeline so its total duration is knowable up front
  (`timeline.duration()`). Each slide's on-screen length is its narration;
  the timeline has to fit inside it (beat positions and exits are laid out
  against the slide's real duration).
- **Target structural classes, never text content or per-language
  selectors.** `.slide-title`, `.slide-bullets li`, `.slide-diagram` — the
  same principle that makes node-ID translation survive independently of
  wording (see the localization skill). A selector keyed to English text
  breaks the moment a different language's translation lands in that
  element. Real decks predate this feature and rarely define those exact
  classes, so `animation_runtime.js`'s `pickEl`/`pickAll` fall back through
  a **repeated-sibling-group heuristic** (find the largest set of ≥2
  direct siblings sharing one class — how most decks actually express a
  card/row/layer grid, e.g. `.layer-stack > .layer`) before falling back
  further to plain semantic tags (`h1, h2` / `li, p`). All three tiers are
  still structural, never text-content-based, so this doesn't weaken the
  rule above — it just widens what counts as "structural" to match how
  real decks are actually written.
- **Animate transform and opacity only** (`x`, `y`, `scale`, `rotation`,
  `opacity`) — never `width`/`height`/`top`/`left` for motion. This is a
  performance rule (transform/opacity are compositor-only, everything else
  triggers layout) that matters even more here than in a normal browser,
  because every frame is rendered from a headless browser, and a
  layout-heavy timeline is slower to render and can reflow text between
  frames.
- **Every tween needs an explicit `duration` and `ease`.** Never rely on
  GSAP's bare defaults (`duration: 0.5, ease: "power1.out"`) silently —
  pull both from `config/design_system.yaml: motion` so every deck's
  animation moves at the same brand-consistent pace (see "Design system
  binding" below).
- **No infinite repeats, no `yoyo`, no scroll-triggered anything.**
  ScrollTrigger, Draggable, and infinite/repeating tweens all assume a live
  interactive page. This pipeline renders a fixed-length, non-interactive
  video. A finite `repeat` + `yoyo` is seek-safe, but the playful style
  deliberately avoids continuous bobbing (it read as shaking). Every
  timeline must have a finite, computable end.
- **Leave elements in their final animated state — don't `clearProps` or
  reverse.** A slide holds its final animated state for the rest of its
  narration-driven duration for free, because GSAP leaves transform/
  opacity at their end values once the timeline completes. Calling
  `.clearProps()` or `.reverse()` breaks that and snaps the slide back to
  its pre-animation state mid-slide. (The playful `exit` effect is the one
  deliberate exception: a fade just before the cut.)
- **Must render correctly when seeked, not only when played.** Seek mode
  (`window.__MOTION_MODE__ = "seek"`) builds the same timeline paused and a
  renderer seeks it frame by frame, as HyperFrames does for every video.
  - **Never write the DOM from `onUpdate` (or any callback).** GSAP's
    `seek()` suppresses callbacks by default, so a callback-driven effect
    silently never changes under a seeking renderer; this is how
    `count_up` broke. Tween a property whose setter writes the DOM
    instead (see `animateCountUp`).
  - **Apply start values at build time.** Use `.from()`/`.fromTo()`, which
    render their start state immediately; a plain `.to()` on a proxy shows
    the source state until it first renders, so t=0 depends on seek history.
  - **No wall clock, no unseeded `Math.random()`, no per-tick
    accumulation.** Every value must be a pure function of playhead time.

  `tests/test_motion_runtime_seek.py` seeks out of order and mid-tween; add
  a case there for any new effect primitive.
- **No external asset loads inside the timeline's own logic.** Fonts and
  the GSAP library itself load once, before the timeline starts (see
  "Injection point" below) — a tween that waits on an image/font load
  mid-timeline makes frames depend on load timing, so the same frame could
  render differently twice.

## Design system binding

Never hardcode a color, size, or duration. Read them from
`config/design_system.yaml` (already set up — see
`docs/marketing-animation-pipeline-plan.md` §4.2) via the CSS custom
properties `slides/generate_animation.py` injects alongside the timeline
(`--ds-color-brand-primary`, `--ds-motion-duration-base-ms`, etc. — see
that module's docstring for the full property list). `animation_runtime.js`'s
`readTokens()` reads these via `getComputedStyle(document.documentElement)`
at animation-build time (once per slide, before the timeline is built), not
by embedding literal values anywhere — a template's `duration`/`stagger`
YAML fields are token *names* (`"base"`, `"fast"`, ...), resolved against
this same `ds` object by the generic engine. This is what makes the whole
bundle stay correct if `design_system.yaml` is ever revised — nothing
generated needs to change, only the values it reads.

Default easing for anything that isn't an explicit dramatic beat:
`"power2.out"` — GSAP's closest equivalent to the plain CSS `ease-out` the
real site's brand already uses everywhere (§4.2's motion research: zero
bounce/elastic/spring easing anywhere on `ideabosque.ai_website`). Do not
reach for `"elastic"`, `"bounce"`, or `"back"` eases by default — they
introduce a motion register this brand doesn't otherwise have. A stat
highlight's *number* count-up is the one template where a slight
`"back.out(1.2)"** overshoot on settle is acceptable (§4.1a's "stat
highlight" shot) — everywhere else, stay on `power*.out`.

## Injection point

1. **`slides/generate_animation.py`** (`msv slides generate-animation`)
   writes the deck's bundle once: `spec.json` (each slide's template),
   `design_tokens.css` (the design-system CSS custom properties), and a
   snapshot of the runtime files. It does **not** touch any deck's HTML.
2. **The HyperFrames engine** (`production/motion/hyperframes_engine.py`)
   builds one project per language render:
   - `index.html` loads, once for every slide: GSAP and
     `animation_runtime.js` from the **installed package** (never a
     bundle's stale copy), `templates_config.js` generated fresh from the
     configured style's YAML, and the bundle's `design_tokens.css`;
   - each translated slide becomes a `<template>` sub-composition whose
     inline script calls `window.__motionRunSlide(rootEl, {slideId,
     template, duration})`. That builds the slide's timeline paused,
     resolving roles inside that slide's root only (all slides share one
     page), and registers it in `window.__timelines` for HyperFrames to
     seek.
3. **`slides/render.py`'s `_inject_animation_assets`** wires a bundle into
   standalone slide pages (used by `msv slides extract-roles` in seek
   mode). There, an inline `html{visibility:hidden}` keeps the page
   invisible until `run()` has applied the timeline's starting values, so
   the first paint never shows a slide at its final state.

Effects that create elements (e.g. `accent_line`'s underline) must do so
inside the effect function, at build time, so every seek sees the same DOM.

## Self-check before treating a generated timeline as done

1. Every tween has an explicit `duration` and `ease`.
2. No selector references literal English text.
3. No `ScrollTrigger`/`Draggable`/repeat/yoyo/scroll dependency.
4. `timeline.duration()` is a finite, sane number (reject anything under
   0.5s as almost certainly a bug, or over ~6s as probably meant to be a
   "hold," not an entrance animation — holds happen for free for the rest
   of the slide's narration, not via a longer timeline).
5. The timeline builds without a script error (enforced mechanically:
   HyperFrames' `check` fails the whole render on any slide's script error,
   naming the slide), but check it by eye first. A caught-and-swallowed
   error inside a `try/catch` would pass that check while still producing
   a broken visual; validation's "animation actually happened" check is the
   backstop.
