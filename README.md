# Multilingual Slide Video Production System

Five-agent pipeline that turns one clean English HTML slide deck into
fully localized, narrated, captioned, publication-ready slideshow videos
and (optionally) publishes them to YouTube — a Python CLI (`msv`) plus
agent skills in `.agents/skills/` built on top of it, following the same overall
shape as its sibling
[`multilingual_demo_video_production_system`](../multilingual_demo_video_production_system),
but with an HTML/CSS deck instead of a screen recording as the input, and
browser-rendered slide screenshots instead of composited video frames as
the visual track.

```
English HTML Slide Deck → Agent 1 (analyze + translate slide text + localize narration/captions)
                         → Agent 2 (TTS + render the default language's slideshow) → human approval
                         → Language Rollout Agent (fan out Agent 2 to every other language)
                         → Agent 3 (YouTube metadata + publish) → Agent 4 (orchestrates all of it)
```

| Role | Procedure skill | Orchestrator skill | Answers |
|---|---|---|---|
| Slide analysis & localization | `slide_deck_localization` | `.agents/skills/slide_analysis/SKILL.md` | What does each slide say, and what should its on-screen text, narration, captions, and the deck's marketing title say in each language? |
| Voice & slideshow production | `slideshow_video_production` | `.agents/skills/slideshow_production/SKILL.md` | Given the translated slides and script, produce the actual narrated, captioned MP4 for one language. |
| Multilingual rollout | `multilingual_rollout` | `.agents/skills/language_rollout/SKILL.md` | Once the default language is approved, fan Agent 2 out to every other language in one dispatch. |
| YouTube publishing | `youtube_video_publishing` | `.agents/skills/youtube_publishing/SKILL.md` | Draft metadata and publish a finished video. |
| **Orchestration** | `slide_video_orchestration` | `.agents/skills/pipeline_orchestrator/SKILL.md` | Run the whole thing end-to-end, resume after failure, report status. |

Each role has two skills. The **orchestrator skill** (formerly a Claude
Code subagent in `.claude/agents/`) is the entry point: it holds the role,
its guardrails and which other skill to dispatch next. The **procedure
skill** holds the detailed steps it follows. Dispatching a skill means
running it in a subagent when the host supports subagents, otherwise
inline.

`pipeline-orchestrator` (Agent 4) is the entry point for a full
run — invoke it for "produce localized slideshow videos
from this deck" requests rather than driving the other roles by hand.
`slideshow-production` and `language-rollout` still work
standalone for a targeted rerun (e.g. "just re-render the zh-TW
slideshow") or a manual re-fan-out, the same as in the video-source
sibling project.

## Why a separate project instead of extending the existing one

The video-source pipeline's core rendering logic (composite narration
onto existing footage, anchor segments against pre-existing scene
timestamps, pad or trim to match a fixed source video length) doesn't
transfer cleanly to slides — there is no pre-existing footage or timeline
to composite onto or anchor against; a slide's on-screen duration is
*derived entirely* from how long its own narration takes to speak. Rather
than threading a `source_type` branch through the existing project's
state machine, renderer, and schemas, this is an independent project that
**replicates the useful patterns** (CLI shape, pipeline state machine,
two-gate approval workflow, skill/agent structure) without importing code
from or depending on the original at runtime. The two pipelines evolve
independently.

## Why HTML instead of PPTX/PDF as the source format

This was a deliberate change from an earlier draft of this design (which
targeted `.pptx`). Reasoning:

- **Translation is DOM text-node replacement**, not shape/paragraph/run
  traversal — simpler and more robust than `python-pptx`'s object model,
  and directly built on standard, well-tested HTML libraries
  (`BeautifulSoup`/`lxml`) — see `src/multilingual_slide_video_agent/slides/`.
