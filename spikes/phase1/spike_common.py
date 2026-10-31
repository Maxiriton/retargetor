"""Phase 1 spike: helpers shared by the Blender-side scripts (Kimodo conversions, retargetor setup)."""
import json
import os
import sys

import bpy
from mathutils import Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
PHASE0_OUT = os.path.join(HERE, "..", "phase0", "out")
SOMA_BLEND = os.path.join(PHASE0_OUT, "soma_reference.blend")
SOMA_SKELETON = os.path.join(PHASE0_OUT, "soma_skeleton.json")

# Blender (Z-up) -> Kimodo (Y-up): (x, y, z) -> (x, z, -y)
B_TO_K = Matrix(((1, 0, 0), (0, 0, 1), (0, -1, 0)))
K_TO_B = B_TO_K.transposed()

# Rigify ORG bones (read side) -> SOMA joints
RIG_TO_SOMA = {
    "ORG-spine": "Hips", "ORG-spine.001": "Spine1", "ORG-spine.002": "Spine2", "ORG-spine.003": "Chest",
    "ORG-spine.004": "Neck1", "ORG-spine.005": "Neck2", "ORG-spine.006": "Head",
}
# SOMA joints -> Rigify FK controls (write side)
SOMA_TO_RIG = {
    "Hips": "torso", "Chest": "chest", "Neck1": "neck", "Head": "head",
}
for side, soma_side in (("L", "Left"), ("R", "Right")):
    RIG_TO_SOMA.update({
        f"ORG-shoulder.{side}": f"{soma_side}Shoulder", f"ORG-upper_arm.{side}": f"{soma_side}Arm",
        f"ORG-forearm.{side}": f"{soma_side}ForeArm", f"ORG-hand.{side}": f"{soma_side}Hand",
        f"ORG-thigh.{side}": f"{soma_side}Leg", f"ORG-shin.{side}": f"{soma_side}Shin",
        f"ORG-foot.{side}": f"{soma_side}Foot", f"ORG-toe.{side}": f"{soma_side}ToeBase",
    })
    SOMA_TO_RIG.update({
        f"{soma_side}Shoulder": f"shoulder.{side}", f"{soma_side}Arm": f"upper_arm_fk.{side}",
        f"{soma_side}ForeArm": f"forearm_fk.{side}", f"{soma_side}Hand": f"hand_fk.{side}",
        f"{soma_side}Leg": f"thigh_fk.{side}", f"{soma_side}Shin": f"shin_fk.{side}",
        f"{soma_side}Foot": f"foot_fk.{side}", f"{soma_side}ToeBase": f"toe_fk.{side}",
    })


# Rigify limbs: FK chain, IK control, pole control, the bone holding the IK_FK switch, toe controls (legs)
IK_CHAINS = []
for side in "LR":
    IK_CHAINS.append({"fk": [f"upper_arm_fk.{side}", f"forearm_fk.{side}", f"hand_fk.{side}"],
                      "ik": f"hand_ik.{side}", "pole": f"upper_arm_ik_target.{side}",
                      "switch": f"upper_arm_parent.{side}", "toe": None})
    IK_CHAINS.append({"fk": [f"thigh_fk.{side}", f"shin_fk.{side}", f"foot_fk.{side}"],
                      "ik": f"foot_ik.{side}", "pole": f"thigh_ik_target.{side}",
                      "switch": f"thigh_parent.{side}", "toe": (f"toe_fk.{side}", f"toe_ik.{side}")})


def ik_rest_data(rig):
    """Rest relations used to place the IK controls from an FK pose (armature space)."""
    bones = rig.data.bones
    data = {}
    for chain in IK_CHAINS:
        upper, _mid, end = (bones[n].matrix_local for n in chain["fk"])
        pole = bones[chain["pole"]].head_local
        elbow = bones[chain["fk"][1]].head_local
        data[chain["ik"]] = {
            "end_to_ik": end.inverted() @ bones[chain["ik"]].matrix_local,
            # Pole offset from the elbow/knee, in the upper bone's rest frame
            "pole_local": upper.to_3x3().inverted() @ (pole - elbow),
        }
        if chain["toe"]:
            toe_fk, toe_ik = chain["toe"]
            data[chain["ik"]]["toe_fk_to_ik"] = bones[toe_fk].matrix_local.inverted() @ bones[toe_ik].matrix_local
    return data


