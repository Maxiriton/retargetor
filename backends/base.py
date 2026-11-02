"""What a backend declares to the add-on. No bpy at load time.

A backend is a Backend subclass, listed in registry.py. Its worker (a script in its folder) does the actual
work in its own process; the add-on only knows what is declared here.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class Capabilities:
    """What the UI and the add-on can ask of a backend.

    prompt: takes a text prompt. seed: takes a seed (results are repeatable).
    max_duration: longest motion in seconds (None: no limit). native_fps: the model's own frame rate
    (None: works at any rate; the backend's adapter resamples to the request's fps either way).
    streaming: sends the motion in several chunks while generating.
    min_key_poses: fewest key poses in a request (0: the prompt alone is enough).
    """
    prompt: bool = False
    min_key_poses: int = 2
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

    def worker_command(self, settings):
        """(argv, extra environment variables) starting the worker.
        Raises ValueError with an explicit message if the settings don't allow it (missing path...)."""
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

    def check_request(self, request):
        """Raises ValueError if the backend can't generate this request."""
        problem = self.range_problem(request.start_frame, request.end_frame, request.fps, len(request.key_poses))
        if problem:
            raise ValueError(problem)


def worker_script(package_file, name="worker.py"):
    """Path of a worker script next to a backend module."""
    return os.path.join(os.path.dirname(os.path.abspath(package_file)), name)


def blender_python():
    """Blender's own Python executable (it has numpy), for workers that need nothing else."""
    return sys.executable
