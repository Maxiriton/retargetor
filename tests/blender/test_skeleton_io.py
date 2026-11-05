"""A model's armature built from a neutral Skeleton, and a Motion written in bulk into its F-curves.

    blender -b --factory-startup --python tests/blender/test_skeleton_io.py
"""
import math
import os
import sys
import time

import bpy
from mathutils import Euler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bootstrap  # noqa: E402


def compare(a, b, frames, names):
    """Worst bone direction (deg) and head position (cm) difference between two armatures"""
    scene = bpy.context.scene
    worst_dir = worst_head = 0.0
    for frame in frames:
        scene.frame_set(frame)
        for n in names:
            worst_dir = max(worst_dir, bootstrap.angle_deg(bootstrap.bone_direction(a, n), bootstrap.bone_direction(b, n)))
            worst_head = max(worst_head, ((a.matrix_world @ a.pose.bones[n].head)
                                          - (b.matrix_world @ b.pose.bones[n].head)).length * 100)
    return worst_dir, worst_head


def chain_skeleton(count):
    """A skeleton of `count` joints: a root and branches of 6 bones, like a body with fingers"""
    from retargetor.core.skeleton import Joint, Skeleton
    joints = [Joint("j0", None, (0.0, 0.0, 1.0), (0.0, 0.0, 1.1))]
    for i in range(1, count):
        parent = joints[i - 1] if i % 6 else joints[0]
        head = parent.tail
        tail = (head[0] + 0.05 * math.cos(i), head[1] + 0.05 * math.sin(i), head[2] + 0.02)
        joints.append(Joint(f"j{i}", parent.name, head, tail, roll=0.1 * i))
    return Skeleton(joints, root="j0")


def main():
    checks = bootstrap.Checks("test_skeleton_io")
    source, _target = bootstrap.make_test_scene()
    bootstrap.register_addon()
    from retargetor.core.pose_io import read_motion, write_motion, write_motion_fcurves
    from retargetor.core.skeleton import Joint, Skeleton
    from retargetor.core.skeleton_io import armature_backend, armature_skeleton, build_armature

    scene = bpy.context.scene
    view_layer = bpy.context.view_layer
    context = bpy.context

    # 1. Build an armature from a skeleton while another armature is in pose mode
    skeleton = Skeleton([Joint(n, p, h, t, math.radians(roll) + 0.3) for n, h, t, roll, p in bootstrap.SOURCE_BONES],
                        root="Hips")
    view_layer.objects.active = source
    bpy.ops.object.mode_set(mode='POSE')
    built = build_armature(context, skeleton, "MODEL", scene.collection, backend_id="test")
    checks.check(context.active_object == source and source.mode == 'POSE', "active object and pose mode restored")
    checks.check(built.mode == 'OBJECT' and len(built.data.bones) == len(bootstrap.SOURCE_BONES), "armature built")
    worst = max(max((built.data.bones[j.name].head_local - source.data.bones[j.name].head_local).length,
                    (built.data.bones[j.name].tail_local - source.data.bones[j.name].tail_local).length)
                for j in skeleton.joints)
    checks.below(worst * 100, 1e-4, "heads and tails as described (cm)")
    checks.check(abs(built.data.bones["Arm.L"].matrix_local.to_euler().y - source.data.bones["Arm.L"].matrix_local.to_euler().y) > 0.1,
                 "rolls as described (differ from the source by 0.3 rad)")
    checks.check(armature_skeleton(built) == skeleton and armature_backend(built) == "test", "skeleton kept on the armature")
    checks.check(all(pb.rotation_mode == 'QUATERNION' for pb in built.pose.bones), "quaternion rotation mode")
    bpy.ops.object.mode_set(mode='OBJECT')

    # 2. A motion written in bulk gives the same pose as the source, with another object transform and rolls
    built.location = (1.0, 2.0, 0.5)
    built.rotation_euler = Euler((0.0, 0.0, math.radians(70.0)))
    view_layer.update()
    names = [b[0] for b in bootstrap.SOURCE_BONES]
    # The source is translated and turned the same way, so the world poses can be compared directly
    source.location = built.location
    source.rotation_euler = built.rotation_euler
    view_layer.update()
    motion = read_motion(source, range(1, 11), scene, root_joint="Hips")
    write_motion_fcurves(built, motion, root_joint="Hips")
    worst_dir, worst_head = compare(source, built, range(1, 11), names)
    checks.below(worst_dir, 1e-3, "bulk-written motion, bone directions (deg)")
    checks.below(worst_head, 1e-3, "bulk-written motion, bone heads (cm)")

    # Partial poses: a joint missing from the motion keeps its rest pose relative to its parent
    for pose in motion.poses:
        del pose.rotations["Forearm.L"]
    write_motion_fcurves(built, motion, root_joint="Hips")
    scene.frame_set(5)
    q = built.pose.bones["Forearm.L"].rotation_quaternion
    checks.check(tuple(q) == (1.0, 0.0, 0.0, 0.0), "joint missing from the motion stays at rest")
    channelbag = built.animation_data.action.layers[0].strips[0].channelbags[0]
    checks.check(channelbag.fcurves.find('pose.bones["Forearm.L"].rotation_quaternion') is None,
                 "no F-curve for a joint missing from the motion, previous F-curves replaced")

    # 3. Speed, on a skeleton the size of SOMA (77 joints) and a 10 s clip at 30 fps
    big = build_armature(context, chain_skeleton(77), "BIG", scene.collection)
    other = build_armature(context, chain_skeleton(77), "BIG_COPY", scene.collection)
    for frame in range(1, 301):
        for i, pb in enumerate(big.pose.bones):
            pb.rotation_quaternion = Euler((0.01 * frame * (i % 3), 0.02 * i, 0.003 * frame)).to_quaternion()
            pb.keyframe_insert("rotation_quaternion", frame=frame)
        big.pose.bones["j0"].location = (0.0, 0.01 * frame, 0.0)
        big.pose.bones["j0"].keyframe_insert("location", frame=frame)
    motion = read_motion(big, range(1, 301), scene, root_joint="j0")
    start = time.perf_counter()
    write_motion_fcurves(other, motion, root_joint="j0")
    bulk = time.perf_counter() - start
    worst_dir, worst_head = compare(big, other, range(1, 301, 23), [pb.name for pb in big.pose.bones])
    checks.below(worst_dir, 1e-3, "77 joints, 300 frames: bone directions (deg)")
    checks.below(worst_head, 1e-3, "77 joints, 300 frames: bone heads (cm)")
    short = read_motion(big, range(1, 31), scene, root_joint="j0")
    other.animation_data_clear()
    start = time.perf_counter()
    write_motion(other, short, scene, view_layer, root_joint="j0")
    per_frame = (time.perf_counter() - start) / 30
    print(f"FINDING write_motion_fcurves: 77 joints x 300 frames in {bulk * 1000:.0f} ms; "
          f"write_motion: {per_frame * 1000:.0f} ms per frame ({per_frame * 300:.1f} s for 300 frames)")
    checks.check(bulk < per_frame * 300 / 10, "bulk writing at least 10 times faster")
    checks.finish()


if __name__ == "__main__":
    main()
