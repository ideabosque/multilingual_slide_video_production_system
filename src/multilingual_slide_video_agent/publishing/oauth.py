"""One-time interactive helper to mint a YouTube OAuth refresh token.

Not part of the automated pipeline — run `msv publishing get-refresh-token`
once locally, by hand, to populate YOUTUBE_REFRESH_TOKEN in .env. Never
invoked by any agent/skill. Uses the same client secrets JSON file
`multilingual_slide_video_agent.publishing.youtube.build_youtube_client`
reads at upload time (`YOUTUBE_CLIENT_SECRETS_FILE`), so client_id/secret
only ever live in that one downloaded file, never copied into .env.
"""
from __future__ import annotations


def get_refresh_token(client_secrets_file: str) -> str:
    from google_auth_oauthlib.flow import InstalledAppFlow

    from multilingual_slide_video_agent.publishing.youtube import SCOPES

    flow = InstalledAppFlow.from_client_secrets_file(client_secrets_file, scopes=SCOPES)
    creds = flow.run_local_server(port=0)
    return creds.refresh_token
