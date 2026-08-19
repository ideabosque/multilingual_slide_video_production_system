"""Shared configuration: .env + config/*.yaml + working-directory layout.

Every directory `msv` reads/writes (`config/`, `output/`, `state/`,
`logs/`) plus `.env` itself resolves relative to `root_dir()` — MSV_ROOT_DIR
if set, else the current working directory. This is what makes `msv`
behave the same whether run from an installed package or a repo checkout,
and lets a single project's data live somewhere other than "wherever the
shell happens to be" without exporting four separate directory overrides.
Each directory still has its own MSV_*_DIR override for the rare case one
needs to live somewhere else (e.g. output/ on a bigger disk) while the
rest stay under the root. Source decks are referenced by whatever path
the caller passes to `--source-deck`/`--deck-dir` — there is no dedicated
input directory.

To also control *which* .env gets loaded, MSV_ROOT_DIR needs to be a real
process environment variable, not a line inside that same .env — .env's
own location is resolved before .env is read, so a value set only inside
it arrives too late to change that one decision (it still takes effect
for config/output/state/logs, resolved lazily afterward).
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


def root_dir() -> Path:
    return Path(os.environ.get("MSV_ROOT_DIR", ".")).expanduser().resolve()


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    env_path = root_dir() / ".env"
    if env_path.is_file():
        load_dotenv(env_path)


_load_env()


def config_dir() -> Path:
    return Path(os.environ.get("MSV_CONFIG_DIR") or (root_dir() / "config")).expanduser()


def output_dir() -> Path:
    return Path(os.environ.get("MSV_OUTPUT_DIR") or (root_dir() / "output")).expanduser()


def state_dir() -> Path:
    return Path(os.environ.get("MSV_STATE_DIR") or (root_dir() / "state")).expanduser()


def logs_dir() -> Path:
    return Path(os.environ.get("MSV_LOGS_DIR") or (root_dir() / "logs")).expanduser()


def youtube_client_secrets_file() -> Path:
    """Path to the OAuth 2.0 Client JSON downloaded from Google Cloud
    Console (APIs & Services > Credentials > OAuth client ID > Desktop app
    > Download JSON) — holds client_id/client_secret so they never need to
    be copied into .env by hand. See YOUTUBE_CLIENT_SECRETS_FILE in
    .env.example; the file itself must never be committed (see .gitignore)."""
    override = os.environ.get("YOUTUBE_CLIENT_SECRETS_FILE")
    return Path(override).expanduser() if override else config_dir() / "youtube_client_secret.json"


@lru_cache(maxsize=None)
def load_yaml(name: str) -> dict[str, Any]:
    """Load and cache a YAML file from config/ by filename (e.g. 'languages.yaml')."""
    path = config_dir() / name
    if not path.exists():
        raise FileNotFoundError(f"Missing config file: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def languages_config() -> dict[str, Any]:
    return load_yaml("languages.yaml")


def terminology_config() -> dict[str, Any]:
    return load_yaml("terminology.yaml")


def video_config() -> dict[str, Any]:
    return load_yaml("video.yaml")


def supported_languages() -> list[str]:
    env_value = os.getenv("SUPPORTED_LANGUAGES")
    if env_value:
        return [lang.strip() for lang in env_value.split(",") if lang.strip()]
    return list(languages_config().get("languages", {}).keys())


def default_language() -> str:
    return os.getenv("DEFAULT_LANGUAGE", languages_config().get("default_language", "en-US"))


def language_profile(language: str) -> dict[str, Any]:
    languages = languages_config().get("languages", {})
    if language not in languages:
        raise ValueError(f"Unsupported language: {language}. Configure it in config/languages.yaml.")
    return languages[language]


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return int(value)


def env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return float(value)


def _looks_like_placeholder(value: str) -> bool:
    """.env.example ships every secret/optional value as a literal
    <bracketed> placeholder (e.g. <api-key>, <playlist-id>). Treat an
    unedited copy of that placeholder as unset rather than as a real
    value - using one verbatim is a setup mistake, not a valid ID/secret,
    and should fail clearly here instead of being sent to an API that
    will reject it with a much more confusing error."""
    v = value.strip()
    return v.startswith("<") and v.endswith(">")


def env_or_none(name: str) -> str | None:
    """Like os.getenv(name), but treats an unedited <placeholder> value as
    unset - for optional settings (e.g. YOUTUBE_PLAYLIST_ID) where the
    caller's own `if value:` check would otherwise treat the placeholder
    text as a real, truthy value."""
    value = os.getenv(name)
    if not value or _looks_like_placeholder(value):
        return None
    return value


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value or _looks_like_placeholder(value):
        raise RuntimeError(
            f"Missing required environment variable: {name}. Set it in .env (see .env.example)."
        )
    return value
