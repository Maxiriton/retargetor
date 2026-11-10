"""ARDY's checkpoints and what each one is. No bpy.

Each checkpoint is trained on one skeleton, at one frame rate, generating a fixed number of frames per autoregressive
step (its horizon). The SOMA one shares its skeleton with Kimodo; the Core one has ARDY's own 27-joint skeleton.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Checkpoint:
    label: str
    skeleton: str      # "soma" or "core"
    fps: float
    horizon: int       # frames generated per autoregressive step
    size_gb: float


CHECKPOINTS = {
    "ARDY-SOMA-RP-30FPS-Horizon60": Checkpoint("SOMA, 30 fps", "soma", 30.0, 60, 0.77),
    "ARDY-Core-RP-20FPS-Horizon40": Checkpoint("Core, 20 fps", "core", 20.0, 40, 0.77),
}
DEFAULT_MODEL = "ARDY-SOMA-RP-30FPS-Horizon60"
