"""Agent 3 upload engine.

Uploads one localized slideshow video to YouTube via the Data API v3,
using a long-lived OAuth refresh token plus the OAuth client JSON
downloaded from Google Cloud Console (never an interactive login at
pipeline run time — credentials come only from .env /
YOUTUBE_CLIENT_SECRETS_FILE). Metadata (title/description/tags) is
authored beforehand by Claude and passed in as a dict/file — this module
only performs the mechanical upload/playlist-add/update and reports the
result.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from multilingual_slide_video_agent import config as cfg
from multilingual_slide_video_agent import schemas
from multilingual_slide_video_agent.logging_utils import RunLogger

RETRIABLE_STATUS_CODES = {500, 502, 503, 504}
SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube"]


class PublishError(Exception):
    pass


def load_client_secrets(path: Path) -> tuple[str, str]:
    """Read client_id/client_secret out of a Google OAuth client JSON file
    (the file you download from Cloud Console — 'installed' app type)."""
    if not path.exists():
        raise RuntimeError(
            f"YouTube client secrets file not found: {path}. Download it from Google Cloud "
            "Console (APIs & Services > Credentials > OAuth client ID > Desktop app > Download "
            "JSON), save it there, and set YOUTUBE_CLIENT_SECRETS_FILE in .env if using a "
            "different path."
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    section = data.get("installed") or data.get("web")
    if not section:
        raise RuntimeError(f"'{path}' doesn't look like a Google OAuth client secrets file (missing 'installed'/'web' key)")
    return section["client_id"], section["client_secret"]


def build_youtube_client():
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    client_id, client_secret = load_client_secrets(cfg.youtube_client_secrets_file())
    creds = Credentials(
        token=None,
        refresh_token=cfg.require_env("YOUTUBE_REFRESH_TOKEN"),
        client_id=client_id,
        client_secret=client_secret,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def _upload_video(youtube, video_path: Path, metadata: dict, max_retries: int) -> str:
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload

    body = {
        "snippet": {
            "title": metadata["title"],
            "description": metadata["description"],
            "tags": metadata.get("tags", []),
            "categoryId": str(metadata.get("category_id") or cfg.env_int("YOUTUBE_CATEGORY_ID", 28)),
            "defaultLanguage": metadata.get("language"),
            "defaultAudioLanguage": metadata.get("language"),
        },
        "status": {
            "privacyStatus": metadata.get("privacy_status") or os.getenv("YOUTUBE_PRIVACY_STATUS", "unlisted"),
        },
    }
    media = MediaFileUpload(str(video_path), chunksize=-1, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    attempt = 0
    while response is None:
        try:
            _status, response = request.next_chunk()
        except HttpError as e:
            if e.resp.status in RETRIABLE_STATUS_CODES and attempt < max_retries:
                attempt += 1
                time.sleep(min(2 ** attempt, 30))
                continue
            raise PublishError(f"YouTube upload failed (HTTP {e.resp.status}): {e}") from e
    if not response or "id" not in response:
        raise PublishError(f"YouTube upload returned no video id: {response}")
    return response["id"]


def _update_video_metadata(youtube, video_id: str, metadata: dict) -> None:
    """Metadata-only update (title/description/tags/privacy) for an
    already-published video, without re-uploading the file."""
    body = {
        "id": video_id,
        "snippet": {
            "title": metadata["title"],
            "description": metadata["description"],
            "tags": metadata.get("tags", []),
            "categoryId": str(metadata.get("category_id") or cfg.env_int("YOUTUBE_CATEGORY_ID", 28)),
            "defaultLanguage": metadata.get("language"),
        },
        "status": {
            "privacyStatus": metadata.get("privacy_status") or os.getenv("YOUTUBE_PRIVACY_STATUS", "unlisted"),
        },
    }
    youtube.videos().update(part="snippet,status", body=body).execute()


def _add_to_playlist(youtube, video_id: str, playlist_id: str) -> None:
    youtube.playlistItems().insert(
        part="snippet",
        body={"snippet": {"playlistId": playlist_id, "resourceId": {"kind": "youtube#video", "videoId": video_id}}},
    ).execute()


def publish_video(
    *,
    run_id: str,
    project_id: str,
    language: str,
    video_path: str | None,
    metadata_path: str,
    output_dir: str,
    existing_video_id: str | None = None,
) -> dict:
    """Upload (or, with `existing_video_id`, metadata-only update) one
    language's video. Returns the status envelope; also writes
    publication_<language>.json to output_dir."""
    logger = RunLogger(run_id, project_id)
    metadata_file = Path(metadata_path)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    errors: list[str] = []
    if not existing_video_id:
        if not video_path:
            errors.append("video_path is required unless existing_video_id is given")
        elif not Path(video_path).exists():
            errors.append(f"video file not found: {video_path}")
    if not metadata_file.exists():
        errors.append(f"metadata file not found: {metadata_file}")
    if errors:
        return _fail(logger, language, errors)

    metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
    validation = schemas.validate_publication_metadata(metadata)
    if not validation.ok:
        return _fail(logger, language, validation.errors)

    max_retries = cfg.env_int("PIPELINE_MAX_RETRIES", 3)
    t0 = time.time()
    try:
        youtube = build_youtube_client()
        if existing_video_id:
            _update_video_metadata(youtube, existing_video_id, metadata)
            video_id = existing_video_id
        else:
            video_id = _upload_video(youtube, Path(video_path), metadata, max_retries)
    except PublishError as e:
        return _fail(logger, language, [str(e)])
    except Exception as e:  # noqa: BLE001 - report unexpected API/auth errors, don't crash the pipeline
        return _fail(logger, language, [f"unexpected publishing error: {e}"])

    # The video is uploaded and live at this point - a playlist-add
    # problem (bad ID, permissions, deleted playlist) is a secondary,
    # non-fatal concern from here on and must never turn a successful
    # publish into a reported failure (which would otherwise risk a
    # retry re-uploading a duplicate video that already exists on the
    # channel).
    publish_warnings: list[str] = []
    if not existing_video_id:
        playlist_id = cfg.env_or_none("YOUTUBE_PLAYLIST_ID")
        if playlist_id:
            try:
                _add_to_playlist(youtube, video_id, playlist_id)
            except Exception as e:  # noqa: BLE001 - see comment above
                publish_warnings.append(
                    f"video uploaded successfully but could not be added to playlist '{playlist_id}': {e}"
                )

    published_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    result = {
        "run_id": run_id, "project_id": project_id, "language": language,
        "status": "published", "youtube_video_id": video_id,
        "youtube_url": f"https://www.youtube.com/watch?v={video_id}",
        "published_at": published_at, "title": metadata["title"],
        "metadata_only_update": bool(existing_video_id),
        "warnings": publish_warnings,
    }
    (out_dir / f"publication_{language}.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    envelope = logger.status_envelope(
        agent="youtube_publishing_agent", language=language, status="completed",
        outputs=result, warnings=publish_warnings,
    )
    logger.log(
        agent="youtube_publishing_agent", skill="youtube_video_publishing",
        stage="publishing", language=language, event="upload_completed", status="completed",
        duration_seconds=time.time() - t0, artifacts=[result["youtube_url"]],
        warnings=publish_warnings,
    )
    return envelope


def _fail(logger: RunLogger, language: str, errors: list[str]) -> dict:
    logger.log(
        agent="youtube_publishing_agent", skill="youtube_video_publishing",
        stage="publishing", language=language, event="upload_failed", status="failed", errors=errors,
    )
    return logger.status_envelope(agent="youtube_publishing_agent", language=language, status="failed", errors=errors)
