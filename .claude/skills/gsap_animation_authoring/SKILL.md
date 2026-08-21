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

## Core GSAP rules for this pipeline

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
that module's docstring for the full property list). A timeline template
in `slides/animation_templates.py` reads these via
`getComputedStyle(document.documentElement)` at animation-build time, not
by embedding literal values in the generated JS. This is what makes one
generated `animation.js` stay correct if `design_system.yaml` is ever
revised — the timeline structure doesn't change, only the values it reads.

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
   writes the reusable bundle once per deck — `animation_runtime.js`
   (the actual timelines, this skill's "how"), the vendored
   `gsap.min.js`, and `design_tokens.css` (the design-system CSS custom
   properties) — into `state/<run_id>/analysis/slides/animation/`. It
   does **not** touch any deck's HTML.
2. **`slides/render.py`'s `_inject_animation_assets`** (called from
   `render_deck_animation_clips`, at capture time) copies those three
   files into that language's already-translated deck directory and
   injects, before `</head>` in every `slide_NNN.html`:
   ```html
   <style>html{visibility:hidden}</style>
   <link rel="stylesheet" href="design_tokens.css">
   <script>window.__ANIMATION_TEMPLATE__="feature_callout";</script>
   <script src="gsap.min.js"></script>
   <script src="animation_runtime.js" defer></script>
   ```
   idempotently, by marker comment — the same pattern
   `slides/cjk_fonts.py` uses for font overrides, so the two don't
   conflict (CJK font injection runs first if both apply to the same
   deck). GSAP itself loads from that locally-vendored copy (no CDN —
   the deck must render identically offline and CI-deterministically).

**The inline `html{visibility:hidden}` matters, and isn't optional.**
Without it, the browser paints the slide at its normal/final CSS state
for a frame or more before `animation_runtime.js` runs — a visible flash
at the start of every captured clip (this was shipped, found in real
output, and fixed — not a theoretical concern). `run()`'s last line,
`document.documentElement.style.visibility = "visible"`, reveals the
page synchronously right after the timeline is constructed — GSAP's
`.from()`/timeline creation applies "from" starting values synchronously,
before that line runs, so the first visible paint already shows every
animated element at its starting state. If a template dynamically
creates new elements (e.g. `drawAccentLine`'s decorative underline), they
inherit this same guarantee automatically as long as they're created
*inside* the template function GSAP calls, before `run()` returns.

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
