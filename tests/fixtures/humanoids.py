"""Synthetic humanoid skeletons named like common rigs, for the detection tests. No bpy, no asset: the bone names
and hierarchies follow each convention, the positions are the same simple T-pose (Z-up, meters, facing -Y, left
side +X).

    skeleton("mixamo", prefix="mixamorig1:") -> [(name, parent, head, tail)]
    expected("mixamo") -> {role id: bone name} (without prefix)

The real rigs (the user's Mixamo and SMPL files, Auto-Rig Pro's Mike, CloudRig's Storm...) are tested in
tests/blender/test_rigs.py when they are present.
"""

# Joint positions, left side (the right side mirrors X)
P = {
    "ground": (0.0, 0.0, 0.0), "hips": (0.0, 0.0, 1.0), "s1": (0.0, 0.0, 1.1), "s2": (0.0, 0.0, 1.2),
    "s3": (0.0, 0.0, 1.3), "s4": (0.0, 0.0, 1.38), "s5": (0.0, 0.0, 1.43), "neck": (0.0, 0.0, 1.48),
    "neck2": (0.0, 0.0, 1.55), "head": (0.0, 0.0, 1.6), "top": (0.0, 0.0, 1.8), "top2": (0.0, 0.0, 1.85),
    "clav": (0.02, 0.0, 1.45), "shoulder": (0.17, 0.0, 1.45), "arm_mid": (0.31, 0.0, 1.45),
    "elbow": (0.45, 0.0, 1.45), "fore_mid": (0.58, 0.0, 1.45), "wrist": (0.72, 0.0, 1.45),
    "knuckle": (0.8, 0.0, 1.45), "finger2": (0.85, 0.0, 1.45), "tip": (0.9, 0.0, 1.45),
    "hip": (0.1, 0.0, 1.0), "pelvis_l": (0.1, 0.0, 0.98), "thigh_mid": (0.1, 0.0, 0.78), "knee": (0.1, 0.0, 0.55),
    "shin_mid": (0.1, 0.0, 0.33), "ankle": (0.1, 0.0, 0.1), "ball": (0.1, -0.15, 0.02),
    "toe": (0.1, -0.22, 0.02),
}


def _mirror(point):
    return (-point[0], point[1], point[2])


def _build(entries, side_names, prefix=""):
    """entries: (name, parent, head point, tail point); "{s}" in a name or parent is the side, formatted with
    side_names = {"L": ..., "R": ...}. Sided entries are made for both sides."""
    bones = []
    for name, parent, head, tail in entries:
        if "{s}" in name:
            for side in ("L", "R"):
                s = side_names[side]
                h, t = P[head], P[tail]
                if side == "R":
                    h, t = _mirror(h), _mirror(t)
                bones.append((prefix + name.format(s=s), prefix + parent.format(s=s) if parent else None, h, t))
        else:
            bones.append((prefix + name, prefix + parent if parent else None, P[head], P[tail]))
    return bones


def _fingers(hand, name):
    return [(name.format(f="Middle", n=1), hand, "knuckle", "finger2"),
            (name.format(f="Middle", n=2), name.format(f="Middle", n=1), "finger2", "tip"),
            (name.format(f="Index", n=1), hand, "knuckle", "finger2")]


SCHEMES = {}


def _scheme(name, side_names, entries, expected):
    SCHEMES[name] = (side_names, entries, expected)


_scheme("mixamo", {"L": "Left", "R": "Right"}, [
    ("Hips", None, "hips", "s1"), ("Spine", "Hips", "s1", "s2"), ("Spine1", "Spine", "s2", "s4"),
    ("Spine2", "Spine1", "s4", "neck"), ("Neck", "Spine2", "neck", "head"), ("Head", "Neck", "head", "top"),
    ("HeadTop_End", "Head", "top", "top2"),
    ("{s}Shoulder", "Spine2", "clav", "shoulder"), ("{s}Arm", "{s}Shoulder", "shoulder", "elbow"),
    ("{s}ForeArm", "{s}Arm", "elbow", "wrist"), ("{s}Hand", "{s}ForeArm", "wrist", "knuckle"),
    *_fingers("{s}Hand", "{{s}}Hand{f}{n}"),
    ("{s}UpLeg", "Hips", "hip", "knee"), ("{s}Leg", "{s}UpLeg", "knee", "ankle"),
    ("{s}Foot", "{s}Leg", "ankle", "ball"), ("{s}ToeBase", "{s}Foot", "ball", "toe"),
    ("{s}Toe_End", "{s}ToeBase", "toe", "toe"),
], {"hips": "Hips", "spine": "Spine", "chest": "Spine1", "upper_chest": "Spine2", "neck": "Neck", "head": "Head",
    "shoulder": "{s}Shoulder", "upper_arm": "{s}Arm", "forearm": "{s}ForeArm", "hand": "{s}Hand",
    "thigh": "{s}UpLeg", "shin": "{s}Leg", "foot": "{s}Foot", "toes": "{s}ToeBase"})

