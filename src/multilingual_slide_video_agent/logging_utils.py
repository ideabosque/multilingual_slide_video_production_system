"""Centralized, secret-safe logging for all agents.

Every log line is a JSON object appended to logs/<run_id>.jsonl so Agent 4
can assemble a full-execution log across agents/skills/languages/stages
(see the slide_video_orchestration skill's "Logging and observability").
Values are scrubbed for known secret patterns before they are ever
formatted, so a caller accidentally logging an API key or OAuth token
cannot leak it.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any

from multilingual_slide_video_agent.config import logs_dir

_SECRET_ENV_NAMES = {
    "OPENAI_API_KEY",
    "YOUTUBE_REFRESH_TOKEN",
}
_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"ya29\.[A-Za-z0-9_-]{20,}"),
    re.compile(r"1//[A-Za-z0-9_-]{20,}"),
]


def _redact(value: Any) -> Any:
    if isinstance(value, str):
        redacted = value
        for pattern in _SECRET_PATTERNS:
            redacted = pattern.sub("[REDACTED]", redacted)
        return redacted
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k.upper() in _SECRET_ENV_NAMES or "secret" in k.lower() or "token" in k.lower() or "api_key" in k.lower():
                out[k] = "[REDACTED]"
            else:
                out[k] = _redact(v)
        return out
    if isinstance(value, list):
        return [_redact(v) for v in value]
    return value


class RunLogger:
    """Structured logger scoped to one pipeline run_id."""

    def __init__(self, run_id: str, project_id: str | None = None):
        self.run_id = run_id
        self.project_id = project_id
        logs_dir().mkdir(parents=True, exist_ok=True)
        self.path = logs_dir() / f"{run_id}.jsonl"

    def log(
        self,
        *,
        agent: str,
        skill: str,
        stage: str | None = None,
        language: str | None = None,
        event: str,
        status: str = "info",
        duration_seconds: float | None = None,
        retry_count: int = 0,
        artifacts: list[str] | None = None,
        warnings: list[str] | None = None,
        errors: list[str] | None = None,
        **extra: Any,
    ) -> None:
        record = _redact(
            {
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "run_id": self.run_id,
                "project_id": self.project_id,
                "agent": agent,
                "skill": skill,
                "stage": stage,
                "language": language,
                "event": event,
                "status": status,
                "duration_seconds": duration_seconds,
                "retry_count": retry_count,
                "artifacts": artifacts or [],
                "warnings": warnings or [],
                "errors": errors or [],
                **extra,
            }
        )
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def status_envelope(
        self,
        *,
        agent: str,
        language: str | None,
        status: str,
        outputs: dict[str, Any] | None = None,
        warnings: list[str] | None = None,
        errors: list[str] | None = None,
    ) -> dict[str, Any]:
        """Build the standard agent-to-agent status envelope."""
        return _redact(
            {
                "agent": agent,
                "run_id": self.run_id,
                "language": language,
                "status": status,
                "outputs": outputs or {},
                "warnings": warnings or [],
                "errors": errors or [],
            }
        )
