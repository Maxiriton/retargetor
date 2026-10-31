"""Phase 1 IK test, FK-only approach: snap the FK controls to the IK key poses and switch the limbs to FK.

Run headless with Blender 5.1+:
    blender -b --factory-startup <out_dir>/rig_keyposes_ik.blend --python make_rig_ik2fk.py -- <out_dir> <frame> [<frame> ...]

The user's IK keys are kept; FK keys are added on the key frames and the limbs are switched to FK,
so the rest of the chain only reads and writes FK. Writes <out_dir>/ik_reference.json (the IK key
poses, for comparison at the end) and <out_dir>/rig_keyposes_ik2fk.blend.
"""
import json
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import spike_common as common  # noqa: E402


def main(out_dir, frames):
    scene = bpy.context.scene
    rig = bpy.data.objects["rig"]
    reference = common.keyposes_snapshot(rig, frames)
    with open(os.path.join(out_dir, "ik_reference.json"), "w") as fp:
        json.dump(reference, fp)

    for frame in frames:
        scene.frame_set(frame)
        common.snap_fk_to_ik(rig)
        for name in common.fk_controls():
            rig.pose.bones[name].keyframe_insert("rotation_quaternion", frame=frame)

    common.set_limbs_mode(rig, ik=False)
    common.compare_to_snapshot(rig, reference, "FK snap vs IK pose,")

    scene.frame_set(frames[0])
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(out_dir, "rig_keyposes_ik2fk.blend"))


if __name__ == "__main__":
    args = sys.argv[sys.argv.index("--") + 1:]
    main(args[0], [int(f) for f in args[1:]])
