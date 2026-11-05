"""Build a setup with an OLD version of the add-on (settings stored in scene.retarget_*), bake it, and save
the file without the bake. test_migration.py then opens it with the new version.

    blender -b --factory-startup --python tests/blender/legacy_setup.py -- <old add-on folder> <out dir>

<old add-on folder>: the add-on as it was before Phase 2, for example extracted with
    git archive 62864b7 | tar -x -C <folder>
Writes <out dir>/legacy.blend and <out dir>/legacy_bake.json (target bone world matrices on every frame).
"""
import importlib.util
import json
import os
import sys

import bpy
from mathutils import Quaternion

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bootstrap  # noqa: E402

CORRECTION = Quaternion((0.0, 1.0, 0.0), 0.3)
REST_OFFSET_BONES = {"Hips", "Spine"}


def register_old_addon(folder):
    spec = importlib.util.spec_from_file_location(
        "retargetor", os.path.join(folder, "__init__.py"), submodule_search_locations=[folder])
    package = importlib.util.module_from_spec(spec)
    sys.modules["retargetor"] = package
    spec.loader.exec_module(package)
    package.register()


def bake_snapshot(target, scene):
    """World matrices of the target bones on every frame of the scene"""
    data = {}
    for frame in range(scene.frame_start, scene.frame_end + 1):
        scene.frame_set(frame)
        data[frame] = {pb.name: [list(row) for row in target.matrix_world @ pb.matrix] for pb in target.pose.bones}
    return data


def main(old_addon, out_dir):
    source, target = bootstrap.make_test_scene()
    register_old_addon(old_addon)
    scene = bpy.context.scene

    scene.retarget_source_armature = source
    scene.retarget_target_armature = target
    assert bpy.ops.retargetor.setup_bone_list() == {'FINISHED'}
    for item in scene.retarget_bones:
        item.offset_mode = 'REST_OFFSET' if item.src_name in REST_OFFSET_BONES else 'ROLL'
        item.use_translation = item.src_name == "Hips"
        if item.src_name == "Forearm.L":
            item.has_corrective_offset = True
            item.corrective_offset = CORRECTION
    scene.retarget_bones_active_index = 2
    assert bpy.ops.retargetor.auto_translation_scale() == {'FINISHED'}

    bpy.context.view_layer.objects.active = target
    assert bpy.ops.retargetor.simple_retarget() == {'FINISHED'}
    snapshot = bake_snapshot(target, scene)
    with open(os.path.join(out_dir, "legacy_bake.json"), "w") as f:
        json.dump({"translation_scale": scene.retarget_translation_scale, "frames": snapshot}, f)

    # Save the setup only: the new version bakes it again
    target.animation_data_clear()
    for pb in target.pose.bones:
        pb.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
        pb.location = (0.0, 0.0, 0.0)
    scene.frame_set(1)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(out_dir, "legacy.blend"))
    print("legacy setup saved")


if __name__ == "__main__":
    args = bootstrap.script_args()
    main(args[0], args[1])