def capture_fk(rig):
    """Armature-space matrices of the FK chains (and toes) at the current frame."""
    names = [n for chain in IK_CHAINS for n in chain["fk"]] + [c["toe"][0] for c in IK_CHAINS if c["toe"]]
    return {n: rig.pose.bones[n].matrix.copy() for n in names}


def apply_fk_to_ik(rig, fk, rest):
    """Place the IK controls and poles so the IK chains reproduce the given FK matrices.
    Hands, feet and toes are exact. Elbows and knees are not: Rigify's IK bones have ik_stretch 0.1,
    so the solver shrinks the bones slightly instead of bending them fully (see README)."""
    pbones = rig.pose.bones
    for chain in IK_CHAINS:
        data = rest[chain["ik"]]
        upper, mid, end = (fk[n] for n in chain["fk"])
        pbones[chain["ik"]].matrix = end @ data["end_to_ik"]
        pole = pbones[chain["pole"]]
        # The pole goes in the plane of the FK chain, on the elbow/knee side, so the IK solver puts the
        # elbow/knee where the FK chain has it. A straight limb has no plane: fall back to the rest offset.
        root, joint, tip = upper.to_translation(), mid.to_translation(), end.to_translation()
        axis = (tip - root).normalized()
        bend = (joint - root) - axis * (joint - root).dot(axis)
        rest_offset = upper.to_3x3().normalized() @ data["pole_local"]
        if bend.length > 0.01:
            pole_pos = joint + bend.normalized() * rest_offset.length
        else:
            pole_pos = joint + rest_offset
        pole.matrix = Matrix.Translation(pole_pos) @ pole.matrix.to_3x3().to_4x4()
    bpy.context.view_layer.update()
    for chain in IK_CHAINS:
        if chain["toe"]:
            toe_fk, toe_ik = chain["toe"]
            pbones[toe_ik].matrix = fk[toe_fk] @ rest[chain["ik"]]["toe_fk_to_ik"]
    bpy.context.view_layer.update()


def fk_controls():
    """FK controls of the limbs, parents first (toes last)."""
    return [n for chain in IK_CHAINS for n in chain["fk"]] + [c["toe"][0] for c in IK_CHAINS if c["toe"]]


def org_name(fk_name):
    """ORG bone followed by an FK control: upper_arm_fk.L -> ORG-upper_arm.L"""
    return "ORG-" + fk_name.replace("_fk", "")


def snap_fk_to_ik(rig):
    """Rotate the FK controls so the FK chains match the current IK pose (read from the ORG bones).
    Only rotations are copied: FK controls keep their own length, so the IK stretch is not carried over."""
    pbones = rig.pose.bones
    wanted = {n: pbones[org_name(n)].matrix.to_quaternion() for n in fk_controls()}
    for name in fk_controls():
        pb = pbones[name]
        pb.matrix = Matrix.LocRotScale(pb.matrix.to_translation(), wanted[name], None)
        bpy.context.view_layer.update()


def keyposes_snapshot(rig, frames):
    """World head positions and directions of the mapped ORG bones at the given frames."""
    scene = bpy.context.scene
    snapshot = {}
    for frame in frames:
        scene.frame_set(frame)
        snapshot[frame] = {n: (list(rig.matrix_world @ rig.pose.bones[n].head), list(bone_direction(rig, n)))
                           for n in RIG_TO_SOMA}
    return snapshot


def compare_to_snapshot(rig, snapshot, label):
    """Print how far the rig's current animation is from a keyposes_snapshot."""
    import math
    scene = bpy.context.scene
    ends = ["ORG-hand.L", "ORG-hand.R", "ORG-foot.L", "ORG-foot.R", "ORG-shin.L", "ORG-shin.R",
            "ORG-forearm.L", "ORG-forearm.R", "ORG-spine.006"]
    for frame, bones in snapshot.items():
        scene.frame_set(int(frame))
        angles = {n: math.degrees(Vector(bones[n][1]).angle(bone_direction(rig, n)))
                  for n in bones if not n.startswith("ORG-spine")}
        worst = sorted(angles.items(), key=lambda kv: -kv[1])[:3]
        dists = {n: ((rig.matrix_world @ rig.pose.bones[n].head) - Vector(bones[n][0])).length * 100 for n in ends}
        print(f"{label} frame {frame}: limb directions mean {sum(angles.values()) / len(angles):.2f} deg, "
              f"worst {', '.join(f'{n} {a:.2f}' for n, a in worst)}")
        print(f"{label}   positions (cm): {', '.join(f'{n} {d:.2f}' for n, d in dists.items())}")