# Unreal Engine 5 mannequin: root above the pelvis, 5 spine and 2 neck bones, twist bones beside the limbs,
# IK helper bones under the root
_scheme("ue5", {"L": "l", "R": "r"}, [
    ("root", None, "ground", "hips"), ("pelvis", "root", "hips", "s1"),
    ("spine_01", "pelvis", "s1", "s2"), ("spine_02", "spine_01", "s2", "s3"), ("spine_03", "spine_02", "s3", "s4"),
    ("spine_04", "spine_03", "s4", "s5"), ("spine_05", "spine_04", "s5", "neck"),
    ("neck_01", "spine_05", "neck", "neck2"), ("neck_02", "neck_01", "neck2", "head"), ("head", "neck_02", "head", "top"),
    ("clavicle_{s}", "spine_05", "clav", "shoulder"), ("upperarm_{s}", "clavicle_{s}", "shoulder", "elbow"),
    ("upperarm_twist_01_{s}", "upperarm_{s}", "arm_mid", "elbow"), ("lowerarm_{s}", "upperarm_{s}", "elbow", "wrist"),
    ("lowerarm_twist_01_{s}", "lowerarm_{s}", "fore_mid", "wrist"), ("hand_{s}", "lowerarm_{s}", "wrist", "knuckle"),
    *_fingers("hand_{s}", "{f}_0{n}_{{s}}"),
    ("thigh_{s}", "pelvis", "hip", "knee"), ("thigh_twist_01_{s}", "thigh_{s}", "thigh_mid", "knee"),
    ("calf_{s}", "thigh_{s}", "knee", "ankle"), ("calf_twist_01_{s}", "calf_{s}", "shin_mid", "ankle"),
    ("foot_{s}", "calf_{s}", "ankle", "ball"), ("ball_{s}", "foot_{s}", "ball", "toe"),
    ("ik_foot_root", "root", "ground", "ball"), ("ik_foot_{s}", "ik_foot_root", "ankle", "ball"),
    ("ik_hand_root", "root", "ground", "wrist"), ("ik_hand_{s}", "ik_hand_root", "wrist", "knuckle"),
], {"hips": "pelvis", "spine": "spine_01", "chest": "spine_03", "upper_chest": "spine_05", "neck": "neck_01",
    "upper_neck": "neck_02", "head": "head", "shoulder": "clavicle_{s}", "upper_arm": "upperarm_{s}",
    "forearm": "lowerarm_{s}", "hand": "hand_{s}", "thigh": "thigh_{s}", "shin": "calf_{s}", "foot": "foot_{s}",
    "toes": "ball_{s}"})

# SMPL: "Collar" is the collar bone and "Shoulder" the upper arm; "Wrist" is the hand, "Ankle" the foot
_scheme("smpl", {"L": "L", "R": "R"}, [
    ("m_avg_root", None, "ground", "hips"), ("m_avg_Pelvis", "m_avg_root", "hips", "s1"),
    ("m_avg_{s}_Hip", "m_avg_Pelvis", "hip", "knee"), ("m_avg_{s}_Knee", "m_avg_{s}_Hip", "knee", "ankle"),
    ("m_avg_{s}_Ankle", "m_avg_{s}_Knee", "ankle", "ball"), ("m_avg_{s}_Foot", "m_avg_{s}_Ankle", "ball", "toe"),
    ("m_avg_Spine1", "m_avg_Pelvis", "s1", "s2"), ("m_avg_Spine2", "m_avg_Spine1", "s2", "s4"),
    ("m_avg_Spine3", "m_avg_Spine2", "s4", "neck"), ("m_avg_Neck", "m_avg_Spine3", "neck", "head"),
    ("m_avg_Head", "m_avg_Neck", "head", "top"),
    ("m_avg_{s}_Collar", "m_avg_Spine3", "clav", "shoulder"), ("m_avg_{s}_Shoulder", "m_avg_{s}_Collar", "shoulder", "elbow"),
    ("m_avg_{s}_Elbow", "m_avg_{s}_Shoulder", "elbow", "wrist"), ("m_avg_{s}_Wrist", "m_avg_{s}_Elbow", "wrist", "knuckle"),
    ("m_avg_{s}_Hand", "m_avg_{s}_Wrist", "knuckle", "tip"),
], {"hips": "m_avg_Pelvis", "spine": "m_avg_Spine1", "chest": "m_avg_Spine2", "upper_chest": "m_avg_Spine3",
    "neck": "m_avg_Neck", "head": "m_avg_Head", "shoulder": "m_avg_{s}_Collar", "upper_arm": "m_avg_{s}_Shoulder",
    "forearm": "m_avg_{s}_Elbow", "hand": "m_avg_{s}_Wrist", "thigh": "m_avg_{s}_Hip", "shin": "m_avg_{s}_Knee",
    "foot": "m_avg_{s}_Ankle", "toes": "m_avg_{s}_Foot"})

