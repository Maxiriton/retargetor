"""Phase 1 spike: import the generated motion and retarget it back onto the Rigify FK controls.

Run headless with Blender 5.1+:
    blender -b --factory-startup <rig.blend> --python soma_to_rig.py -- <out_dir> <motion.bvh> <fk|ik> <frame> [<frame> ...]

The motion is baked onto the FK controls. With "ik", it is then transferred onto the IK controls
and poles on every frame, and the limbs stay in IK.
Compares the rig at the key frames before and after (the rig should get its own key poses back),
then saves <out_dir>/result.blend with the rig and the generated SOMA motion.
"""
import json
import math
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import spike_common as common  # noqa: E402

LIMB_BONES = [name for name in common.RIG_TO_SOMA if not name.startswith("ORG-spine")]
END_BONES = ["ORG-hand.L", "ORG-hand.R", "ORG-foot.L", "ORG-foot.R", "ORG-spine.006"]


def snapshot(rig):
    """World head positions and directions of the ORG bones we compare."""
    data = {}
    for name in common.RIG_TO_SOMA:
        pb = rig.pose.bones[name]
        data[name] = ((rig.matrix_world @ pb.head).copy(), common.bone_direction(rig, name))
    return data


def bake_ik(rig, scene):
    """Transfer the baked FK chains onto the IK controls and poles, on every frame."""
    rest = common.ik_rest_data(rig)
    for frame in range(scene.frame_start, scene.frame_end + 1):
        scene.frame_set(frame)
        common.apply_fk_to_ik(rig, common.capture_fk(rig), rest)
        for name in common.ik_controls():
            pb = rig.pose.bones[name]
            pb.keyframe_insert("location", frame=frame)
            pb.keyframe_insert("rotation_quaternion", frame=frame)


def main(out_dir, bvh_path, target, frames):
    scene = bpy.context.scene
    rig = bpy.data.objects["rig"]
    with open(os.path.join(out_dir, "canonical.json")) as fp:
        canonical = json.load(fp)

    before = {}
    for frame in frames:
        scene.frame_set(frame)
        before[frame] = snapshot(rig)

    bpy.ops.import_anim.bvh(filepath=bvh_path, global_scale=0.01, axis_forward="-Z", axis_up="Y",
                            frame_start=canonical["first_frame"])
    soma = bpy.context.active_object
    soma.name = "SOMA_generated"
    # Undo Kimodo's canonicalization: Kimodo (x, 0, z) -> Blender (x, -z, 0)
    offset = canonical["kimodo_offset"]
    soma.location = (offset[0], -offset[2], 0.0)
    bpy.context.view_layer.update()

    common.register_retargetor()
    roll_bones = {name for name in common.SOMA_TO_RIG
                  if name not in ("Hips", "Chest", "Neck1", "Head")}
    scale = common.setup_mapping(scene, soma, rig, common.SOMA_TO_RIG, translation_bones={"Hips"},
                                 roll_bones=roll_bones)
    print(f"Translation scale SOMA -> rig: {scale[0]:.3f}")

    bpy.context.view_layer.objects.active = rig
    result = bpy.ops.retargetor.simple_retarget()
    print(f"Bake: {result}")
    if target == "ik":
        bake_ik(rig, scene)
        print("IK controls baked")

    for frame in frames:
        scene.frame_set(frame)
        after = snapshot(rig)
        angles = {n: math.degrees(before[frame][n][1].angle(after[n][1])) for n in LIMB_BONES}
        worst = sorted(angles.items(), key=lambda kv: -kv[1])[:3]
        dists = {n: (before[frame][n][0] - after[n][0]).length * 100 for n in END_BONES}
        print(f"Frame {frame}: limb directions vs original pose, mean {sum(angles.values()) / len(angles):.1f} deg, "
              f"worst {', '.join(f'{n} {a:.1f}' for n, a in worst)}")
        print(f"           positions vs original (cm): {', '.join(f'{n} {d:.1f}' for n, d in dists.items())}")

    scene.frame_set(frames[0])
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(out_dir, "result.blend"))


if __name__ == "__main__":
    args = sys.argv[sys.argv.index("--") + 1:]
    main(args[0], args[1], args[2], [int(f) for f in args[3:]])
