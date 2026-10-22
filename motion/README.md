# motion/ - the Node toolchain (plan B3 #3)

This directory hosts the HyperFrames composition project (`hyperframes/`,
built in Phase 2b) and the Remotion project (`remotion/`, built in Phase 3)
behind the engine seam in `src/multilingual_slide_video_agent/production/motion/`.

Rules (from the plan, B3 #3 "Node toolchain, pinned and offline-capable"):

- `package.json` pins **exact** versions - no `^`/`~` ranges; the
  `package-lock.json` is committed.
- Python invokes binaries from `motion/node_modules/.bin/` via
  `subprocess` - **never** an unpinned `npx <pkg>` (no silent upgrades, no
  supply-chain drift, no network access at render time).
- `msv motion install` runs `npm ci` here (installs exactly what the
  lockfile pins).
- `msv motion doctor` reports Node version (>= 22 required by HyperFrames),
  ffmpeg/ffprobe, Playwright's Chromium, and each engine's
  `check_available()`.
- `pyproject.toml` stays Python-only: a missing/unknown Node toolchain only
  disables the two Node engines; the Playwright path and every other `msv`
  command work without this directory.