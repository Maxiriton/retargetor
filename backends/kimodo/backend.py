"""What the add-on knows about the Kimodo backend, and its preferences."""
import os

import bpy
from bpy.props import StringProperty
from bpy.types import PropertyGroup

from ..base import Backend, Capabilities, worker_script
from . import joints


class RTGTR_KimodoSettings(PropertyGroup):
    python: StringProperty(
        name="Kimodo Python", subtype='FILE_PATH',
        description="Python executable of the virtual environment where Kimodo is installed "
                    "(for example kimodo-venv/Scripts/python.exe)")
    model: StringProperty(name="Model", default=joints.DEFAULT_MODEL,
                          description="Kimodo model to load (its weights must be downloaded already)")


class KimodoBackend(Backend):
    id = "kimodo"
    label = "Kimodo"
    description = "NVIDIA Kimodo, SOMA skeleton: text prompt and full-body key poses (needs a CUDA GPU)"
    capabilities = Capabilities(prompt=True, seed=True, max_duration=joints.MAX_DURATION,
                                native_fps=joints.MODEL_FPS)
    joint_map = dict(joints.JOINT_MAP)

    def settings_class(self):
        return RTGTR_KimodoSettings

    def draw_settings(self, layout, settings):
        layout.prop(settings, "python")
        layout.prop(settings, "model")

    def worker_command(self, settings):
        python = bpy.path.abspath(settings.python) if settings is not None else ""
        if not python:
            raise ValueError("Set the Python executable of the Kimodo environment in the add-on preferences.")
        if not os.path.isfile(python):
            raise ValueError(f"The Kimodo Python executable doesn't exist: {python}")
        model = settings.model or joints.DEFAULT_MODEL
        env = {
            # Never download anything: the weights must already be there
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            # Use the local text encoder directly, without trying a text encoder server first
            "TEXT_ENCODER_MODE": "local",
        }
        return [python, "-I", "-u", worker_script(__file__), "--model", model], env
