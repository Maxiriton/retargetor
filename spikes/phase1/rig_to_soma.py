"""Phase 1 spike: snap SOMA to the rig's key poses with the Retargetor and export Kimodo constraints.

Run headless with Blender 5.1+:
    blender -b --factory-startup <out_dir>/rig_keyposes.blend --python rig_to_soma.py -- <out_dir> <rest|roll> <frame> [<frame> ...]

Writes <out_dir>/constraints.json (Kimodo frame = Blender frame - first key frame),
<out_dir>/canonical.json (the offset removed to put the root at Kimodo's origin)
and <out_dir>/rig_to_soma.blend (SOMA keyed on the key frames, for viewing).
"""
import json
import math
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import spike_common as common  # noqa: E402


def main(out_dir, frames, mode):
    scene = bpy.context.scene
    rig = bpy.data.objects["rig"]
    soma = common.append_soma()
    skeleton = common.load_soma_skeleton()

    common.register_retargetor()
    from retargetor import retarget_operators

    # mode "rest": every bone in REST_OFFSET; mode "roll": limbs in ROLL, spine in REST_OFFSET
    roll_bones = {name for name in common.RIG_TO_SOMA if not name.startswith("ORG-spine")} if mode == "roll" else ()
    scale = common.setup_mapping(scene, rig, soma, common.RIG_TO_SOMA, translation_bones={"ORG-spine"},
                                 roll_bones=roll_bones)
    print(f"Translation scale rig -> SOMA: {scale[0]:.3f} (rig {scale[1]:.2f} m, SOMA {scale[2]:.2f} m)")

    local_rots, root_positions = [], []
    for frame in frames:
        scene.frame_set(frame)
        errors = retarget_operators.snap_full_pose(bpy.context)
        if errors:
            print(f"Frame {frame}: snap errors {sorted(errors)}")

        # Fidelity on the limbs: angle between each rig bone and its SOMA bone.
        # (Spine bones are laid out differently in both rigs, so their directions can't be compared.)
        angles = {
            src: math.degrees(common.bone_direction(rig, src).angle(common.bone_direction(soma, tgt)))
            for src, tgt in common.RIG_TO_SOMA.items() if not src.startswith("ORG-spine")
        }
        worst = sorted(angles.items(), key=lambda kv: -kv[1])[:3]
        print(f"Frame {frame}: limb directions rig vs SOMA, mean {sum(angles.values()) / len(angles):.1f} deg, "
              f"worst {', '.join(f'{n} {a:.1f}' for n, a in worst)}")

        for pb in soma.pose.bones:
            pb.keyframe_insert("rotation_quaternion", frame=frame)
            pb.keyframe_insert("location", frame=frame)

        local, root = common.soma_pose_to_kimodo(soma, skeleton)
        local_rots.append(local)
        root_positions.append(root)

    # Kimodo's canonical frame: root at XZ = (0, 0) on frame 0
    offset = [root_positions[0][0], 0.0, root_positions[0][2]]
    root_positions = [[p[0] - offset[0], p[1], p[2] - offset[2]] for p in root_positions]

    constraints = [{
        "type": "fullbody",
        "frame_indices": [f - frames[0] for f in frames],
        "local_joints_rot": local_rots,
        "root_positions": root_positions,
    }]
    with open(os.path.join(out_dir, "constraints.json"), "w") as fp:
        json.dump(constraints, fp)
    with open(os.path.join(out_dir, "canonical.json"), "w") as fp:
        json.dump({"kimodo_offset": offset, "first_frame": frames[0], "translation_scale": scale[0]}, fp)
    print(f"Root positions (Kimodo, m): {[[round(c, 3) for c in p] for p in root_positions]}")

    scene.frame_set(frames[0])
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(out_dir, "rig_to_soma.blend"))


if __name__ == "__main__":
    args = sys.argv[sys.argv.index("--") + 1:]
    main(args[0], [int(f) for f in args[2:]], mode=args[1])
