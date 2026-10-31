"""Neutral Pose / Motion read from one armature and written to another one with the same joints.

    blender -b --factory-startup --python tests/blender/test_pose_io.py
"""
import json
import math
import os
import sys

import bpy
from mathutils import Quaternion

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bootstrap  # noqa: E402


def worst_difference(a, b, frames):
    """Worst rotation (deg) and position (cm) difference between the bones of two armatures, in world space"""
    scene = bpy.context.scene
    worst_rot = worst_loc = 0.0
    for frame in frames:
        scene.frame_set(frame)
        for pb in a.pose.bones:
            ma = a.matrix_world @ pb.matrix
            mb = b.matrix_world @ b.pose.bones[pb.name].matrix
            worst_rot = max(worst_rot, math.degrees(ma.to_quaternion().rotation_difference(mb.to_quaternion()).angle))
            worst_loc = max(worst_loc, (ma.to_translation() - mb.to_translation()).length * 100)
    return worst_rot, worst_loc


def main():
    checks = bootstrap.Checks("test_pose_io")
    source, _target = bootstrap.make_test_scene()
    bootstrap.register_addon()
    from retargetor.core.motion import Motion
    from retargetor.core.pose_io import read_motion, read_pose, write_motion, write_pose

    scene = bpy.context.scene
    view_layer = bpy.context.view_layer
    # Same joints, other bone rolls and another object transform: rotations from rest don't depend on them
    bones = [(n, h, t, roll + 40.0, p) for n, h, t, roll, p in bootstrap.SOURCE_BONES]
    copy = bootstrap.make_armature("COPY", bones)
    copy.rotation_euler = (0.0, 0.0, 0.0)

    scene.frame_set(7)
    pose = read_pose(source, root_joint="Hips")
    checks.check(len(pose.rotations) == len(source.pose.bones), "every joint read")
    write_pose(copy, pose, view_layer, root_joint="Hips")
    _rot, loc = worst_difference(source, copy, [7])
    # Rolls differ, so compare the bone directions and heads, not the full matrices
    worst_dir = max(bootstrap.angle_deg(bootstrap.bone_direction(source, n), bootstrap.bone_direction(copy, n))
                    for n in source.pose.bones.keys())
    checks.below(worst_dir, 1e-3, "written pose, bone directions (deg)")
    checks.below(loc, 1e-3, "written pose, bone heads (cm)")
    again = read_pose(copy, root_joint="Hips")
    worst_q = max(math.degrees(Quaternion(pose.rotations[n]).rotation_difference(Quaternion(again.rotations[n])).angle)
                  for n in pose.rotations)
    checks.below(worst_q, 1e-3, "read back the same rotations (deg)")

    motion = read_motion(source, range(1, 11), scene, root_joint="Hips")
    motion = Motion.from_dict(json.loads(json.dumps(motion.to_dict())))
    checks.check((motion.start_frame, motion.end_frame) == (1, 10), "motion on frames 1-10")
    copy.animation_data_clear()
    write_motion(copy, motion, scene, view_layer, root_joint="Hips", keytype='GENERATED')
    worst_dir = worst_head = 0.0
    for frame in range(1, 11):
        scene.frame_set(frame)
        for n in source.pose.bones.keys():
            worst_dir = max(worst_dir, bootstrap.angle_deg(bootstrap.bone_direction(source, n),
                                                           bootstrap.bone_direction(copy, n)))
            worst_head = max(worst_head, ((source.matrix_world @ source.pose.bones[n].head)
                                          - (copy.matrix_world @ copy.pose.bones[n].head)).length * 100)
    checks.below(worst_dir, 1e-3, "keyed motion, bone directions (deg)")
    checks.below(worst_head, 1e-3, "keyed motion, bone heads (cm)")
    from bpy_extras.anim_utils import action_get_channelbag_for_slot
    channelbag = action_get_channelbag_for_slot(copy.animation_data.action, copy.animation_data.action_slot)
    types = {k.type for fc in channelbag.fcurves for k in fc.keyframe_points}
    checks.check(types == {'GENERATED'}, f"keys typed GENERATED ({types})")
    checks.finish()


if __name__ == "__main__":
    main()