# VRM (VRoid): "C" marks the center bones
_scheme("vrm", {"L": "L", "R": "R"}, [
    ("J_Bip_C_Hips", None, "hips", "s1"), ("J_Bip_C_Spine", "J_Bip_C_Hips", "s1", "s2"),
    ("J_Bip_C_Chest", "J_Bip_C_Spine", "s2", "s4"), ("J_Bip_C_UpperChest", "J_Bip_C_Chest", "s4", "neck"),
    ("J_Bip_C_Neck", "J_Bip_C_UpperChest", "neck", "head"), ("J_Bip_C_Head", "J_Bip_C_Neck", "head", "top"),
    ("J_Bip_{s}_Shoulder", "J_Bip_C_UpperChest", "clav", "shoulder"),
    ("J_Bip_{s}_UpperArm", "J_Bip_{s}_Shoulder", "shoulder", "elbow"),
    ("J_Bip_{s}_LowerArm", "J_Bip_{s}_UpperArm", "elbow", "wrist"), ("J_Bip_{s}_Hand", "J_Bip_{s}_LowerArm", "wrist", "knuckle"),
    ("J_Bip_{s}_UpperLeg", "J_Bip_C_Hips", "hip", "knee"), ("J_Bip_{s}_LowerLeg", "J_Bip_{s}_UpperLeg", "knee", "ankle"),
    ("J_Bip_{s}_Foot", "J_Bip_{s}_LowerLeg", "ankle", "ball"), ("J_Bip_{s}_ToeBase", "J_Bip_{s}_Foot", "ball", "toe"),
], {"hips": "J_Bip_C_Hips", "spine": "J_Bip_C_Spine", "chest": "J_Bip_C_Chest", "upper_chest": "J_Bip_C_UpperChest",
    "neck": "J_Bip_C_Neck", "head": "J_Bip_C_Head", "shoulder": "J_Bip_{s}_Shoulder", "upper_arm": "J_Bip_{s}_UpperArm",
    "forearm": "J_Bip_{s}_LowerArm", "hand": "J_Bip_{s}_Hand", "thigh": "J_Bip_{s}_UpperLeg",
    "shin": "J_Bip_{s}_LowerLeg", "foot": "J_Bip_{s}_Foot", "toes": "J_Bip_{s}_ToeBase"})

# Daz Genesis: a "pelvis" under the hips on the legs' side only, bend and twist bones in the limbs
_scheme("daz", {"L": "l", "R": "r"}, [
    ("hip", None, "hips", "s1"), ("pelvis", "hip", "hips", "hip"),
    ("{s}ThighBend", "pelvis", "hip", "thigh_mid"), ("{s}ThighTwist", "{s}ThighBend", "thigh_mid", "knee"),
    ("{s}Shin", "{s}ThighTwist", "knee", "ankle"), ("{s}Foot", "{s}Shin", "ankle", "ball"),
    ("{s}Metatarsals", "{s}Foot", "ankle", "ball"), ("{s}Toe", "{s}Foot", "ball", "toe"),
    ("abdomenLower", "hip", "s1", "s2"), ("abdomenUpper", "abdomenLower", "s2", "s3"),
    ("chestLower", "abdomenUpper", "s3", "s4"), ("chestUpper", "chestLower", "s4", "neck"),
    ("neckLower", "chestUpper", "neck", "neck2"), ("neckUpper", "neckLower", "neck2", "head"),
    ("head", "neckUpper", "head", "top"),
    ("{s}Collar", "chestUpper", "clav", "shoulder"), ("{s}ShldrBend", "{s}Collar", "shoulder", "arm_mid"),
    ("{s}ShldrTwist", "{s}ShldrBend", "arm_mid", "elbow"), ("{s}ForearmBend", "{s}ShldrTwist", "elbow", "fore_mid"),
    ("{s}ForearmTwist", "{s}ForearmBend", "fore_mid", "wrist"), ("{s}Hand", "{s}ForearmTwist", "wrist", "knuckle"),
], {"hips": "hip", "spine": "abdomenLower", "chest": "abdomenUpper", "upper_chest": "chestUpper",
    "neck": "neckLower", "upper_neck": "neckUpper", "head": "head", "shoulder": "{s}Collar",
    "upper_arm": "{s}ShldrBend", "forearm": "{s}ForearmBend", "hand": "{s}Hand", "thigh": "{s}ThighBend",
    "shin": "{s}Shin", "foot": "{s}Foot", "toes": "{s}Toe"})

