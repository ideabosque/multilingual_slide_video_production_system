"""Motion-rendering exception types - in their own module (not base.py) so
context.py and base.py can both import them without a cycle."""
from __future__ import annotations


class MotionError(Exception):
    """A failed motion render. Raised loudly with the slide named wherever
    it can be named - the pipeline's "fail loudly, not silently" standard
    (a silently-broken animation is worse than a render error, since
    nothing about the output MP4 would look obviously wrong without
    frame-by-frame review)."""


class MotionContextError(MotionError):
    """Bad or missing motion-render inputs (production.json, animation
    bundle, design system). Fail before any ffmpeg/Playwright work starts."""