- **Rendering fidelity is higher and more consistent.** Slides are
  rasterized with a real browser engine (headless Chromium via
  Playwright) instead of LibreOffice's `--headless --convert-to`
  pipeline, which has known quirks (e.g. its PNG export filter often only
  emits the first slide for a multi-slide file, forcing a PDF
  intermediate step). Chromium renders CSS, web fonts, SVGs, and
  gradients the same way on every OS.
- **Text reflow is a solved problem in CSS.** A `.pptx` text box has a
  fixed size and only reflows if the deck author remembered to turn on
  "shrink text on overflow." HTML/CSS layouts (flexbox, `clamp()` for
  responsive font sizing, `overflow-wrap`) can be authored to gracefully
  absorb a translation that's meaningfully longer (German) or denser
  (CJK) than the English source — this is a structural improvement, not
  just a lateral format swap.
- **Setup is one pip package, not a separate system binary.** Playwright
  installs via pip and downloads its own browser binary
  (`playwright install chromium`) — no equivalent of hunting down a
  LibreOffice install and pointing `SOFFICE_PATH` at `soffice.exe`.

The real tradeoff, and the reason this wasn't the first choice: **the
source deck must be authored directly as HTML/CSS**, not converted from
an existing PowerPoint file. If the actual starting point is a deck a
colleague already built in PowerPoint, this design doesn't remove that
conversion problem — it just moves it upstream, out of scope, to a
one-time PPTX/PDF → HTML export (manual, or via a separate tool) done
before this pipeline ever runs.

## Install

```bash
python -m venv .venv && source .venv/bin/activate   # or .venv\Scripts\activate on Windows
pip install -e ".[dev]"
cp .env.example .env   # fill in OPENAI_API_KEY, YOUTUBE_* credentials
playwright install chromium   # one-time browser download for slide rendering
```

Requires `ffmpeg`/`ffprobe` on `PATH` and, for CJK captions, a font such
as Noto Sans CJK installed system-wide.

New compared to the video-source sibling project:

- **`playwright`** (pip) — drives headless Chromium to screenshot each
  HTML slide at a fixed viewport size, for both the original English deck
  (so Agent 1 can visually read it) and every translated deck (the actual
  video frames Agent 2 renders from). Replaces LibreOffice entirely — no
  external system binary to install or locate on `PATH`.
- **`beautifulsoup4` / `lxml`** (pip) — parses each slide's HTML to walk
  and translate text nodes in place (`src/multilingual_slide_video_agent/slides/extract_text.py`,
  `apply_translations.py`), and to inject stable node IDs during analysis
  so translations map back to the exact right element.
- If slides reference web fonts (Google Fonts, custom `@font-face`),
  either keep them locally bundled under the deck's `assets/` folder for
  reproducible rendering, or ensure the render environment has network
  access — same consideration the video-source project already has for
  CJK caption fonts.

## YouTube API setup

Only needed once, before the first publish — `msv slides`/`msv production`
work fine without any of this. Three pieces: a Google Cloud OAuth client, a
one-time consent flow to mint a refresh token, and a few `.env` values.

### 1. Create a Google Cloud project and enable the API

