"""Phase 1 spike: check the baked result over the whole clip.

Run headless with Blender 5.1+:
    blender -b --factory-startup <out_dir>/result.blend --python check_result.py

Prints the number of keys on the rig, how closely the rig follows the generated SOMA motion
on every frame, the spine at the key frames, and the feet height (floor contact).
"""
import math
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import spike_common as common  # noqa: E402

scene = bpy.context.scene
rig = bpy.data.objects["rig"]
soma = bpy.data.objects["SOMA_generated"]

from bpy_extras.anim_utils import action_get_channelbag_for_slot  # noqa: E402

# Blender 5 actions are layered: F-curves live in the channelbag of the rig's slot
anim = rig.animation_data
channelbag = action_get_channelbag_for_slot(anim.action, anim.action_slot)
fcurve = next(fc for fc in channelbag.fcurves if fc.data_path == 'pose.bones["upper_arm_fk.L"].rotation_quaternion')
print(f"Keys on upper_arm_fk.L: {len(fcurve.keyframe_points)} (frames {scene.frame_start}-{scene.frame_end})")

worst_angle, worst_where, total, count = 0.0, "", 0.0, 0
feet_z = []
hips_gap = []
for frame in range(scene.frame_start, scene.frame_end + 1):
    scene.frame_set(frame)
    for src, tgt in common.RIG_TO_SOMA.items():
        if src.startswith("ORG-spine"):
            continue
        a = math.degrees(common.bone_direction(rig, src).angle(common.bone_direction(soma, tgt)))
        total += a
        count += 1
        if a > worst_angle:
            worst_angle, worst_where = a, f"{src} at frame {frame}"
    feet_z.append(min((rig.matrix_world @ rig.pose.bones[n].tail).z for n in ("ORG-toe.L", "ORG-toe.R")))
    hips_gap.append(((rig.matrix_world @ rig.pose.bones["ORG-spine"].head).xy
                     - (soma.matrix_world @ soma.pose.bones["Hips"].head).xy).length * 100)

print(f"Rig vs generated SOMA, limb directions over all frames: mean {total / count:.2f} deg, "
      f"max {worst_angle:.2f} deg ({worst_where})")
print(f"Hips horizontal gap rig vs SOMA: max {max(hips_gap):.1f} cm (expected: grows with the 1.11 scale)")
print(f"Lowest toe tip height over the clip: min {min(feet_z) * 100:.1f} cm, max {max(feet_z) * 100:.1f} cm")
