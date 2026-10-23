"""What every engine renders, clip by clip: the title card and each slide,
on whole-frame boundaries (`segment_frame_counts`), with the steps a motion
design gives the slide and the transitions that overlap it with its
neighbours (plan C3). Both engines build from this one plan, so they cut,
choreograph and transition every slide identically.

Without a motion design, `steps` is None and the slide plays its template
by name, exactly as before designs existed; there are no transitions.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from multilingual_slide_video_agent.production.motion.assembly import segment_frame_counts
from multilingual_slide_video_agent.production.motion.context import MotionRenderContext
from multilingual_slide_video_agent.slides import motion_design as md
from multilingual_slide_video_agent.slides.animation_templates import load_template_config

TITLE_CLIP_ID = "title"


@dataclass
class ClipPlan:
    id: str
    kind: str                       # "title" or "slide"
    template: str
    start: int                      # the clip's own first frame (its narration start)
    frames: int                     # its own length, boundary to boundary
    lead: int = 0                   # frames shown before `start`, for an incoming transition
    tail: int = 0                   # frames shown after its end, for an outgoing transition
    steps: list[dict[str, Any]] | None = None
    transition_in: dict[str, Any] | None = None    # {type, direction, frames}
    transition_out: dict[str, Any] | None = None   # {type, direction, frames, start}: start is clip-local

    @property
    def host_start(self) -> int:
        return self.start - self.lead

    @property
    def host_frames(self) -> int:
        return self.lead + self.frames + self.tail

    def runtime_options(self, fps: int) -> dict[str, Any]:
        """The runtime's __motionRunSlide options for this clip's motion
        (seconds): its steps, its lead, and the transitions an engine that
        composites slides in one page plays on the slide's root."""
        opts: dict[str, Any] = {}
        if self.steps is not None:
            opts["steps"] = self.steps
        if self.lead:
            opts["lead"] = self.lead / fps
        if self.transition_in:
            opts["transitionIn"] = {"type": self.transition_in["type"],
                                    "direction": self.transition_in["direction"],
                                    "duration": self.transition_in["frames"] / fps}
        if self.transition_out:
            opts["transitionOut"] = {"type": self.transition_out["type"],
                                     "direction": self.transition_out["direction"],
                                     "duration": self.transition_out["frames"] / fps,
                                     "at": self.transition_out["start"] / fps}
        return opts


def duration_tokens(design_tokens: dict[str, Any]) -> dict[str, float]:
    """The design system's motion tokens in seconds, by design token name."""
    motion = design_tokens.get("motion", {})
    return {
        "fast": motion.get("duration_fast_ms", 120) / 1000,
        "base": motion.get("duration_base_ms", 160) / 1000,
        "slow": motion.get("duration_slow_ms", 200) / 1000,
        "slide_enter": motion.get("slide_enter_ms", 480) / 1000,
        "slide_exit": motion.get("slide_exit_ms", 320) / 1000,
    }


def plan_clips(ctx: MotionRenderContext) -> list[ClipPlan]:
    frame_counts = segment_frame_counts([t["end_time"] - t["start_time"] for t in ctx.timing], ctx.fps)
    template_by_slide = {s.slide_id: s.template for s in ctx.slides}
    clips: list[ClipPlan] = []
    start = 0
    for item, frames in zip(ctx.timing, frame_counts):
        if item.get("kind") == "title":
            clips.append(ClipPlan(TITLE_CLIP_ID, "title", "title_backdrop", start, frames))
        else:
            sid = item["slide_id"]
            clips.append(ClipPlan(sid, "slide", template_by_slide[sid], start, frames))
        start += frames

    design = ctx.motion_design
    if not design:
        return clips

    plans = md.plan_transitions([c.id for c in clips], frame_counts, design, ctx.fps,
                                duration_tokens(ctx.design_tokens))
    presets = load_template_config(str(ctx.motion_config.get("animation_style", "calm")))
    entries = md.entries_by_slide(design)
    for clip, plan in zip(clips, plans):
        clip.lead, clip.tail = plan["lead"], plan["tail"]
        clip.transition_in = plan["in"]
        if plan["out"]:
            # The outgoing half starts where the incoming clip does: d // 2
            # frames before the boundary.
            before = plan["out"]["frames"] // 2
            clip.transition_out = {**plan["out"], "start": clip.lead + clip.frames - before}
        if clip.kind == "slide":
            entry = entries.get(clip.id)
            preset = (entry or {}).get("preset") or clip.template
            clip.template = preset
            clip.steps = md.slide_steps(entry, presets[preset]["steps"], drop_exit=bool(plan["out"]))
    return clips
