"""What the add-on knows about the Kimodo backend, and its preferences."""
import os

from bpy.props import EnumProperty
from bpy.types import PropertyGroup

from ..base import Backend, Capabilities, worker_script
from . import install, joints

_MODEL_ITEMS = [(name, label, f"nvidia/{name}: SOMA skeleton, {joints.MODEL_FPS:g} fps")
                for name, label in joints.MODEL_LABELS.items()]


class RTGTR_KimodoSettings(PropertyGroup):
    model: EnumProperty(name="Model", items=_MODEL_ITEMS, default=joints.DEFAULT_MODEL,
                        description="Kimodo model to load (its weights are downloaded by the install)")


class KimodoBackend(Backend):
    id = "kimodo"
    label = "Kimodo"
    description = (f"NVIDIA Kimodo: text prompt and key poses, up to {joints.MAX_DURATION:g} s at a time "
                   "(needs a CUDA GPU with 8 GB)")
    capabilities = Capabilities(prompt=True, seed=True, max_duration=joints.MAX_DURATION,
                                native_fps=joints.MODEL_FPS, min_key_poses=0, partial_poses=True,
                                prompt_segments=True,
                                transition_duration=joints.TRANSITION_FRAMES / joints.MODEL_FPS,
                                # The motion around a regenerated segment: as many model frames as a transition
                                motion_context=True,
                                context_duration=(joints.TRANSITION_FRAMES - 1) / joints.MODEL_FPS)
    joint_map = dict(joints.JOINT_MAP)

    def settings_class(self):
        return RTGTR_KimodoSettings

    def draw_settings(self, layout, settings):
        layout.prop(settings, "model")

    def requirements(self, machine, settings):
        return install.requirements(machine, settings.model if settings is not None else None)

    def worker_command(self, python, settings, layout):
        if not python or not os.path.isfile(python):
            raise ValueError(f"The Kimodo Python executable doesn't exist: {python}")
        model = (settings.model if settings is not None else "") or joints.DEFAULT_MODEL
        env = {
            # Never download anything: the install downloaded the weights
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            # Use the local text encoder directly, without trying a text encoder server first
            "TEXT_ENCODER_MODE": "local",
        }
        if layout is not None:
            env["KIMODO_TEXT_ENCODER_DIR"] = layout.weights_dir(install.TEXT_ENCODER)
        return [python, "-I", "-u", worker_script(__file__), "--model", model], env
