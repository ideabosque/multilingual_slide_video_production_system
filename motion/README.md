# motion/ - the Node toolchain (plan B3 #3)

The pinned Node packages behind the two motion engines in
`src/multilingual_slide_video_agent/production/motion/`: HyperFrames
(`hyperframes`, whose projects are generated per render - see
`hyperframes/README.md`) and Remotion (the composition project in
`remotion/`).

Rules (from the plan, B3 #3 "Node toolchain, pinned and offline-capable"):

- `package.json` pins **exact** versions - no `^`/`~` ranges; the
  `package-lock.json` is committed. New versions must be at least two
  weeks old.
- Python runs these packages via `subprocess` from `motion/node_modules` -
  **never** an unpinned `npx <pkg>` (no silent upgrades, no supply-chain
  drift).
- `msv motion install` runs `npm ci` here (installs exactly what the
  lockfile pins), then downloads Remotion's chrome-headless-shell into
  `node_modules/.remotion`, so a Remotion render downloads nothing.
  HyperFrames does look up some font families on Google Fonts while
  rendering (plan status block).
- `msv motion doctor` reports Node (>= 22), ffmpeg/ffprobe, Playwright's
  Chromium, each engine's `check_available()`, and the Remotion license
  reminder.
- `pyproject.toml` stays Python-only: a missing Node toolchain only
  disables the animated engines; the static slideshow fallback and every
  other `msv` command work without this directory.
