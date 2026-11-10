"""Kimodo's constants; its skeleton is SOMA (backends/shared/soma.py). No bpy."""
from ..shared.soma import END_EFFECTORS, JOINT_MAP, ROOT_JOINT  # noqa: F401

MODEL_FPS = 30.0
# Longest motion Kimodo's own demo generates, in seconds
MAX_DURATION = 10.0
# Frames at the start of each prompt segment constrained by the end of the previous one (Kimodo's multi-prompt
# default, num_transition_frames)
TRANSITION_FRAMES = 5
DEFAULT_MODEL = "Kimodo-SOMA-RP-v1.1"
