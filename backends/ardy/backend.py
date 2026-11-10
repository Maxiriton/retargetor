"""What the add-on knows about the ARDY backend, and its preferences. Its capabilities, joint map and skeleton
depend on the checkpoint chosen (ArdyBackend.configured)."""
import os

from bpy.props import EnumProperty
from bpy.types import PropertyGroup

from ..base import Backend, Capabilities, worker_script
from . import install, models

_MODEL_ITEMS = [(name, checkpoint.label, f"nvidia/{name}: {checkpoint.skeleton.upper()} skeleton, "
                 f"{checkpoint.fps:g} fps") for name, checkpoint in models.CHECKPOINTS.items()]


class RTGTR_ArdySettings(PropertyGroup):
    model: EnumProperty(name="Model", items=_MODEL_ITEMS, default=models.DEFAULT_MODEL,
                        description="ARDY model to load (its weights are downloaded by the install): the SOMA "
                                    "skeleton at 30 fps, or ARDY's own Core skeleton at 20 fps")


def checkpoint_capabilities(checkpoint):
    return Capabilities(prompt=True, seed=True, min_key_poses=0, partial_poses=True,
                        # Autoregressive: any length, a prompt per window
                        max_duration=None, native_fps=checkpoint.fps, prompt_segments=True,
                        # The next segment's prompt starts at the boundary: the model makes the transition after it
                        transition_duration=0.0,
                        # The motion around a regenerated segment: two tokens of model frames, constrained
                        motion_context=True,
                        context_duration=(2 * models.TOKEN_FRAMES - 1) / checkpoint.fps,
                        streaming=True)


class ArdyBackend(Backend):
    id = "ardy"
    label = "ARDY"
    description = ("NVIDIA ARDY: text prompt and key poses, any length, streamed window by window "
                   "(needs a CUDA GPU with 17 GB)")
    checkpoint_name = models.DEFAULT_MODEL
    capabilities = checkpoint_capabilities(models.checkpoint(models.DEFAULT_MODEL))
    joint_map = models.checkpoint(models.DEFAULT_MODEL).joint_map
    # Llama 3 8B in bfloat16 takes about a minute to load
    load_timeout = 900.0

    _configured = {}

    def settings_class(self):
        return RTGTR_ArdySettings

    def draw_settings(self, layout, settings):
        layout.prop(settings, "model")

    def configured(self, settings):
        name = (settings.model if settings is not None else "") or models.DEFAULT_MODEL
        if name == self.checkpoint_name:
            return self
        backend = ArdyBackend._configured.get(name)
        if backend is None:
            checkpoint = models.checkpoint(name)
            backend = ArdyBackend()
            backend.checkpoint_name = name
            backend.capabilities = checkpoint_capabilities(checkpoint)
            backend.joint_map = checkpoint.joint_map
            ArdyBackend._configured[name] = backend
        return backend

    @property
    def skeleton_id(self):
        return f"{self.id}-{models.checkpoint(self.checkpoint_name).skeleton}"

    def requirements(self, machine, settings):
        return install.requirements(machine, settings.model if settings is not None else models.DEFAULT_MODEL)

    def worker_command(self, python, settings, layout):
        if not python or not os.path.isfile(python):
            raise ValueError(f"The ARDY Python executable doesn't exist: {python}")
        model = (settings.model if settings is not None else "") or models.DEFAULT_MODEL
        env = {
            # Never download anything: the install downloaded the weights
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            # The local text encoder, without trying ARDY's text encoder service first; the checkpoints from the
            # Hugging Face cache
            "TEXT_ENCODER_MODE": "local",
            "LOCAL_CACHE": "true",
        }
        return [python, "-I", "-u", worker_script(__file__), "--model", model], env
