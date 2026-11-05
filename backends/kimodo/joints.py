"""Kimodo's constants and the SOMA skeleton's humanoid role -> joint map. No bpy."""

MODEL_FPS = 30.0
# Longest motion Kimodo's own demo generates, in seconds
MAX_DURATION = 10.0
DEFAULT_MODEL = "Kimodo-SOMA-RP-v1.1"

ROOT_JOINT = "Hips"

# Kimodo's end-effector constraints (kimodo.constraints), by constraint type: the joints of a partial pose each
# one stands for. Hands and feet use their named types: Kimodo's post-processing only places those (a generic
# "end-effector" one is followed by the diffusion alone). "end-effector" pins the hips. Any other joint keyed
# (spine, neck, head) needs the whole body.
END_EFFECTORS = {
    "end-effector": {"Hips"},
    "left-hand": {"LeftShoulder", "LeftArm", "LeftForeArm", "LeftHand"},
    "right-hand": {"RightShoulder", "RightArm", "RightForeArm", "RightHand"},
    "left-foot": {"LeftLeg", "LeftShin", "LeftFoot", "LeftToeBase"},
    "right-foot": {"RightLeg", "RightShin", "RightFoot", "RightToeBase"},
}

# Humanoid role -> SOMA joint (the 77-joint skeleton used in Kimodo's outputs)
JOINT_MAP = {
    "hips": "Hips",
    "spine": "Spine1",
    "chest": "Spine2",
    "upper_chest": "Chest",
    "neck": "Neck1",
    "upper_neck": "Neck2",
    "head": "Head",
}
for _side, _soma in (("L", "Left"), ("R", "Right")):
    JOINT_MAP.update({
        f"shoulder.{_side}": f"{_soma}Shoulder",
        f"upper_arm.{_side}": f"{_soma}Arm",
        f"forearm.{_side}": f"{_soma}ForeArm",
        f"hand.{_side}": f"{_soma}Hand",
        f"thigh.{_side}": f"{_soma}Leg",
        f"shin.{_side}": f"{_soma}Shin",
        f"foot.{_side}": f"{_soma}Foot",
        f"toes.{_side}": f"{_soma}ToeBase",
    })
