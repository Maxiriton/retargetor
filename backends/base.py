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
    """
    prompt: bool = False
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

    def check_request(self, request):
        """Raises ValueError if the backend can't generate this request."""
        caps = self.capabilities
        if caps.max_duration is not None and request.duration > caps.max_duration + 1e-6:
            raise ValueError(f"{self.label} generates at most {caps.max_duration:g} s; the key poses span "
                             f"{request.duration:.2f} s (frames {request.start_frame}-{request.end_frame}).")
        if len(request.key_poses) < 2:
            raise ValueError("At least two key poses are needed.")


def worker_script(package_file, name="worker.py"):
    """Path of a worker script next to a backend module."""
    return os.path.join(os.path.dirname(os.path.abspath(package_file)), name)


def blender_python():
    """Blender's own Python executable (it has numpy), for workers that need nothing else."""
    return sys.executable
