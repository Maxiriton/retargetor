"""The interpolation backend's skeleton: one joint per humanoid role, named after the role, in a T-pose.
Blender conventions: Z-up, meters, the character faces -Y, its left side is +X. No bpy."""
from core.skeleton import Joint, Skeleton

# name, parent, head, tail (left side and spine; the right side mirrors the left on X)
_JOINTS = [
    ("hips", None, (0.0, 0.0, 1.0), (0.0, 0.0, 1.1)),
    ("spine", "hips", (0.0, 0.0, 1.1), (0.0, 0.0, 1.25)),
    ("chest", "spine", (0.0, 0.0, 1.25), (0.0, 0.0, 1.38)),
    ("upper_chest", "chest", (0.0, 0.0, 1.38), (0.0, 0.0, 1.48)),
    ("neck", "upper_chest", (0.0, 0.0, 1.48), (0.0, 0.0, 1.55)),
    ("upper_neck", "neck", (0.0, 0.0, 1.55), (0.0, 0.0, 1.6)),
    ("head", "upper_neck", (0.0, 0.0, 1.6), (0.0, 0.0, 1.8)),
    ("shoulder.L", "upper_chest", (0.02, 0.0, 1.45), (0.17, 0.0, 1.45)),
    ("upper_arm.L", "shoulder.L", (0.17, 0.0, 1.45), (0.45, 0.0, 1.45)),
    ("forearm.L", "upper_arm.L", (0.45, 0.0, 1.45), (0.72, 0.0, 1.45)),
    ("hand.L", "forearm.L", (0.72, 0.0, 1.45), (0.9, 0.0, 1.45)),
    ("thigh.L", "hips", (0.1, 0.0, 1.0), (0.1, 0.0, 0.55)),
    ("shin.L", "thigh.L", (0.1, 0.0, 0.55), (0.1, 0.0, 0.1)),
    ("foot.L", "shin.L", (0.1, 0.0, 0.1), (0.1, -0.15, 0.02)),
    ("toes.L", "foot.L", (0.1, -0.15, 0.02), (0.1, -0.22, 0.02)),
]


def _mirror(name):
    return name[:-2] + ".R" if name and name.endswith(".L") else name


def skeleton():
    joints = []
    for name, parent, head, tail in _JOINTS:
        joints.append(Joint(name, parent, head, tail))
    for name, parent, head, tail in _JOINTS:
        if name.endswith(".L"):
            joints.append(Joint(_mirror(name), _mirror(parent), (-head[0], head[1], head[2]),
                                (-tail[0], tail[1], tail[2])))
    return Skeleton(joints, root="hips")
