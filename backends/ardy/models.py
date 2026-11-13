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

# ARDY's text encoder: LLM2Vec on Llama 3 8B Instruct, as ARDY loads it (in bfloat16, the McGill adapters merged
# when it loads: 15 GB of video memory, about a minute), or a build with the adapters merged in and the weights
# quantized (community builds for ARDY, voxta on Hugging Face, not gated). Measured against the full one on 11 motion
# prompts (2026-11-13, RTX 3090): the text features 0.997 (8-bit) and 0.985 (4-bit) alike on average; the same seed
# gives the same motion within 1.5 to 3.4 cm with the 8-bit, 5 to 11.5 cm with the 4-bit (another seed: 31 to 36 cm).


@dataclass(frozen=True)
class TextEncoder:
    label: str
    description: str
    repo_id: str = ""        # a merged build ("" for the full one, from its three repositories)
    revision: str = ""
    size_gb: float = 0.0
    vram_gb: float = 15.0    # the encoder alone

    @property
    def quantized(self):
        return bool(self.repo_id)


TEXT_ENCODERS = {
    "INT8": TextEncoder("8-bit", "Quantized to 8 bits: 8 GB of video memory, loads in a few seconds, the motion "
                                 "nearly the full one's", "voxta/Llama-3-8B-LLM2Vec-ARDY-INT8",
                        "96c7eb1cc9100cd3925662d1093926c00b64a698", 8.1, 8.0),
    "NF4": TextEncoder("4-bit", "Quantized to 4 bits: 4.7 GB of video memory, loads in a few seconds, the motion "
                                "a little further from the full one's", "voxta/Llama-3-8B-LLM2Vec-ARDY-NF4",
                       "f746923e9e7edb3b6fc54aae7dfd8cecb0f52a8f", 4.7, 4.7),
    "FULL": TextEncoder("Full", "As ARDY loads it (bfloat16): 15 GB of video memory, about a minute to load, "
                                "Hugging Face access to Meta's Llama 3"),
}
DEFAULT_TEXT_ENCODER = "INT8"


def text_encoder(name):
    return TEXT_ENCODERS.get(name) or TEXT_ENCODERS[DEFAULT_TEXT_ENCODER]


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
