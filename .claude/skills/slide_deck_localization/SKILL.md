---
name: slide-deck-localization
description: Slide analysis and localization skill for Agent 1. Reads an original English HTML slide deck (via its parsed text nodes and rendered screenshots), analyzes what each slide shows, and produces per-language slide-text translations, narration, and short highlight captions while preserving product/technical terminology. Use when a new source deck needs slide analysis and multilingual scripts before slideshow production can run.
---

# Slide Deck Localization Skill

## Purpose

Understand what each slide in the original English HTML deck shows and
turn that understanding into structured, machine-readable translations,
narration, and captions for every configured language — the input Agent 2
needs to produce localized slideshow videos.

## Responsibilities

- Parse the original deck's HTML to identify every translatable text node
  and assign it a stable ID (`msv slides extract-text`).
- Analyze the deck's actual rendered appearance via screenshots
  (`msv slides render-images`) — Claude cannot visually interpret raw
  HTML/CSS any more than it can play video, so the rendered PNGs are the
  only view into what a slide actually looks like.
- Identify what each slide shows and its key point; write a
  language-independent `slide_analysis.json`.
- Write a narration script per slide in a **confident, benefit-driven
  marketing voiceover** tone — not a dry, minimal description of what's on
  screen (see "Narration voice" below).
- Write a short **highlight** caption per slide — a label/fragment
  distilling the slide's key point, not a transcript of the narration
  (see "Caption vs narration" below).
- Write one short, localized **marketing title** for the whole deck (see
  "Marketing title card" below).
- Translate every text node identified in the manifest, in place by node
  ID, so Agent 2 can apply the translation back into the original HTML
  without re-parsing or guessing which element changed.
- Localize slide text, narration, captions, and the title independently
  for every language in `SUPPORTED_LANGUAGES`, from the same slide
  analysis — not by translating one language's output into another.
- Preserve terminology from `config/terminology.yaml` (and any
  per-project additions) — company/product names, acronyms, domain terms.
- Tag which preserved terms apply to each slide so Agent 2 can enforce
  them before spending on TTS.

### Caption vs narration — they are NOT the same text

Same rule as the video-source sibling project, and just as important
here: `narration` is what the voice says; `caption` is a short on-screen
label of the key point, closer to a headline than a sentence. Writing
`caption` as a copy (or near-copy) of `narration` is a bug: a long
unwrapped line overflows the slide, and it reads like a transcript dump
instead of a highlight. Budget: captions should stay under
`config/video.yaml: captions.max_chars_soft_limit` (default 90
characters) — `msv slides validate` warns (not errors) past that, and
warns separately if `caption == narration`. This budget applies to the
caption only — it is not a reason to keep the narration terse too (see
"Narration voice").

### Narration voice: marketing, not a slide-reading log

Narration is the deck's sales voice-over, not a neutral read-aloud of the
slide's on-screen bullets. Write it the way a confident presenter would
walk through the deck live: lead with the value or outcome, not just
what's written on the slide; use active, persuasive phrasing; it is fine
— expected — to add a short phrase of color or benefit framing that isn't
literally on screen, as long as it stays accurate to what the slide shows
and doesn't drift into unsupported claims.

### Narration pacing — no fixed window to fit

Unlike the video-source project's scene-anchored narration, a slide has
no pre-existing timeline to fit into or overrun — **the slide's on-screen
duration is derived entirely from how long its own narration takes to
speak** (plus a short pause; see the `slideshow_video_production` skill).
This removes the "budget to spend, don't overrun a window" concern
entirely: write narration to the length the content actually deserves —
a dense slide can run longer, a simple one shorter — rather than padding
or trimming to hit a target duration. The only pacing discipline that
still matters is *per-slide-relative*: an outlier slide whose narration
runs dramatically longer than every other slide's is usually a sign its
on-screen text/bullets are trying to carry too much and should be split
across two slides upstream (a deck-authoring concern, not something to
fix by cutting narration Agent 1 would otherwise write in full).

### Marketing title card

