"""Shared contracts for the motion engines (motion-engines-and-hardening-plan
B2). Three engines (playwright today; hyperframes and remotion in Phases 2b/3)
implement one `MotionEngine` protocol and share the same post-pass - narration
bytes and caption timing stay identical across engines and with `slideshow.mp4`,
so only the visual track differs and cross-engine parity checks (B6 item 5)
stay honest."""
from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from multilingual_slide_video_agent.production.motion.context import MotionRenderContext
from multilingual_slide_video_agent.production.motion.errors import MotionError


@runtime_checkable
class MotionEngine(Protocol):
    """One animated-visual-track renderer.

    The contract keeps each engine's job small (B2): produce a **silent**
    video whose duration equals `ctx.total_duration` within one frame -
    narration and captions are added by the shared post-pass (post.py), not
    inside the engine, so audio/caption bytes stay identical across engines
    and `motion engine` parity checks are honest.
    """

    name: str

    def check_available(self) -> list[str]:
        """Missing prerequisites for this engine; an empty list means ready.
        Never raises - `msv motion doctor` prints the list, and
        `render_motion` fails a render loudly on a non-empty one."""
        ...

    def render(self, ctx: MotionRenderContext, work_dir: Path) -> Path:
        """Render the silent video into `work_dir` and return its path.

        `work_dir` is engine-private scratch (created by the caller); the
        engine may leave intermediate files there - `render_motion` deletes
        it after a successful run (same cleanup contract as the previous
        monolithic renderer). A browser/console error during render raises
        `MotionError` naming the slide where possible."""
        ...