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
