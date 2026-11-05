"""Phase 0 spike: import a Kimodo BVH in Blender and check the conversions both ways.

Run headless with Blender 5.1+:
    blender -b --factory-startup --python blender_roundtrip.py -- <motion.bvh> <motion.npz> <soma_skeleton.json> <out_dir> <frame> [<frame> ...]

1. Import: the bone heads of the imported armature must match Kimodo's posed_joints.
2. Export: rebuild Kimodo constraints (local_joints_rot, root_positions) from the Blender pose
   at the given Kimodo frames, and write them to <out_dir>/roundtrip_constraints.json.
   check_keyframes.py then compares them with the motion using Kimodo's own FK.
3. Save the imported armature as <out_dir>/soma_reference.blend.

Kimodo frame f is Blender frame f + 1 (the BVH importer starts at frame 1).
"""
import json
import os
import sys

import bpy
import numpy as np
from mathutils import Matrix

# Blender (Z-up) -> Kimodo (Y-up): (x, y, z) -> (x, z, -y)
B_TO_K = Matrix(((1, 0, 0), (0, 0, 1), (0, -1, 0)))
K_TO_B = B_TO_K.transposed()


def to_kimodo(v):
    return list(B_TO_K @ v)


def global_rotation_kimodo(arm, name):
    """Rotation of the bone relative to its rest orientation, in Kimodo's world basis."""
    pose_bone = arm.pose.bones[name]
    rest = (arm.matrix_world @ pose_bone.bone.matrix_local).to_3x3().normalized()
    pose = (arm.matrix_world @ pose_bone.matrix).to_3x3().normalized()
    return B_TO_K @ (pose @ rest.transposed()) @ K_TO_B


def axis_angle(m):
    axis, angle = m.to_quaternion().to_axis_angle()
    return list(axis * angle)


def main(bvh_path, npz_path, skeleton_path, out_dir, frames):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_anim.bvh(
        filepath=bvh_path,
        global_scale=0.01,  # centimeters -> meters
        axis_forward="-Z",
        axis_up="Y",
        update_scene_fps=True,
        update_scene_duration=True,
    )
    arm = bpy.context.active_object
    arm.name = "SOMA_reference"
    scene = bpy.context.scene
    print(f"Imported '{arm.name}': {len(arm.data.bones)} bones, scene fps {scene.render.fps}")

    motion = np.load(npz_path)
    skeleton = json.load(open(skeleton_path))
    joints77 = skeleton["joints77"]

    # 1. Import check: bone heads vs posed_joints
    worst = 0.0
    for f in range(0, motion["posed_joints"].shape[0], 10):
        scene.frame_set(f + 1)
        for j, name in enumerate(joints77):
            head = to_kimodo(arm.matrix_world @ arm.pose.bones[name].head)
            worst = max(worst, float(np.linalg.norm(np.array(head) - motion["posed_joints"][f, j])))
    print(f"Import check: max head position error {worst * 100:.3f} cm (every 10th frame, 77 joints)")

    # 2. Export check: constraints rebuilt from the Blender pose.
    # Kimodo's 30-joint local rotations are a slice of the 77-joint ones, so each rotation is
    # relative to the joint's 77-joint parent (for the hand end joints: the last finger bone).
    joints30 = skeleton["joints30"]
    parent77 = dict(zip(joints77, skeleton["parents77"]))
    local_rots, root_positions = [], []
    for f in frames:
        scene.frame_set(f + 1)
        globals_ = {name: global_rotation_kimodo(arm, name) for name in joints77}
        local = []
        for name in joints30:
            parent = parent77[name]
            g = globals_[name]
            local.append(axis_angle(g if parent is None else globals_[parent].transposed() @ g))
        local_rots.append(local)
        root_positions.append(to_kimodo(arm.matrix_world @ arm.pose.bones["Hips"].head))

    constraints = [{
        "type": "fullbody",
        "frame_indices": frames,
        "local_joints_rot": local_rots,
        "root_positions": root_positions,
    }]
    with open(os.path.join(out_dir, "roundtrip_constraints.json"), "w") as fp:
        json.dump(constraints, fp)

    # Global rotations compared directly with the NPZ
    worst_deg = 0.0
    for f in frames:
        scene.frame_set(f + 1)
        for name in joints30:
            j = joints77.index(name)
            diff = global_rotation_kimodo(arm, name).transposed() @ Matrix(motion["global_rot_mats"][f, j].tolist())
            worst_deg = max(worst_deg, np.degrees(diff.to_quaternion().angle))
    print(f"Export check: max global rotation error {worst_deg:.3f} deg at frames {frames} (30 joints)")

    # 3. Reference armature
    scene.frame_set(1)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(out_dir, "soma_reference.blend"))


if __name__ == "__main__":
    args = sys.argv[sys.argv.index("--") + 1:]
    main(args[0], args[1], args[2], args[3], [int(f) for f in args[4:]])