1. Go to the [Google Cloud Console](https://console.cloud.google.com/) and
   create a project (or pick an existing one).
2. **APIs & Services → Library** → search for **YouTube Data API v3** →
   **Enable**.

### 2. Configure the OAuth consent screen

1. **APIs & Services → OAuth consent screen**.
2. User type: **External** (unless you have a Google Workspace org and want
   Internal). Fill in the required app name/support email fields.
3. Scopes: you don't need to add anything here manually — the app requests
   `youtube.upload`/`youtube` at consent time.
4. **Leave Publishing status as "Testing."** This app requests YouTube
   upload/manage scopes, which Google treats as sensitive — publishing the
   app for real would trigger a formal verification review, which is a lot
   of overhead for something used by you/your team. Testing mode works
   fine indefinitely (no expiring 7-day tokens the way it used to), with
   one catch: only *test users you explicitly add* can complete the
   consent flow — add yours now, before step 4 ("Mint a refresh token")
   below, or you'll hit `Error 403: access_denied` / "has not completed
   the Google verification process."

#### Adding a test user

1. Open the [Google Cloud Console](https://console.cloud.google.com/) and
   select your project from the project selector dropdown at the top of
   the page.
2. In the left-hand navigation menu, go to **APIs & Services → OAuth
   consent screen** (some console versions instead show this as
   **Google Auth platform → Audience**).
3. If Publishing status is **Testing** and User type is **External**,
   you'll see a **Test users** section. Click **+ ADD USERS**.
4. Enter the Google account email address(es) you want to authorize
   (`user@gmail.com`, or a Workspace email) — use whichever account
   manages the destination YouTube channel, since that's the account
   you'll sign in with in step 4 below.
5. Click **Save**.

### 3. Create an OAuth client and download the credentials

1. **APIs & Services → Credentials → + Create Credentials → OAuth client
   ID**.
2. Application type: **Desktop app**. Give it any name.
3. **Download JSON** on the resulting client — this is your client secrets
   file (holds `client_id`/`client_secret`; never commit it — see
   Security below).
4. Save it somewhere on disk (outside the repo, or under `config/` — either
   is fine, `config/youtube_client_secret*.json` is already `.gitignore`d)
   and point `.env` at it:
   ```
   YOUTUBE_CLIENT_SECRETS_FILE=/path/to/client_secret_....json
   ```

### 4. Mint a refresh token (one-time, interactive)

This step has to run in *your* terminal, not through an agent — it opens a
browser for you to sign in and grant consent. It only needs to be done
once per YouTube channel/account (the token doesn't expire from use).

1. In a terminal, from the project root, with the venv active:
   ```bash
   cd C:\Users\bibo7\gitrepo\multilingual_slide_video_production_system
   .venv\Scripts\activate
   msv publishing get-refresh-token
   ```
   This automatically picks up `YOUTUBE_CLIENT_SECRETS_FILE` from `.env`;
   pass `--client-secrets-file /path/to/client_secret.json` instead if you
   want to use a different one for this run.
2. A browser window opens to a Google sign-in screen. Sign in with the
   **same account you added as a test user** above — this determines
   which channel receives the uploads.
3. Review the requested permissions (YouTube upload/manage) and click
   **Allow**.
4. The browser shows a plain success page — you can close it. Back in
   your terminal, the command prints:
   ```
   Add this to .env:
   YOUTUBE_REFRESH_TOKEN=1//...
   ```
5. Copy the value after `YOUTUBE_REFRESH_TOKEN=` (the whole `1//...`
   string).
6. Open `.env` and replace the placeholder line:
   ```
   YOUTUBE_REFRESH_TOKEN=<refresh-token>
   ```
   with the real value:
   ```
   YOUTUBE_REFRESH_TOKEN=1//06k_...           # your actual token
   ```
7. Save `.env`. Publishing is now ready to use — no further setup needed
   for this channel.

**If you hit `Error 403: access_denied`** — "has not completed the Google
verification process" — the signed-in account isn't on the test-user list
yet. Go back to "Adding a test user" above, add it, then re-run
`msv publishing get-refresh-token`.

### 5. Set the remaining publishing options in `.env`

```
YOUTUBE_PRIVACY_STATUS=unlisted   # or public / private
YOUTUBE_CATEGORY_ID=28            # YouTube category id, 28 = Science & Technology
# YOUTUBE_PLAYLIST_ID=            # optional - leave unset/commented if you don't have one yet
```

Leave `YOUTUBE_PLAYLIST_ID` unset rather than a placeholder — the CLI
treats a literal `<playlist-id>` as "not configured" and skips
playlist-add cleanly, but don't rely on that if you're editing this by
hand; just comment the line out or leave it blank.

### Sanity-check before publishing anything

```bash
python -c "
from multilingual_slide_video_agent.publishing.youtube import build_youtube_client
yt = build_youtube_client()
print(yt.channels().list(part='snippet', mine=True).execute()['items'][0]['snippet']['title'])
"
```

Prints the authenticated channel's name if credentials are wired up
correctly — cheaper than finding out via a failed upload.

## The `msv` CLI

Five command groups (`slides`, `production`, `motion`, `publishing`, `pipeline`) —
every command prints one JSON object and exits 0/1 for success/failure.
`language-rollout` has no command group of its own: it's pure
orchestration built entirely on `msv pipeline status`/`next-actions` plus
dispatching `slideshow-production`, the same as Agent 4 does.

```bash
msv slides extract-text --deck-dir <path> --out state/<run_id>/analysis/slides/manifest.json
msv slides render-images --deck-dir <path> --out <dir> [--viewport 1920x1080]
msv slides apply-translations --deck-dir <original_deck_dir> --localization <localization_<lang>.json> --out <translated_<lang>_dir>
msv slides validate --slide-analysis ... --localization ... --language ... [--manifest ...] [--project ...]
msv slides generate-animation --deck-dir <original_deck_dir> --out state/<run_id>/analysis/slides/animation [--slide-analysis ...] [--spec ...]
msv slides inspect-layout --deck-dir <deck_dir> --out layout_map.json [--annotate-dir ...]   # targets for motion design
msv slides validate-motion --design motion_design.json --deck-dir <deck_dir> [--layout-map ...] [--production ...]

# stage tts: narration + narration-driven timing + captions -> production.json (no video)
msv production narrate --run-id ... --project-id ... --language ... \
    --source-deck <original_deck_dir> \
    --localization state/<run_id>/analysis/localization_<language>.json \
    --output-dir output/<run_id>/<language> [--audio-dir ...]
# stage rendering: the animated video in one pass (engine/style from config/motion.yaml)
msv production render-motion --production output/<run_id>/<language>/production.json \
    --translated-deck-dir state/<run_id>/analysis/slides/translated_<language> \
    --animation-dir state/<run_id>/analysis/slides/animation \
    --localization state/<run_id>/analysis/localization_<language>.json \
    [--engine remotion|hyperframes] [--motion-design motion_design.json] [--output-name video.mp4]
msv production validate --production output/<run_id>/<language>/production.json [--localization ...] [--run-id ...]
# static fallback (explicit request, or motion engine unavailable)
msv production render-slideshow --run-id ... --project-id ... --language ... \
    --source-deck <original_deck_dir> --slides-dir state/<run_id>/analysis/slides/rendered_<language> \
    --localization ... --output-dir output/<run_id>/<language> [--audio-dir ...] [--no-burn-in]

msv motion install          # npm ci in motion/ (pinned HyperFrames + Remotion), then Remotion's browser
msv motion doctor           # Node, ffmpeg, Chromium, per-engine availability, Remotion license reminder

msv publishing validate --metadata ... --language ... [--video ...]
msv publishing upload --run-id ... --project-id ... --language ... --video ... --metadata ... --output-dir ... [--existing-video-id ...]
msv publishing get-refresh-token [--client-secrets-file ...]

msv pipeline init --project-id ... --source-deck deck/ [--languages en-US,zh-TW,ja-JP]
msv pipeline next-actions / status / set-stage / rerun-language / rerun-stage /
    approve-production / approve-publish / validate / report
```

`msv slides` has no "run it end-to-end" command by design — reading the
deck and writing slide descriptions/narration/translations is Claude's
job (see `.agents/skills/slide_deck_localization/SKILL.md`), not a
deterministic script; the CLI only provides the extraction/rendering/
validation tooling around that step.

**Production is animation-first.** Each language's video is rendered in
one pass: `narrate` (TTS and the narration-driven timing), then
`render-motion`, which renders the translated deck as an animated video
with Remotion (frame-exact) in the **playful** motion style - springy
pop-ins, word-by-word headlines, count-ups, cards popping in across the
narration, a slow camera push-in, and a quick fade before each cut. The
review gates are unchanged: the default language is reviewed before the
other languages render, and nothing is published without approval.

Each slide gets one of eight shot templates (`title_reveal`,
`feature_callout`, `stat_highlight`, `diagram_build`, `closing`,
`quote_testimonial`, `comparison_versus`, `timeline_roadmap`), picked by
`msv slides generate-animation` from an optional `visual_role` Agent 1
assigns per slide in `slide_analysis.json`, otherwise a deterministic
position + keyword heuristic. The templates are declarative data, one file
per motion style (`config/animation_templates.yaml` = calm,
`config/animation_templates_playful.yaml` = playful), played by a small
generic engine in `slides/assets/animation_runtime.js` built on GSAP.
Adding or tuning a template is a YAML edit. See
`docs/motion-engines-and-hardening-plan.md` (Part D) for the design, and
`.agents/skills/slideshow_video_production/SKILL.md` for the full command
sequence.

**Two engines, one animation.** `--engine remotion` (the default) and
`--engine hyperframes` both render the translated deck itself and seek the same
per-slide GSAP timelines frame by frame, so they cut, animate and
transition every slide on the same frames. They differ in fonts:
HyperFrames swaps system fonts (Georgia, Arial, generic `sans-serif`) for
its own bundled ones and looks up other font names on Google Fonts while
rendering; Remotion renders the deck's fonts as the browser does. Remotion
is free for individuals and companies of up to 3 people; larger companies
need a Remotion company license (`msv motion doctor` prints a reminder).

**Per-deck motion designs.** Instead of one template per slide, a deck can
have a `motion_design.json` (schema `motion-design/v1`): which elements
move, in what order and at which point in the narration, with effects such
as word-by-word or line-by-line text, SVG line drawing, highlights,
arrows between boxes, camera moves, and crossfade/push/wipe transitions
between slides. The eight templates are its presets. Pass it with
`render-motion --motion-design`. `msv slides inspect-layout` maps what
can be targeted on each slide, with numbered screenshots, and
`msv slides validate-motion` checks a design against the deck and against
comfort rules (no more than 3 flashes per second, at most 6 elements moving
at once, time left to read). At render time a slide whose design fails in
one language plays its preset there, with a warning naming it.
`docs/examples/motion_design.food-manufacturing.json` is a worked example.
Claude writing these designs itself, with an approval gate, is the plan's
Phase 6.

## Architecture

```
                    USER / API
                        │
                        ▼
              ┌──────────────────┐
              │     AGENT 4      │  slide_video_orchestration
              │   ORCHESTRATOR   │  state/<run_id>.json, resume/retry
              └────────┬─────────┘
                       │
                       ▼
              ┌──────────────────┐
              │     AGENT 1      │  slide_deck_localization
              │ SLIDE ANALYSIS + │  slide_analysis.json +
              │  LOCALIZATION    │  localization_<language>.json
              │                  │  (marketing title + per-slide
              │                  │   narration + short highlight caption +
              │                  │   node-ID-keyed slide_translations,
              │                  │   for every configured language)
              └────────┬─────────┘
                       ▼
              ┌──────────────────┐
              │     AGENT 2      │  slideshow_video_production
              │ HTML TRANSLATE + │  default_language ONLY, first —
              │  OPENAI TTS +    │  narrate (tts), then one-pass animated
              │ HYPERFRAMES      │  render (rendering): video.mp4/narration.mp3/
              │ ANIMATED RENDER  │  captions.srt/production.json. Each slide's
              │                  │  on-screen duration is its own narration
              │                  │  length plus a short pause; playful motion
              │                  │  plays against it; captions auto-wrap; an
              │                  │  animated title card leads the video.
              └────────┬─────────┘
                       ▼
                 HUMAN REVIEW
              (msv pipeline approve-production,
               or PIPELINE_AUTO_APPROVE_PRODUCTION=true)
                       ▼
              ┌──────────────────┐
              │ LANGUAGE ROLLOUT │  multilingual_rollout
              │      AGENT       │  fans out AGENT 2 to every other
              │                  │  language in parallel, once
              └────────┬─────────┘
                       ▼
              ┌──────────────────┐
              │     AGENT 3      │  youtube_video_publishing
              │ YOUTUBE METADATA │  metadata_<language>.json →
              │  + PUBLISHING    │  publication_<language>.json
              └────────┬─────────┘
                       ▼
                YouTube Videos
```

The default-language-first gate exists because a bug visible in one
language's render (bad pacing, a caption-formatting issue, translated
text overflowing a slide's layout) is almost always present in every
language's render — catching it after producing one video instead of N
avoids repeating (and re-billing) the mistake N times. See
`slide_video_orchestration/SKILL.md`'s "Default-language-first production
gate" for the full mechanics.

Full detail — validation criteria, error handling, retry behavior,
handoff contracts — lives in each skill's `SKILL.md`; this file covers
project-wide setup and configuration.

## Workflow

1. **Analyze the English deck.** Agent 1 reads each slide's HTML/CSS
   source (text content, structure) and a rendered screenshot of it (see
   below — Claude can't visually interpret raw HTML/CSS any more than it
   can play video or render a `.pptx`), and writes a language-independent
   `slide_analysis.json` describing what each slide shows.
2. **Translate every configured language, in one pass.** For each
   language in `SUPPORTED_LANGUAGES`, Agent 1 writes a
   `localization_<language>.json` containing: a marketing title for the
   deck, and per slide — translated on-screen text (mapped back onto the
   slide's HTML by stable node ID, preserving the original CSS/layout/
   design), a narration script, and a short highlight caption.
3. **Produce the default language's complete slideshow first.** Agent 2
   applies that language's translations to the original deck, renders the
   translated deck to PNG screenshots via headless Chromium, generates
   narration audio, and assembles the full slideshow video — captions,
   title card, per-slide timing driven by each slide's actual narration
   length.
4. **Human approval gate #1.** The default language's slideshow is
   reviewed before any other language's rendering work begins — this
   catches pacing/caption/narration problems once instead of once per
   language.
5. **Roll out to the remaining languages.** Once approved, the Language
   Rollout Agent fans Agent 2 out to every other language in parallel,
   reusing the slide translations already produced in step 2 — no
   re-translation needed.
6. **Human approval gate #2.** Each finished language is held for review
   before publishing.
7. **Publish to YouTube.** Agent 3 drafts localized metadata (title,
   description, tags) and uploads each approved language's video.

## Directory layout

```
.agents/
  skills/          # 12 SKILL.md files: 5 orchestrator skills (pipeline_orchestrator,
                    # language_rollout, slide_analysis, slideshow_production,
                    # youtube_publishing), the 5 procedure skills they follow, plus
                    # gsap_animation_authoring and motion_design_principles
src/multilingual_slide_video_agent/
  config.py        # .env + config/*.yaml + cwd-relative dir resolution
  state.py          # PipelineState — resume/retry backbone
  schemas.py         # agent-to-agent contract validation
  terminology.py      # preserve/forbidden-term checks
  logging_utils.py     # secret-redacting structured logging
  media.py            # ffprobe helper
  slides/            # text extraction, node-ID translation application, Chromium rendering,
                      # + generate_animation.py/animation_templates.py/design_system.py
                      # (GSAP animation bundle generation — see docs/marketing-animation-pipeline-plan.md)
    assets/            # animation_runtime.js (the actual GSAP timelines)
    vendor/            # vendored gsap.min.js (see its GSAP_LICENSE.txt)
  production/         # render_slideshow.py: narration (narrate_language) + static fallback
                      # motion/: animated rendering - HyperFrames engine, exact-frame assembly,
                      # shared caption+narration post-pass, validation
  publishing/         # YouTube upload (same shape as the video-source project)
  cli.py            # the `msv` command groups
config/            # languages.yaml, terminology.yaml, video.yaml, design_system.yaml,
                   # animation_templates.yaml (the 5 GSAP shot templates, as data)
docs/              # marketing-animation-pipeline-plan.md
output/ state/ logs/   # runtime data (git-ignored except .gitkeep)
tests/             # pytest unit tests
```

**Source deck shape**: a directory of standalone, self-contained slide
files — `deck/slide_001.html`, `deck/slide_002.html`, ... — each a
complete HTML page sized to a fixed canvas (e.g. 1920×1080), optionally
sharing `deck/assets/` (images, fonts) and a common `deck/styles.css`.
One file per slide (rather than a single multi-section file, as
frameworks like reveal.js use) keeps both translation and rendering
trivial: each file is one independent DOM to parse/translate, and one
independent page for Chromium to screenshot — no slide-navigation or
section-isolation logic needed.

Per-run artifacts unique to this pipeline (vs. the video-source project's
`scene_analysis.json` + video-timestamp-based segments):

```
state/<run_id>/analysis/
├── slides/manifest.json                  # per-slide DOM node IDs + original text
├── slides/source_images/slide_001.png    # rendered ORIGINAL English deck (via Chromium)
├── slide_analysis.json                   # language-independent per-slide description
├── localization_<language>.json          # title + segments[] with slide_index +
│                                          # slide_translations[] keyed by node id, instead
│                                          # of start_time/end_time
├── slides/translated_<language>/         # per-language translated HTML deck
│   ├── slide_001.html
│   └── ...
└── slides/rendered_<language>/           # rendered translated deck — what gets composited
    ├── slide_001.png
    └── ...
```

`config/`, `output/`, `state/`, `logs/`, and `.env` itself resolve under
`MSV_ROOT_DIR` (a real environment variable; defaults to the current
working directory if unset), with a per-directory `MSV_CONFIG_DIR` etc.
override for the rare case one needs to live elsewhere (see
`.env.example`) — the same convention as the video-source sibling
project's `MDV_*` directory variables. Source decks have no dedicated
directory — pass whatever path the deck actually lives at to
`--source-deck`/`--deck-dir`.

## Adding a language

Add an entry to `config/languages.yaml` (voice, caption font, TTS tone
instructions) and include its code in `SUPPORTED_LANGUAGES` in `.env`. No
code changes required — Agent 1 will localize into it and Agent 4 will
create a job for it on the next `msv pipeline init`.

## Default-language-first production gate

Only `DEFAULT_LANGUAGE` (or `--default-language` at `msv pipeline init`)
gets rendered first. Every other language's `translation` stage is held
until that render is reviewed and `msv pipeline approve-production --run-id ...`
is called (or `PIPELINE_AUTO_APPROVE_PRODUCTION=true` is set) — at which
point `language-rollout` fans out to everyone else in one dispatch.
Rerunning the default language (`rerun_language --language <default>`)
re-locks the gate automatically, since whatever was approved no longer
exists. See `slide_video_orchestration/SKILL.md` for the full mechanics.

## Human review before publishing

`PIPELINE_AUTO_PUBLISH=false` (the default) holds every language at
`ready_for_review` once validation passes — narration, captions, and
(once drafted) title/description can be reviewed before anything goes
live. Release specific languages with
`msv pipeline approve-publish --run-id ... --languages en-US,zh-TW`.
Requires YouTube credentials to actually be configured first — see
"YouTube API setup" above.

## Example prompts

This project is meant to be operated by talking to a coding agent, not by
typing raw `msv` commands yourself: the orchestrator skills run the CLI for
you and report back. Naming the skill explicitly (as in every example
below) is the reliable way to get the right one. Each also has a
`description` in its `.agents/skills/<name>/SKILL.md` frontmatter tuned for
an agent to pick up on intent alone, but an explicit name removes any
ambiguity, especially once several runs exist at once.

**Start a full run on a new deck:**
> "Use the pipeline-orchestrator skill for the deck C:\path\to\your-deck\."

> "Produce localized slideshow videos from C:\Users\you\Documents\product-launch-deck\."

This takes it as far as the default-language-first gate and then stops on
its own — see above.

**Check on a run in progress:**
> "Is it done yet?"

> "What's the pipeline status for run-20260818-001?"

**Approve the default-language render, releasing every other language:**
> "Approved. Please move on to the next step."

> "Please dispatch pipeline-orchestrator to roll out the other languages for run-20260818-001."

This is a real conversational gate (see "Default-language-first production
gate" above) — the orchestrator will not proceed to the other languages
just because a status check shows the default language is ready; it
waits for a reply like this one.

**Approve publishing once everything's rendered:**
> "Approved — go ahead and publish all languages for run-20260818-001."

> "Publish just the en-US and zh-TW videos for run-20260818-001."

Same pattern as production approval: `ready_for_review` is informational,
not permission — nothing gets uploaded until you say so explicitly.

**Rerun one language or one stage after a fix:**
> "Rerun the zh-TW language for run-20260818-001 from analysis onward — the narration was too verbose."

> "Re-render just the fr-FR video for run-20260818-001 with slideshow-production; the rest can stay as they are."

**Run a single role directly, outside the full pipeline:**
> "Use the slide-analysis skill for the deck at C:\path\to\deck\."

> "Dispatch slideshow-production to re-render the ja-JP video for run-20260818-001."

**Add a language to every future run:**
> "Add ko-KR to config/languages.yaml with a natural TTS voice profile, then include it in SUPPORTED_LANGUAGES."

No code changes needed after that — the next `msv pipeline init` picks it
up automatically (see "Adding a language" above).

## Key design decisions

**HTML only, authored directly as the source** (not converted from an
existing PowerPoint/PDF deck). See "Why HTML instead of PPTX/PDF" above
for the full reasoning and the upstream-conversion tradeoff this implies.

**Node-ID-based translation mapping.** During analysis, each slide's HTML
is parsed once and every translatable text node gets a stable ID recorded
in `manifest.json` (slide index + a CSS-selector-like path + original
text). `localization_<language>.json`'s `slide_translations[]` entries
reference those IDs, so applying a translation is a direct node lookup —
no re-parsing ambiguity, and it fails loudly (not silently) if the deck's
structure changed between analysis and translation application.

**Slide duration is narration-driven, not fixed.** A slide's on-screen
duration is its narration's actual length plus a short pause, with no
pre-existing timeline to overrun or pad against — unlike the video-source
project's renderer, which has to reconcile narration against a
pre-existing scene window. See `production/render_slideshow.py`'s
`compute_slide_timeline`.

**CSS absorbs translated-text-length variance better than fixed shapes,
but isn't magic.** Flexbox/`clamp()`-based layouts handle most
translation length differences gracefully. A lightweight validation
warning (comparing caption length against `captions.max_chars_soft_limit`)
is still in place for extreme outliers, the same defensive spirit as the
video-source project's caption-length warnings.

**Captions, title card, and both approval gates are reused conceptually.**
The video-source project's caption-wrapping (`WrapStyle`), distinct
title-card styling (top-aligned, so it reads as visually distinct from a
regular slide caption), and its default-language-first + publishing
approval gates are already-validated designs replicated as-is here, not
redesigned from scratch.

## Security

Same posture as the video-source project: real credentials only in
`.env` (git-ignored), `.env.example` ships placeholders only, structured
logs redact secret-shaped fields, and pipeline state never stores
credentials — only file paths and stage status.

## Tests

```bash
pytest
```

Covers schema validation, terminology enforcement, pipeline state
transitions (stage ordering, per-language failure isolation, the
human-review gate, `rerun_language`/`rerun_stage` invalidation), the
narration-driven slide timeline (`compute_slide_timeline`), and the
node-ID extraction/translation round trip. Does not call OpenAI/YouTube/
Chromium/ffmpeg — those paths are exercised manually (see "Install" and
"YouTube API setup" above).
