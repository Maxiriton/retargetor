"""What a backend declares to the add-on. No bpy at load time.

A backend is a Backend subclass, listed in registry.py. Its worker (a script in its folder) does the actual
work in its own process; the add-on only knows what is declared here.
"""
from __future__ import annotations

import math
import os
import sys
from dataclasses import dataclass

# Inside the add-on this module is <add-on>.backends.base; in the unit tests, backends.base
try:
    from ..core.segments import PromptSegment
except ImportError:
    from core.segments import PromptSegment


@dataclass(frozen=True)
class Capabilities:
    """What the UI and the add-on can ask of a backend.

    prompt: takes a text prompt. seed: takes a seed (results are repeatable).
    max_duration: longest motion in seconds (None: no limit). native_fps: the model's own frame rate
    (None: works at any rate; the backend's adapter resamples to the request's fps either way).
    streaming: sends the motion in several chunks while generating.
    min_key_poses: fewest key poses in a request (0: the prompt alone is enough).
    partial_poses: honours core.motion.Pose.constrained_joints (constrains only what the animator keyed);
    otherwise every key pose is sent whole.
    prompt_segments: generates a track of prompt segments (GenerationRequest.segments) in one pass, with its own
    transitions between them; max_duration then applies to each segment. Otherwise the add-on generates the
    segments one after the other, each one a request of its own, without transition.
    transition_duration: with prompt_segments, seconds before each boundary where the backend blends the previous
    segment into the next one (shown in the timeline).
    motion_context: continues the motion around the range (GenerationRequest.context_before / context_after), so a
    single prompt segment can be regenerated without a jump where it meets its neighbours. context_duration: seconds
    of that motion it needs on each side (the add-on sends at least one frame more).
    """
    prompt: bool = False
    min_key_poses: int = 2
    partial_poses: bool = False
    prompt_segments: bool = False
    transition_duration: float = 0.0
    motion_context: bool = False
    context_duration: float = 0.0
    seed: bool = False
    max_duration: float | None = None
    native_fps: float | None = None
    streaming: bool = False


