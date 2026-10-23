# Remotion engine project (plan B5, Phase 3)

The deck-faithful Remotion mode: one `Slideshow` composition with one
`<Sequence>` per clip (title card, then each slide). Each clip shows the
translated slide page in an iframe and, on every frame, seeks that page's
paused GSAP timeline to `frame / fps` - the same seek-mode runtime
HyperFrames renders. Transitions between slides play on the iframes
(`src/transitions.ts`), matching the runtime's HyperFrames versions.

Nothing here decides timing or content: `remotion_engine.py` builds the
pages and writes the input props (clip frames, transitions) from
`production/motion/clips.py`, then runs `render.mjs`.

- `src/` - the composition (`Root.tsx`, `Slideshow.tsx`, `SlideFrame.tsx`,
  `transitions.ts`, `types.ts`).
- `render.mjs` - bundles and renders a silent H.264 video. Called by
  Python only; it prints one JSON line.
- `ensure-browser.mjs` - downloads Remotion's pinned chrome-headless-shell
  into `node_modules/.remotion`; `msv motion install` runs it so renders
  never download anything.

The "rebuilt look" React templates (Open decision D4) are deferred to
Phase 8. Licensing: Remotion is free for individuals and companies of up
to 3 people; see plan B5 before that changes.