Every deck gets one short, localized, punchy title — the equivalent of a
YouTube title, shown as a prominent title card near the start of the
slideshow (Agent 2 renders it in a distinct, larger style from regular
captions; see `config/video.yaml: title_card`). Keep it well under 100
characters, natural for the target language (not a literal translation of
the English draft — see the youtube_video_publishing skill's "natural,
not literal" guidance, the same principle applies here).

## Required inputs

| Input | Description |
|---|---|
| `run_id`, `project_id` | From Agent 4 |
| `source_deck` | Path to the clean original deck directory (`deck/slide_001.html`, ...) |
| `languages` | Target language codes (defaults to `SUPPORTED_LANGUAGES`) |
| `project` (optional) | A project manifest JSON with domain context and, under a `terminology` key, extra `always_preserve` terms and `forbidden_terms` (keyed by language, `"*"` for all) layered on top of `config/terminology.yaml` |

## Generated outputs

```
state/<run_id>/analysis/
├── slides/manifest.json                 # msv slides extract-text — per-slide node IDs + original text
├── slides/source_images/slide_001.png   # msv slides render-images — rendered ORIGINAL English deck
├── slide_analysis.json                  # language-independent per-slide description
├── localization_<language>.json         # per language, one file each
└── validation_<language>.json           # msv slides validate output
```

`slide_analysis.json`:
```json
{
  "project_id": "product-launch-deck",
  "run_id": "run-20260818-001",
  "source_deck": "/path/to/deck",
  "slides": [
    {"slide_index": 1, "slide_id": "slide_001",
     "slide_description": "Title slide introducing the product.",
     "terminology": ["IdeaBosque"],
     "visual_role": "title_reveal"}
  ]
}
```
`visual_role` is optional but recommended — one of `title_reveal` /
`feature_callout` / `stat_highlight` / `diagram_build` / `closing` /
`quote_testimonial` / `comparison_versus` / `timeline_roadmap` (the
current set in `config/animation_templates.yaml`;
`.claude/skills/motion_design_principles/SKILL.md`'s role table has the
full description of each). It's consumed only by the separate, optional
GSAP marketing-animation pipeline
(`slideshow_video_production/SKILL.md`'s "Optional alternate output") to
pick that slide's shot template — it has no effect on the core
slideshow/translation/publishing pipeline, and omitting it is fine (a
deterministic position+keyword heuristic covers slides without it). Assign
it using the same judgment already going into `slide_description` — this
is not extra research, just one more label on a slide you're already
describing. Get it wrong and the animation pipeline just falls back to
the heuristic; get the *slide_id*/*slide_index* wrong instead and node-ID
translation breaks, which is the actual thing to be careful about here.

`localization_<language>.json` (the Agent 2 handoff contract, README
section 3). Note `title` at the top level, `slide_translations` keyed by
the manifest's stable node IDs (not free-form text matching), and that
`caption` is a short highlight distinct from `narration`:
```json
{
  "language": "zh-TW",
  "run_id": "run-20260818-001",
  "title": "IdeaBosque AI 代理 — 產品發表簡報",
  "segments": [
    {
      "slide_index": 1,
      "slide_id": "slide_001",
      "slide_description": "Title slide introducing the product.",
      "narration": "歡迎來到 IdeaBosque —— 我們用 AI 代理重新定義企業詢價流程，讓您在幾秒鐘內完成過去需要幾天的工作。",
      "caption": "AI 代理重新定義企業詢價流程",
      "terminology": ["IdeaBosque"],
      "slide_translations": [
        {"node_id": "slide_001#n0", "text": "IdeaBosque"},
        {"node_id": "slide_001#n1", "text": "用 AI 重新定義企業詢價流程"}
      ]
    }
  ]
}
```
`slide_index`/`slide_id` must line up 1:1 with `slide_analysis.json`'s
entries so downstream tooling can cross-reference them. Every `node_id`
in `slide_translations` must exist in `slides/manifest.json` for that
slide — Agent 2's `msv slides apply-translations` fails loudly (not
silently) if a node ID doesn't resolve, rather than guessing which
element it meant.

## Available tools

The `msv` CLI (installed via `pip install -e .` at the repo root — see
top-level README.md), group `msv slides`:

- `msv slides extract-text --deck-dir ... --out state/<run_id>/analysis/slides/manifest.json`
  — parses every slide's HTML, assigns each translatable text node a
  stable ID, and records its original text.
- `msv slides render-images --deck-dir ... --out <dir> [--viewport 1920x1080]`
  — drives headless Chromium (Playwright) to screenshot each slide;
  called here against the *original* deck so Claude can see it, and again
  by Agent 2 against each *translated* deck to produce actual video
  frames.
- `msv slides validate --slide-analysis ... --localization ... --language ... --manifest state/<run_id>/analysis/slides/manifest.json [--project ...]`
  — schema + terminology validation, **plus node-ID-coverage validation
  only when `--manifest` is passed** — omitting it silently skips the
  "every manifest node has a translation" check (see "Validation
  criteria" below), so always pass it.
- Claude's own reasoning over the rendered screenshots (and the
  manifest's extracted text) to write slide descriptions, narration, and
  translations — this is the one step in the whole pipeline that is not a
  deterministic script, by nature of the task.

## Configuration

`config/languages.yaml` (which languages exist, their TTS voice profile —
narration tone should match what's declared there), `config/terminology.yaml`
(`always_preserve`, `pronunciation_hints`, `forbidden_terms`),
`DEFAULT_LANGUAGE` / `SUPPORTED_LANGUAGES` in `.env`.

## Execution procedure

1. `msv slides extract-text` the source deck into
   `state/<run_id>/analysis/slides/manifest.json`.
2. `msv slides render-images` the source deck into
   `state/<run_id>/analysis/slides/source_images/`.
3. Read the manifest and rendered screenshots and write
   `slide_analysis.json`: describe each slide, tag terminology, and assign
   each slide a `visual_role` (see "Generated outputs" above — optional
   but recommended, five minutes of extra judgment while the slide's
   already being described).
4. For each target language, write `localization_<language>.json`:
   - a short, localized marketing `title` for the whole deck;
   - per slide, a **narration** passage in a confident marketing
     voiceover tone sized to the slide's actual content (see "Narration
     voice" and "Narration pacing"), a **caption** that is a short
     highlight of the slide (see "Caption vs narration"), and
     **`slide_translations`** — every translatable node from the
     manifest, translated, keyed by its exact `node_id` — both preserving
     tagged terminology exactly and using natural phrasing for the target
     language (not literal word-for-word translation).
5. Run `msv slides validate` for the slide analysis and each language,
   **passing `--manifest state/<run_id>/analysis/slides/manifest.json`**
   so node-ID coverage is actually checked — omitting it skips that
   check silently, not loudly; fix errors, and seriously consider fixing
   warnings (long/duplicate captions) before reporting completion to
   Agent 4.

## Validation criteria

- Every language in `languages` produced a `localization_<language>.json`
  with a non-empty `title`.
- Every slide has non-empty `narration` and `caption`.
- Every node ID present in `slides/manifest.json` for a slide has a
  corresponding entry in that slide's `slide_translations` — no node
  silently left untranslated.
- Every `terminology`-tagged term for a slide literally appears in that
  slide's narration and caption text.
- No forbidden term (from `config/terminology.yaml` or a project
  manifest's overrides) appears in narration, captions, slide
  translations, or the title.
- (Warnings, not hard failures) caption length within
  `captions.max_chars_soft_limit`, and caption not identical to
  narration — see "Caption vs narration".

## Error handling & retry behavior

- Missing/malformed source deck (no `slide_NNN.html` files found, or one
  fails to parse): fail immediately, do not extract further slides.
- A language missing from `config/languages.yaml`: fail with a clear
  message naming the language and pointing at the config file — do not
  guess a voice/font.
- Terminology violations found by `msv slides validate`: this is a
  content bug, not a transient failure — fix the offending slide's text
  and re-validate; do not retry blindly.
- Because `slide_analysis.json` is language-independent and cached under
  `state/<run_id>/analysis/`, re-running localization for one added or
  corrected language does not require re-analyzing the deck — only
  `localization_<language>.json` for that language needs to be
  (re)written.

## Handoff contract

Per-language status envelope to Agent 4:

```json
{
  "agent": "slide_analysis_agent",
  "run_id": "run-20260818-001",
  "language": "zh-TW",
  "status": "completed",
  "outputs": {
    "slide_analysis": "state/<run_id>/analysis/slide_analysis.json",
    "localization": "state/<run_id>/analysis/localization_zh-TW.json"
  },
  "warnings": [],
  "errors": []
}
```

Agent 4 records this under `languages.<language>.stages.analysis` and, once
every requested language is `completed`, creates the per-language jobs for
Agent 2.