class Backend:
    id = ""
    label = ""
    description = ""
    # Only listed when the "Developer" option of the preferences is on
    developer_only = False
    capabilities = Capabilities()
    # {humanoid role id: joint name}, composed with the rig profile (core.profile.compose)
    joint_map: dict[str, str] = {}
    # Seconds to wait for the model to load ("load" request), and for a generation
    load_timeout = 600.0
    generate_timeout = 600.0

    def settings_class(self):
        """The bpy PropertyGroup holding this backend's preferences, or None. Called at registration."""
        return None

    def draw_settings(self, layout, settings):
        """Draw the backend's preferences (settings is an instance of settings_class())."""

    @property
    def installable(self):
        """The backend has a model to install (it overrides requirements())"""
        return type(self).requirements is not Backend.requirements

    def requirements(self, machine, settings):
        """What the model needs installed on this machine (backends.setup.spec.Requirements: Python version,
        packages, weights...), or None when there is nothing to install (the worker runs with Blender's Python).
        settings: an instance of settings_class(), or None."""
        return None

    def worker_command(self, python, settings, layout):
        """(argv, extra environment variables) starting the worker.
        python: the Python of the model's environment (None for a backend without requirements). layout: its
        backends.setup.paths.Layout (where its weights are), or None.
        Raises ValueError with an explicit message if the settings don't allow it."""
        raise NotImplementedError

    def range_problem(self, start_frame, end_frame, fps, key_count):
        """Why the backend can't generate frames start_frame to end_frame (fps) with key_count key poses in them,
        or "" if it can. Also used by the panel, before generating."""
        caps = self.capabilities
        duration = (end_frame - start_frame + 1) / fps
        if caps.max_duration is not None and duration > caps.max_duration + 1e-6:
            return (f"{self.label} generates at most {caps.max_duration:g} s; frames {start_frame}-{end_frame} "
                    f"span {duration:.2f} s.")
        if key_count < caps.min_key_poses:
            return (f"{self.label} needs at least {caps.min_key_poses} key poses in the range "
                    f"({key_count} in frames {start_frame}-{end_frame}).")
        return ""

    def segments_problem(self, segments, fps, key_frames):
        """Why the backend can't generate this track of prompt segments (core.segments, contiguous) with key poses
        on key_frames, or "" if it can. With prompt_segments one request covers the track: the maximum duration
        applies to each segment, the fewest key poses to the whole track. Otherwise each segment is a request, from
        the previous segment's last frame."""
        caps = self.capabilities
        for i, segment in enumerate(segments):
            duration = segment.frame_count / fps
            if caps.max_duration is not None and duration > caps.max_duration + 1e-6:
                return (f"Segment {i + 1} (frames {segment.start_frame}-{segment.end_frame}) spans {duration:.2f} s: "
                        f"{self.label} generates at most {caps.max_duration:g} s per segment.")
        if caps.prompt_segments:
            start, end = segments[0].start_frame, segments[-1].end_frame
            count = sum(1 for frame in key_frames if start <= frame <= end)
            if count < caps.min_key_poses:
                return (f"{self.label} needs at least {caps.min_key_poses} key poses on the track "
                        f"({count} in frames {start}-{end}).")
            return ""
        for i, segment in enumerate(segments):
            # A segment after another one is generated from that one's last frame
            first = segment.start_frame - 1 if i > 0 else segment.start_frame
            count = sum(1 for frame in key_frames if first <= frame <= segment.end_frame)
            if count < caps.min_key_poses:
                return (f"{self.label} needs at least {caps.min_key_poses} key poses in each segment ({count} in "
                        f"segment {i + 1}, frames {segment.start_frame}-{segment.end_frame}).")
        return ""

    def context_frame_count(self, fps):
        """How many frames of the motion around a range to send on each side (0: the backend takes none)"""
        caps = self.capabilities
        if not caps.motion_context:
            return 0
        return math.ceil(caps.context_duration * fps - 1e-6) + 1

    def segment_problem(self, segment, fps, key_frames, before=False, after=False):
        """Why the backend can't regenerate one prompt segment (core.segments.PromptSegment) with key poses on
        key_frames, or "" if it can. before / after: whether the motion on that side is sent as context
        (motion_context); each side counts as a key pose for min_key_poses. Without motion_context, the segment is
        generated from the frame before it when `before` (as a segment of a track generated one by one)."""
        caps = self.capabilities
        duration = segment.frame_count / fps
        if caps.max_duration is not None and duration > caps.max_duration + 1e-6:
            return (f"Frames {segment.start_frame}-{segment.end_frame} span {duration:.2f} s: {self.label} "
                    f"generates at most {caps.max_duration:g} s per segment.")
        first = segment.start_frame - 1 if before and not caps.motion_context else segment.start_frame
        count = sum(1 for frame in key_frames if first <= frame <= segment.end_frame)
        if caps.motion_context:
            count += int(before) + int(after)
        if count < caps.min_key_poses:
            return (f"{self.label} needs at least {caps.min_key_poses} key poses to regenerate frames "
                    f"{segment.start_frame}-{segment.end_frame} ({count}, the motion around them included).")
        return ""

    def check_request(self, request):
        """Raises ValueError if the backend can't generate this request."""
        context = request.context_before is not None or request.context_after is not None
        if context and not self.capabilities.motion_context:
            raise ValueError(f"{self.label} doesn't continue the motion around a range.")
        if context:
            segment = PromptSegment(request.start_frame, request.end_frame)
            problem = self.segment_problem(segment, request.fps, list(request.key_poses),
                                           request.context_before is not None, request.context_after is not None)
        elif request.segments:
            if not self.capabilities.prompt_segments:
                raise ValueError(f"{self.label} doesn't generate prompt segments in one request.")
            problem = self.segments_problem(request.segments, request.fps, list(request.key_poses))
        else:
            problem = self.range_problem(request.start_frame, request.end_frame, request.fps,
                                         len(request.key_poses))
        if problem:
            raise ValueError(problem)


def worker_script(package_file, name="worker.py"):
    """Path of a worker script next to a backend module."""
    return os.path.join(os.path.dirname(os.path.abspath(package_file)), name)


def blender_python():
    """Blender's own Python executable (it has numpy), for workers that need nothing else."""
    return sys.executable
