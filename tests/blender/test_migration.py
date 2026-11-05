"""Open a file made by the old version (legacy_setup.py): its scene.retarget_* setup must move onto the target
object, and baking it with the new version must give exactly the keys the old version baked.

    blender -b --factory-startup --python tests/blender/test_migration.py -- <dir with legacy.blend and legacy_bake.json>
"""
import json
import os
import sys

import bpy
from mathutils import Matrix

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bootstrap  # noqa: E402


def main(out_dir):
    checks = bootstrap.Checks("test_migration")
    bootstrap.register_addon()
    bpy.ops.wm.open_mainfile(filepath=os.path.join(out_dir, "legacy.blend"))
    with open(os.path.join(out_dir, "legacy_bake.json")) as f:
        legacy = json.load(f)

    scene = bpy.context.scene
    source, target = bpy.data.objects["SRC"], bpy.data.objects["TGT"]
    state = target.retargetor

    checks.check(scene.retargetor_target == target, "the scene's target armature is set")
    checks.check(state.source == source, "the source armature moved to the target object")
    checks.check([(i.src_name, i.target_name) for i in state.bones] ==
                 [("Hips", "hips"), ("Spine", "spine"), ("Arm.L", "arm.L"), ("Forearm.L", "forearm.L"),
                  ("Leg.L", "leg.L"), ("Shin.L", "shin.L")], "the bone list moved, in order")
    checks.check([i.offset_mode for i in state.bones] == ['REST_OFFSET', 'REST_OFFSET', 'ROLL', 'ROLL', 'ROLL', 'ROLL'],
                 "offset modes kept")
    checks.check([i.use_translation for i in state.bones] == [True, False, False, False, False, False],
                 "Use Translation kept")
    checks.check([i.has_corrective_offset for i in state.bones] == [False, False, False, True, False, False],
                 "corrections kept")
    checks.check(state.bones_active_index == 2, "active row kept")
    checks.close(state.translation_scale, legacy["translation_scale"], 1e-6, "translation scale kept")
    remaining = [n for n in ("retarget_bones", "retarget_target_armature")
                 if n in scene.bl_system_properties_get()]
    checks.check(not remaining, f"legacy scene properties removed ({remaining})")

    # A second load must not do anything (nothing left to migrate)
    from retargetor import migration
    checks.check(migration.migrate_all() == [], "migration runs only once")

    bpy.context.view_layer.objects.active = target
    checks.check(bpy.ops.retargetor.simple_retarget() == {'FINISHED'}, "bake with the new version")

    worst_rot, worst_loc = 0.0, 0.0
    for frame, bones in legacy["frames"].items():
        scene.frame_set(int(frame))
        for name, rows in bones.items():
            old = Matrix(rows)
            new = target.matrix_world @ target.pose.bones[name].matrix
            worst_rot = max(worst_rot, old.to_quaternion().rotation_difference(new.to_quaternion()).angle)
            worst_loc = max(worst_loc, (old.to_translation() - new.to_translation()).length)
    checks.below(worst_rot * 57.2958, 1e-3, "new bake vs old bake, worst rotation difference (deg)")
    checks.below(worst_loc * 100, 1e-4, "new bake vs old bake, worst position difference (cm)")
    checks.finish()


if __name__ == "__main__":
    main(bootstrap.script_args()[0])
