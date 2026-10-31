"""Phase 1 IK test: turn the FK key poses into the same poses animated with IK controls only.

Run headless with Blender 5.1+:
    blender -b --factory-startup <out_dir>/rig_keyposes.blend --python make_rig_ik.py -- <out_dir> <frame> [<frame> ...]

Limbs switched to IK (with pole vectors), IK controls and poles keyed on the key frames,
FK limb keys removed. Compares the resulting pose with the FK one, then writes
<out_dir>/rig_keyposes_ik.blend.
"""
import math
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import spike_common as common  # noqa: E402

LIMB_BONES = [name for name in common.RIG_TO_SOMA if not name.startswith("ORG-spine")]


def main(out_dir, frames):
    scene = bpy.context.scene
    rig = bpy.data.objects["rig"]
    rest = common.ik_rest_data(rig)

    fk_poses, org_dirs = {}, {}
    for frame in frames:
        scene.frame_set(frame)
        fk_poses[frame] = common.capture_fk(rig)
        org_dirs[frame] = {n: common.bone_direction(rig, n) for n in LIMB_BONES}

    # Remove the FK limb keys: the limbs are now animated with IK only
    fk_names = [n for chain in common.IK_CHAINS for n in chain["fk"]] + \
               [c["toe"][0] for c in common.IK_CHAINS if c["toe"]]
    bag = common.channelbag(rig)
    for fc in [fc for fc in bag.fcurves if any(f'"{n}"' in fc.data_path for n in fk_names)]:
        bag.fcurves.remove(fc)
    for name in fk_names:
        rig.pose.bones[name].rotation_quaternion = (1.0, 0.0, 0.0, 0.0)

    common.set_limbs_mode(rig, ik=True)
    for frame in frames:
        scene.frame_set(frame)
        common.apply_fk_to_ik(rig, fk_poses[frame], rest)
        for name in common.ik_controls():
            pb = rig.pose.bones[name]
            pb.keyframe_insert("location", frame=frame)
            pb.keyframe_insert("rotation_quaternion", frame=frame)

    for frame in frames:
        scene.frame_set(frame)
        angles = {n: math.degrees(org_dirs[frame][n].angle(common.bone_direction(rig, n))) for n in LIMB_BONES}
        worst = sorted(angles.items(), key=lambda kv: -kv[1])[:3]
        print(f"Frame {frame}: IK pose vs FK pose, mean {sum(angles.values()) / len(angles):.2f} deg, "
              f"worst {', '.join(f'{n} {a:.2f}' for n, a in worst)}")

    scene.frame_set(frames[0])
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(out_dir, "rig_keyposes_ik.blend"))


if __name__ == "__main__":
    args = sys.argv[sys.argv.index("--") + 1:]
    main(args[0], [int(f) for f in args[1:]])
