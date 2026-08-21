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
a named timeline template for a slide, the actual GSAP code executed inside
the captured Chromium page must be correct, deterministic, and cheap to
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
   needs a kind of motion the existing three effects (`reveal`,
   `accent_line`, `count_up`) can't express as parameters. This means a
   real JS change in `slides/assets/animation_runtime.js`'s `EFFECTS`
   registry, plus a matching Python-side name in
   `animation_templates.py`'s `_KNOWN_EFFECTS`. The rules below (rule 1
   especially) apply to that JS, not to the YAML.

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
Playwright capture smoke test, not by hand-reading JS.

## Core GSAP rules for this pipeline

These rules govern the fixed engine and effect primitives in
`animation_runtime.js` — the code most template work never touches (see
"Purpose" above). They still matter when adding a genuinely new effect.

- **`gsap.timeline()`, not ad hoc `gsap.to()` calls.** Every slide's
  animation is one timeline so its total duration is knowable up front
  (`timeline.duration()`) — the capture step in `slides/render.py` needs
  this to decide how long to record.
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
  because Playwright is capturing frames from a headless renderer with no
  GPU compositor shortcuts to hide layout thrashing — a layout-heavy
  timeline can visibly stutter in the captured video.
- **Every tween needs an explicit `duration` and `ease`.** Never rely on
  GSAP's bare defaults (`duration: 0.5, ease: "power1.out"`) silently —
  pull both from `config/design_system.yaml: motion` so every deck's
  animation moves at the same brand-consistent pace (see "Design system
  binding" below).
- **No infinite repeats, no `yoyo`, no scroll-triggered anything.**
  ScrollTrigger, Draggable, and infinite/repeating tweens all assume a live
  interactive page. This pipeline captures a fixed-length, non-interactive
  video — a repeating tween would either freeze mid-cycle at an arbitrary
  captured frame or need external synchronization logic. Every timeline
  must have a finite, computable end.
- **Leave elements in their final animated state — don't `clearProps` or
  reverse.** The capture step relies on this: it plays the timeline once,
  then keeps recording for the slide's full narration-driven duration
  (§4.1's "hold" phase happens for free because GSAP just leaves
  transform/opacity at their end values once the timeline completes,
  unless code explicitly reverts them). Calling `.clearProps()` or
  `.reverse()` at the end of a timeline breaks this "hold" assumption and
  will visibly snap the slide back to its pre-animation state partway
  through the recording.
- **No external asset loads inside the timeline's own logic.** Fonts and
  the GSAP library itself load once, before the timeline starts (see
  "Injection point" below) — a tween that waits on an image/font load
  mid-timeline makes the total duration non-deterministic, which breaks
  the capture step's duration calculation.

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

Two separate steps, not one — this replaces an earlier, inaccurate draft
of this section written before Phase 2/3 were actually implemented:

1. **`slides/generate_animation.py`** (`msv slides generate-animation`)
   writes the reusable bundle once per deck — `animation_runtime.js` (the
   fixed generic engine + effect primitives, this skill's "how"),
   `templates_config.js` (`window.__ANIMATION_TEMPLATES__`, the actual
   per-template step data, generated fresh each time from
   `config/animation_templates.yaml` — this skill's "what"), the vendored
   `gsap.min.js`, and `design_tokens.css` (the design-system CSS custom
   properties) — into `state/<run_id>/analysis/slides/animation/`. It
   does **not** touch any deck's HTML.
2. **`slides/render.py`'s `_inject_animation_assets`** (called from
   `render_deck_animation_clips`, at capture time) copies those four
   files into that language's already-translated deck directory and
   injects, before `</head>` in every `slide_NNN.html`:
   ```html
   <style>html{visibility:hidden}</style>
   <link rel="stylesheet" href="design_tokens.css">
   <script>window.__ANIMATION_TEMPLATE__="feature_callout";</script>
   <script src="templates_config.js"></script>
   <script src="gsap.min.js"></script>
   <script src="animation_runtime.js" defer></script>
   ```
   idempotently, by marker comment — the same pattern
   `slides/cjk_fonts.py` uses for font overrides, so the two don't
   conflict (CJK font injection runs first if both apply to the same
   deck). GSAP itself loads from that locally-vendored copy (no CDN —
   the deck must render identically offline and CI-deterministically).
   `templates_config.js` and the inline `__ANIMATION_TEMPLATE__` name are
   both plain (non-`defer`) scripts, so both are guaranteed to run before
   the deferred `animation_runtime.js` reads them in `run()`.

**The inline `html{visibility:hidden}` matters, and isn't optional.**
Without it, the browser paints the slide at its normal/final CSS state
for a frame or more before `animation_runtime.js` runs — a visible flash
at the start of every captured clip (this was shipped, found in real
output, and fixed — not a theoretical concern). `run()`'s last line,
`document.documentElement.style.visibility = "visible"`, reveals the
page synchronously right after the timeline is constructed — GSAP's
`.from()`/timeline creation applies "from" starting values synchronously,
before that line runs, so the first visible paint already shows every
animated element at its starting state. If an effect dynamically creates
new elements (e.g. `accent_line`'s decorative underline), they inherit
this same guarantee automatically as long as they're created *inside* the
effect function `runTemplateSteps` calls, before `run()` returns.

## Self-check before treating a generated timeline as done

1. Every tween has an explicit `duration` and `ease`.
2. No selector references literal English text.
3. No `ScrollTrigger`/`Draggable`/repeat/yoyo/scroll dependency.
4. `timeline.duration()` is a finite, sane number (reject anything under
   0.5s as almost certainly a bug, or over ~6s as probably meant to be a
   "hold," not an entrance animation — holds happen for free via capture
   duration, not via a longer timeline).
5. The browser console is silent when the timeline plays (this is
   mechanically enforced by `slides/render.py`'s capture step, which fails
   the whole render on any console error — see
   `marketing_animation_pipeline_plan.md` §4.1's validation note — but
   check it by eye first; a caught-and-swallowed error inside a `try/catch`
   would pass that mechanical check while still producing a broken visual).
