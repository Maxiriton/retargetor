"""Phase 1 spike: generate a Rigify rig and key three poses on its FK controls.

Run headless with Blender 5.1+:
    blender -b --factory-startup --python make_rig.py -- <out_dir>

Writes <out_dir>/rig_keyposes.blend. Scene at 30 fps (Kimodo's rate), frames 1-120.
The rig faces -Y, its left side is +X.
"""
import os
import sys

import addon_utils
import bpy
from mathutils import Matrix, Vector

KEY_FRAMES = (1, 61, 120)

# World-space bone directions per key frame (normalized when applied), and torso offsets.
# Bones not listed keep their rest direction.
POSES = {
    1: {
        "torso": Vector((0.0, 0.0, 0.0)),
        "dirs": {
            "upper_arm_fk.L": (0.15, 0.0, -1.0), "forearm_fk.L": (0.1, -0.15, -1.0),
            "upper_arm_fk.R": (-0.15, 0.0, -1.0), "forearm_fk.R": (-0.1, -0.15, -1.0),
        },
    },
    61: {
        "torso": Vector((0.0, -0.7, -0.03)),
        "dirs": {
            "thigh_fk.R": (0.0, -0.45, -0.9), "shin_fk.R": (0.0, -0.1, -1.0),
            "thigh_fk.L": (0.0, 0.35, -0.94), "shin_fk.L": (0.0, 0.5, -0.87),
            "upper_arm_fk.L": (0.15, -0.4, -0.9), "forearm_fk.L": (0.1, -0.7, -0.7),
            "upper_arm_fk.R": (-0.15, 0.35, -0.92), "forearm_fk.R": (-0.1, 0.0, -1.0),
        },
    },
    120: {
        "torso": Vector((0.0, -1.5, 0.0)),
        "dirs": {
            "upper_arm_fk.L": (0.25, 0.0, 0.97), "forearm_fk.L": (0.1, 0.0, 1.0),
            "upper_arm_fk.R": (-0.25, 0.0, 0.97), "forearm_fk.R": (-0.1, 0.0, 1.0),
        },
    },
}

# Every control keyed on every key frame, so each key pose is a full-body pose
KEYED_CONTROLS = [
    "torso", "hips", "chest", "neck", "head",
    *[f"{name}.{side}" for side in "LR" for name in (
        "shoulder", "upper_arm_fk", "forearm_fk", "hand_fk", "thigh_fk", "shin_fk", "foot_fk", "toe_fk")],
]


def set_direction(rig, name, direction):
    """Rotate a pose bone around its head so that its Y axis points to `direction` (world space)."""
    pb = rig.pose.bones[name]
    world = rig.matrix_world @ pb.matrix
    current = world.to_3x3() @ Vector((0.0, 1.0, 0.0))
    rotation = current.rotation_difference(Vector(direction).normalized()).to_matrix().to_4x4()
    head = world.to_translation()
    world = Matrix.Translation(head) @ rotation @ Matrix.Translation(-head) @ world
    pb.matrix = rig.matrix_world.inverted() @ world
    bpy.context.view_layer.update()


def reset_pose(rig):
    for pb in rig.pose.bones:
        pb.location = (0.0, 0.0, 0.0)
        pb.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
        pb.rotation_euler = (0.0, 0.0, 0.0)
    bpy.context.view_layer.update()


def key_controls(rig, frame):
    for name in KEYED_CONTROLS:
        pb = rig.pose.bones[name]
        data_path = "rotation_quaternion" if pb.rotation_mode == "QUATERNION" else "rotation_euler"
        pb.keyframe_insert(data_path, frame=frame)
        if name == "torso":
            pb.keyframe_insert("location", frame=frame)


def main(out_dir):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    addon_utils.enable("rigify", default_set=True)
    scene = bpy.context.scene
    scene.render.fps = 30
    scene.frame_start, scene.frame_end = KEY_FRAMES[0], KEY_FRAMES[-1]

    bpy.ops.object.armature_human_metarig_add()
    metarig = bpy.context.active_object
    bpy.ops.pose.rigify_generate()
    rig = bpy.data.objects["rig"]
    metarig.hide_set(True)
    metarig.hide_render = True

    # FK on every limb
    for name in ("upper_arm_parent.L", "upper_arm_parent.R", "thigh_parent.L", "thigh_parent.R"):
        rig.pose.bones[name]["IK_FK"] = 1.0

    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="POSE")
    for frame in KEY_FRAMES:
        scene.frame_set(frame)
        reset_pose(rig)
        pose = POSES[frame]
        torso = rig.pose.bones["torso"]
        torso.matrix = Matrix.Translation(pose["torso"]) @ torso.matrix
        bpy.context.view_layer.update()
        for name, direction in pose["dirs"].items():
            set_direction(rig, name, direction)
        key_controls(rig, frame)
    bpy.ops.object.mode_set(mode="OBJECT")

    # Sanity check: FK controls drive the ORG bones
    scene.frame_set(120)
    org_dir = (rig.matrix_world @ rig.pose.bones["ORG-upper_arm.L"].matrix).to_3x3() @ Vector((0, 1, 0))
    print(f"ORG-upper_arm.L direction at frame 120: {tuple(round(c, 2) for c in org_dir)} (expected arm up)")

    scene.frame_set(1)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(out_dir, "rig_keyposes.blend"))


if __name__ == "__main__":
    main(sys.argv[sys.argv.index("--") + 1])
