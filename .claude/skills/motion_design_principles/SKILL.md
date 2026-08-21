---
name: motion-design-principles
description: Implementation-agnostic motion design judgment (timing, easing, choreography) for deciding what a slide's animation should look like, before writing the GSAP code. Use alongside gsap-animation-authoring when generating or reviewing a deck's animation timeline — this skill covers the "should," that one covers the "how."
---

# Motion Design Principles Skill

Project-authored guidance, informed by classical animation timing
principles and by
[lottiefiles/motion-design-skill](https://github.com/lottiefiles/motion-design-skill)'s
public README (fetched during research for
`docs/marketing-animation-pipeline-plan.md`) — **not a verbatim copy of
that repo's files**, which weren't directly accessible during this build.
This is this project's own distilled version, scoped to picking and tuning
a shot template from `slides/animation_templates.py`, not general UI
animation.

## Purpose

`gsap_animation_authoring` covers *how* to write correct GSAP code.
This skill covers the judgment call that comes first: *which* shot
template fits a given slide, and how its timing should be tuned. Getting
this wrong produces a technically-correct animation that still looks
generic or fights the content — a real, distinct failure mode from a
broken selector.

## Choosing a shot template (see `slides/animation_templates.py`)

Pick by the slide's **role in the narrative**, not by trying to match its
visual content:

| Slide role | Template | When |
|---|---|---|
| Deck opener | `title_reveal` | Slide 1, or any slide whose `slide_analysis.json` role is "title" |
| Single key point, minimal supporting text | `feature_callout` | A slide making one claim with a short supporting line |
| A number/metric is the point | `stat_highlight` | A slide whose primary content is a number (percentage, count, duration) |
| Structural/architecture content | `diagram_build` | A slide with a node/flow/system diagram (already has `.slide-diagram` markup from the deck author) |
| Deck closer / CTA | `closing` | The last slide, or one containing a call-to-action |
| Everything else | `feature_callout` (default) | The safe default — don't force an ill-fitting template onto content that doesn't match any of the above |

Do not invent a new template per deck. A small, consistent set of
templates reused across every deck is the entire point (§4.1a of the
plan) — the failure mode this replaces is `render_marketing_animation.py`'s
old per-deck hardcoded keyword matching, and a new one-off template per
slide just reintroduces that same problem one level up.

## Timing discipline

- **Entrance beats should feel inevitable, not delayed.** Start the first
  element's animation immediately (`t=0` on the timeline) — don't open
  with dead air. A slide that begins its narration but hasn't started
  animating yet reads as broken, not as building anticipation.
- **Stagger, don't synchronize, multi-element entrances.** Three bullet
  points animating in simultaneously read as a slide of text appearing;
  the same three staggered by ~80-120ms each read as a sequence being
  revealed — use GSAP's `stagger` option on the timeline, sourced from
  `config/design_system.yaml: motion.duration_fast_ms` as the stagger
  interval, not a separately invented number.
- **The entrance is the performance; the hold is silence.** Once
  `slide_enter_ms` (design system default 480ms) completes, nothing should
  move again until the slide ends — see `gsap_animation_authoring`'s "leave
  elements in their final state" rule. A slide that keeps subtly animating
  throughout its full narration-driven hold (which can run 10-20+ seconds)
  reads as distracting, not polished.
- **Match entrance energy to content weight.** A stat/number slide can
  afford a slightly more emphatic entrance (`stat_highlight`'s permitted
  `back.out` overshoot, see `gsap_animation_authoring`) because a single
  large number reads fast and has room for a flourish; a slide with several
  lines of text needs a calmer, faster-settling entrance so the animation
  doesn't fight the viewer's reading time.

## Effects beyond a plain fade

Each template's entrance is more than opacity+y now (`slides/assets/animation_runtime.js`):

- **`stat_highlight`** counts its number up from 0 to the parsed target
  value (handles `"40%"`, `"3x faster"`, `"$1.2M saved"` — prefix/suffix
  and decimal precision are preserved), rather than just popping in. Falls
  back to a plain scale-in if the element's text has no parseable number —
  never leaves it blank.
- **`diagram_build`** and, implicitly, any template with `els.body`
  content: element selection now tries a *repeated-sibling-group*
  heuristic before falling back to semantic tags — most real decks express
  a card/row/layer grid as N sibling `<div>`s sharing one class (e.g.
  `.layer-stack > .layer`), not `<li>`/`<p>`, so this materially widens
  which decks actually get a staggered per-item reveal instead of no
  animation firing at all (see `gsap_animation_authoring/SKILL.md`'s
  "Injection point" for why this matters more than it sounds).
- **`title_reveal`/`feature_callout`/`diagram_build`/`closing`** draw a
  short accent-colored underline beneath the headline after it settles —
  a decorative-only beat (a DOM failure here is swallowed, never breaks
  the timeline). `stat_highlight` deliberately skips this, keeping focus
  on the number.

## Choreography ordering within a template

Within any multi-element template, animate in this order unless the
template's own definition says otherwise: **background/frame → label or
kicker → headline → supporting content → diagram/visual detail.** This
mirrors how a presenter would actually reveal the slide's content if
speaking it live — frame first (orients the eye), then the claim, then the
evidence. Reversing this order (e.g. diagram before headline) makes the
viewer parse detail before they have the context to interpret it.

## What this skill does not cover

- Whether a slide *should* be animated at all vs. left as the static
  frame from `render_slideshow.py` — that's `render_slideshow.py`'s
  output, unchanged, and out of scope entirely (see plan §5 Decision 2).
- Sound design / music beat-matching — noted in the plan (§4.1a) as a
  separately-scoped future capability, not part of this pipeline today.
- Anything about narration content or translation quality — that's
  `slide_deck_localization`'s job, upstream of this skill entirely.
