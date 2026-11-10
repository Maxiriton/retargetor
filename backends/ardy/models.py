"""ARDY's checkpoints and what each one is: skeleton, frame rate, horizon, humanoid role -> joint map. No bpy.

Each checkpoint is trained on one skeleton, at one frame rate, generating a fixed number of frames per autoregressive
step (its horizon), in tokens of TOKEN_FRAMES frames. The SOMA one shares its skeleton with Kimodo
(backends/shared/soma.py); the Core one has ARDY's own 27-joint skeleton.
"""
from dataclasses import dataclass

from ..shared import soma

# Frames per token, for both checkpoints (Ardy.num_frames_per_token): history lengths are multiples of it
TOKEN_FRAMES = 4
# Longest window the model attends to (history, generated frames and the key poses ahead), as ARDY's demo and its
# command line: it is trained on windows of at most 10 s
WINDOW_SECONDS = 10.0
# History each window continues from: long enough to keep the motion's style, short enough to leave the window room
# for the key poses ahead
HISTORY_SECONDS = 2.0
# Diffusion steps per window (the checkpoints' schedule: num_base_steps)
DIFFUSION_STEPS = 10
# Classifier-free guidance (text, constraints): ARDY's defaults
CFG_WEIGHT = (2.0, 2.0)

# ARDY's Core skeleton: humanoid role -> joint. Core's "UpLeg" is the thigh and "Leg" the shin (SOMA's "Leg" is
# the thigh). Its spine has four joints: Spine1 follows Spine.
CORE_JOINT_MAP = {
    "hips": "Hips",
    "spine": "Spine",
    "chest": "Spine2",
    "upper_chest": "Spine3",
    "neck": "Neck",
    "head": "Head",
}
for _side, _core in (("L", "Left"), ("R", "Right")):
    CORE_JOINT_MAP.update({
        f"shoulder.{_side}": f"{_core}Shoulder",
        f"upper_arm.{_side}": f"{_core}Arm",
        f"forearm.{_side}": f"{_core}ForeArm",
        f"hand.{_side}": f"{_core}Hand",
        f"thigh.{_side}": f"{_core}UpLeg",
        f"shin.{_side}": f"{_core}Leg",
        f"foot.{_side}": f"{_core}Foot",
        f"toes.{_side}": f"{_core}ToeBase",
    })

# The end-effector constraints on the Core skeleton (ARDY's constraints.py; see shared/soma.py)
CORE_END_EFFECTORS = {
    "end-effector": {"Hips"},
    "left-hand": {"LeftShoulder", "LeftArm", "LeftForeArm", "LeftHand"},
    "right-hand": {"RightShoulder", "RightArm", "RightForeArm", "RightHand"},
    "left-foot": {"LeftUpLeg", "LeftLeg", "LeftFoot", "LeftToeBase"},
    "right-foot": {"RightUpLeg", "RightLeg", "RightFoot", "RightToeBase"},
}


@dataclass(frozen=True)
class Checkpoint:
    label: str
    skeleton: str      # "soma" or "core"
    fps: float
    horizon: int       # frames generated per autoregressive step
    size_gb: float

    @property
    def joint_map(self):
        return dict(soma.JOINT_MAP if self.skeleton == "soma" else CORE_JOINT_MAP)

    @property
    def end_effectors(self):
        return soma.END_EFFECTORS if self.skeleton == "soma" else CORE_END_EFFECTORS

    @property
    def history_frames(self):
        return max(TOKEN_FRAMES, int(round(HISTORY_SECONDS * self.fps)) // TOKEN_FRAMES * TOKEN_FRAMES)

    @property
    def window_frames(self):
        return int(WINDOW_SECONDS * self.fps) // TOKEN_FRAMES * TOKEN_FRAMES


CHECKPOINTS = {
    "ARDY-SOMA-RP-30FPS-Horizon60": Checkpoint("SOMA, 30 fps", "soma", 30.0, 60, 0.77),
    "ARDY-Core-RP-20FPS-Horizon40": Checkpoint("Core, 20 fps", "core", 20.0, 40, 0.77),
}
DEFAULT_MODEL = "ARDY-SOMA-RP-30FPS-Horizon60"
ROOT_JOINT = "Hips"


def checkpoint(name):
    return CHECKPOINTS.get(name) or CHECKPOINTS[DEFAULT_MODEL]