# Character Creator / iClone
_scheme("cc", {"L": "L", "R": "R"}, [
    ("CC_Base_BoneRoot", None, "ground", "hips"), ("CC_Base_Hip", "CC_Base_BoneRoot", "hips", "s1"),
    ("CC_Base_Pelvis", "CC_Base_Hip", "hips", "hip"),
    ("CC_Base_{s}_Thigh", "CC_Base_Pelvis", "hip", "knee"), ("CC_Base_{s}_ThighTwist01", "CC_Base_{s}_Thigh", "thigh_mid", "knee"),
    ("CC_Base_{s}_Calf", "CC_Base_{s}_Thigh", "knee", "ankle"), ("CC_Base_{s}_Foot", "CC_Base_{s}_Calf", "ankle", "ball"),
    ("CC_Base_{s}_ToeBase", "CC_Base_{s}_Foot", "ball", "toe"),
    ("CC_Base_Waist", "CC_Base_Hip", "s1", "s2"), ("CC_Base_Spine01", "CC_Base_Waist", "s2", "s4"),
    ("CC_Base_Spine02", "CC_Base_Spine01", "s4", "neck"), ("CC_Base_NeckTwist01", "CC_Base_Spine02", "neck", "neck2"),
    ("CC_Base_NeckTwist02", "CC_Base_NeckTwist01", "neck2", "head"), ("CC_Base_Head", "CC_Base_NeckTwist02", "head", "top"),
    ("CC_Base_{s}_Clavicle", "CC_Base_Spine02", "clav", "shoulder"),
    ("CC_Base_{s}_Upperarm", "CC_Base_{s}_Clavicle", "shoulder", "elbow"),
    ("CC_Base_{s}_UpperarmTwist01", "CC_Base_{s}_Upperarm", "arm_mid", "elbow"),
    ("CC_Base_{s}_Forearm", "CC_Base_{s}_Upperarm", "elbow", "wrist"), ("CC_Base_{s}_Hand", "CC_Base_{s}_Forearm", "wrist", "knuckle"),
], {"hips": "CC_Base_Hip", "spine": "CC_Base_Waist", "chest": "CC_Base_Spine01", "upper_chest": "CC_Base_Spine02",
    "neck": "CC_Base_NeckTwist01", "upper_neck": "CC_Base_NeckTwist02", "head": "CC_Base_Head",
    "shoulder": "CC_Base_{s}_Clavicle", "upper_arm": "CC_Base_{s}_Upperarm", "forearm": "CC_Base_{s}_Forearm",
    "hand": "CC_Base_{s}_Hand", "thigh": "CC_Base_{s}_Thigh", "shin": "CC_Base_{s}_Calf", "foot": "CC_Base_{s}_Foot",
    "toes": "CC_Base_{s}_ToeBase"})

# Blender's naming (a rig built by hand, or Rigify's deform bones without their prefix), no collar bone, a
# forearm with a name saying nothing
_scheme("blender", {"L": "L", "R": "R"}, [
    ("pelvis", None, "hips", "s1"), ("spine", "pelvis", "s1", "s3"), ("chest", "spine", "s3", "neck"),
    ("neck", "chest", "neck", "head"), ("head", "neck", "head", "top"),
    ("upper_arm.{s}", "chest", "shoulder", "elbow"), ("Bone.{s}", "upper_arm.{s}", "elbow", "wrist"),
    ("hand.{s}", "Bone.{s}", "wrist", "knuckle"),
    ("thigh.{s}", "pelvis", "hip", "knee"), ("shin.{s}", "thigh.{s}", "knee", "ankle"),
    ("foot.{s}", "shin.{s}", "ankle", "ball"), ("toe.{s}", "foot.{s}", "ball", "toe"),
], {"hips": "pelvis", "spine": "spine", "upper_chest": "chest", "neck": "neck", "head": "head",
    "upper_arm": "upper_arm.{s}", "forearm": "Bone.{s}", "hand": "hand.{s}", "thigh": "thigh.{s}",
    "shin": "shin.{s}", "foot": "foot.{s}", "toes": "toe.{s}"})


def skeleton(scheme, prefix=""):
    side_names, entries, _expected = SCHEMES[scheme]
    return _build(entries, side_names, prefix)


def expected(scheme, prefix=""):
    """{role id: bone name} a detection should find"""
    side_names, _entries, roles = SCHEMES[scheme]
    result = {}
    for role, name in roles.items():
        if "{s}" in name:
            for side in ("L", "R"):
                result[f"{role}.{side}"] = prefix + name.format(s=side_names[side])
        else:
            result[role] = prefix + name
    return result