def ik_controls():
    names = []
    for chain in IK_CHAINS:
        names += [chain["ik"], chain["pole"]] + ([chain["toe"][1]] if chain["toe"] else [])
    return names


def set_limbs_mode(rig, ik):
    for chain in IK_CHAINS:
        switch = rig.pose.bones[chain["switch"]]
        switch["IK_FK"] = 0.0 if ik else 1.0
        switch["pole_vector"] = bool(ik)
    bpy.context.view_layer.update()


def channelbag(obj):
    """F-curves of an object's action (Blender 5 layered actions)."""
    from bpy_extras.anim_utils import action_get_channelbag_for_slot
    return action_get_channelbag_for_slot(obj.animation_data.action, obj.animation_data.action_slot)


def load_soma_skeleton():
    with open(SOMA_SKELETON) as f:
        return json.load(f)


def append_soma(name="SOMA"):
    """Append the SOMA reference armature (from Phase 0) in its rest pose, without animation."""
    with bpy.data.libraries.load(SOMA_BLEND, link=False) as (data_from, data_to):
        data_to.objects = ["SOMA_reference"]
    soma = data_to.objects[0]
    soma.name = name
    bpy.context.scene.collection.objects.link(soma)
    soma.animation_data_clear()
    for pb in soma.pose.bones:
        pb.rotation_mode = "QUATERNION"
        pb.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
        pb.location = (0.0, 0.0, 0.0)
    bpy.context.view_layer.update()
    return soma


def register_retargetor():
    """Import the add-on from the repository and register it."""
    repo_parent = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
    if repo_parent not in sys.path:
        sys.path.insert(0, repo_parent)
    import retargetor
    retargetor.register()
    return retargetor


def setup_mapping(scene, source, target, pairs, translation_bones, roll_bones=()):
    """Fill the retargetor bone list with the given (source bone -> target bone) pairs.
    Bones in `roll_bones` use the ROLL offset mode, the others REST_OFFSET."""
    scene.retarget_source_armature = source
    scene.retarget_target_armature = target
    scene.retarget_bones.clear()
    for src_name, target_name in pairs.items():
        item = scene.retarget_bones.add()
        item.src_name = src_name
        item.offset_mode = "ROLL" if src_name in roll_bones else "REST_OFFSET"
        item.use_translation = src_name in translation_bones
        item.target_name = target_name  # computes the rest offsets
    from retargetor import setup_operators
    return setup_operators.update_translation_scale(bpy.context)


def bone_direction(arm, name):
    return ((arm.matrix_world @ arm.pose.bones[name].matrix).to_3x3() @ Vector((0.0, 1.0, 0.0))).normalized()


def to_kimodo(v):
    return list(B_TO_K @ v)


def global_rotation_kimodo(arm, name):
    """Rotation of the bone relative to its rest orientation, in Kimodo's world basis."""
    pb = arm.pose.bones[name]
    rest = (arm.matrix_world @ pb.bone.matrix_local).to_3x3().normalized()
    pose = (arm.matrix_world @ pb.matrix).to_3x3().normalized()
    return B_TO_K @ (pose @ rest.transposed()) @ K_TO_B


def soma_pose_to_kimodo(soma, skeleton):
    """Kimodo full-body constraint data for the current pose: (local_joints_rot, root_position)."""
    joints77 = skeleton["joints77"]
    parent77 = dict(zip(joints77, skeleton["parents77"]))
    globals_ = {name: global_rotation_kimodo(soma, name) for name in joints77}
    local = []
    for name in skeleton["joints30"]:
        parent = parent77[name]
        g = globals_[name] if parent is None else globals_[parent].transposed() @ globals_[name]
        axis, angle = g.to_quaternion().to_axis_angle()
        local.append(list(axis * angle))
    root = to_kimodo(soma.matrix_world @ soma.pose.bones["Hips"].head)
    return local, root
