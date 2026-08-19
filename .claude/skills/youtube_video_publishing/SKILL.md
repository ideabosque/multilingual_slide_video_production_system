---
name: youtube-video-publishing
description: YouTube publishing skill for Agent 3. Drafts a localized title/description/tags for a finished slideshow video and uploads it via the YouTube Data API v3 using stored OAuth credentials. Use when a validated localized video is ready to publish or when re-publishing after fixing metadata without re-rendering the video.
---

# YouTube Video Publishing Skill

Reference implementation: reused as-is (conceptually) from the
`youtube_video_publishing` skill in the sibling
`multilingual_demo_video_production_system` project — nothing about
YouTube publishing changes for a slide-sourced video versus a
screen-recording-sourced one.

## Purpose

Turn a finished, validated localized slideshow video plus its narration/
slide context into YouTube metadata and a published (or unlisted, per
config) video.

## Responsibilities

- Receive the final localized video from Agent 2 and the narration script
  / slide descriptions from Agent 1.
- Draft a natural, localized title, description, tags, and (where
  appropriate) hashtags for the video's target language — not a literal
  translation of an English draft.
  `localization_<language>.json.title` (Agent 1's marketing title card
  text, also in `production.json.title`) is a good starting point for the
  YouTube title — reuse or lightly extend it rather than drafting an
  unrelated one from scratch, so the on-video title card and the YouTube
  listing agree.
- Preserve terminology and branding (`config/terminology.yaml`).
- Validate the metadata before spending an upload quota call.
- Upload via the YouTube Data API v3 using the configured OAuth refresh
  token; add to the configured playlist if any.
- Return the publication result to Agent 4.

## Required inputs

| Input | Description |
|---|---|
| `run_id`, `project_id`, `language` | From Agent 4 |
| `video` | Path to Agent 2's `slideshow.mp4` for this language |
| `localization` | Agent 1's `localization_<language>.json` (narration/slide context to draft metadata from) |
| `production` | Agent 2's `production.json` (duration, etc.) |

## Generated outputs

```
state/<run_id>/publishing/
├── metadata_<language>.json     # authored by Claude, validated before upload
└── publication_<language>.json  # msv publishing upload's result
```

`metadata_<language>.json`:
```json
{
  "language": "en-US",
  "title": "IdeaBosque AI Agent — Product Launch Deck",
  "description": "...",
  "tags": ["AI Agent", "Product Launch", "IdeaBosque"],
  "category_id": 28,
  "privacy_status": "unlisted"
}
```

`publication_<language>.json` (also the handoff contract to Agent 4):
```json
{
  "language": "zh-TW",
  "status": "published",
  "youtube_video_id": "abc123",
  "youtube_url": "https://www.youtube.com/watch?v=abc123",
  "published_at": "2026-08-18T10:00:00Z"
}
```

## Available tools

The `msv` CLI, group `msv publishing` — unchanged in shape from the
video-source project:

- `msv publishing validate --metadata ... --language ... [--video ...]` —
  pre-upload validation.
- `msv publishing upload --run-id ... --project-id ... --language ... --video ... --metadata ... --output-dir ... [--existing-video-id ...]`
  — the actual resumable upload + optional playlist add (or, with
  `--existing-video-id`, a metadata-only update).
- `msv publishing get-refresh-token [--client-secrets-file ...]` —
  one-time, human-run helper to mint an OAuth refresh token from the
  downloaded Google client secrets JSON; never invoked by the pipeline
  itself.
- Claude's own reasoning to draft the localized title/description/tags
  from the narration script and slide descriptions.

## Configuration

`.env`: `YOUTUBE_CLIENT_SECRETS_FILE` (path to the OAuth client JSON
downloaded from Google Cloud Console — holds client_id/client_secret so
neither is ever typed into `.env`), `YOUTUBE_REFRESH_TOKEN`,
`YOUTUBE_PRIVACY_STATUS`, `YOUTUBE_CATEGORY_ID`, `YOUTUBE_PLAYLIST_ID`,
`ENABLE_YOUTUBE_PUBLISHING`, `PIPELINE_AUTO_PUBLISH`,
`PIPELINE_MAX_RETRIES`. None of these — nor the client secrets file's
contents — are ever read into a prompt, a skill file, or a log line —
`multilingual_slide_video_agent/logging_utils.py` redacts any field whose
key looks like a secret and known token/key string shapes as a backstop,
and the client secrets file itself is git-ignored.

## Execution procedure

1. Confirm `ENABLE_YOUTUBE_PUBLISHING` is true and the video/production
   files exist; if `PIPELINE_AUTO_PUBLISH` is false, this stage only runs
   once a human has explicitly approved the run — check state's
   `languages.<language>.stages.publishing` was moved out of the
   auto-held `pending` state by an explicit `publish_pending` command,
   not automatically after validation.
2. Draft `metadata_<language>.json` from the narration script and slide
   descriptions — natural phrasing for the target language, terminology
   preserved, description covering what the deck presents.
3. `msv publishing validate`; fix and re-validate on failure.
4. `msv publishing upload` to perform the upload (and playlist add).
5. Report the resulting status envelope to Agent 4.

## Validation criteria

- `title` and `description` are non-empty and within YouTube's length
  limits (100 / 5000 characters).
- `language` in the metadata matches the language being published.
- Combined tag length is within YouTube's 500-character limit.
- No forbidden terminology in title/description.
- The video file exists on disk.
- After upload: response contains a `youtube_video_id`.

## Error handling & retry behavior

- Missing credentials: fail immediately with a clear error naming the
  missing env var; never fall back to a hardcoded value.
- Transient upload errors (HTTP 500/502/503/504): retried with
  exponential backoff up to `PIPELINE_MAX_RETRIES`, inside
  `msv publishing upload`'s resumable-upload loop.
- Non-transient failures (auth error, quota exceeded, invalid metadata):
  fail the `publishing` stage in pipeline state; Agent 1 and Agent 2 do
  **not** re-run — the existing video and narration are still valid, only
  the publishing stage is retried, optionally after correcting
  `metadata_<language>.json`.
- A rerun should reuse the already-uploaded video if
  `publication_<language>.json` shows `status: "published"` with a
  `youtube_video_id` already — Agent 4 should treat re-publishing as a
  metadata-only update rather than uploading a duplicate video. Pass
  `--existing-video-id <id>` to `msv publishing upload` in that case; it
  calls `videos().update` instead of `videos().insert()` and skips the
  media upload entirely.

## Handoff contract

```json
{
  "agent": "youtube_publishing_agent",
  "run_id": "run-20260818-001",
  "language": "zh-TW",
  "status": "completed",
  "outputs": { "...publication_<language>.json fields..." },
  "warnings": [],
  "errors": []
}
```

Agent 4 records this under `languages.<language>.stages.publishing` and
stores `youtube_video_id` / `youtube_url` on the language entry.
