"""The existing panel's workflow on two small armatures, with the setup stored on the character.

    blender -b --factory-startup --python tests/blender/test_panel.py -- <scratch dir>

Covers: bone list, translation scale, bake, snapping, corrections, JSON round trip, two characters in one
scene, the selection handler, and drawing the panels (with a layout that checks every property and operator).
"""
import os
import sys

import bpy
from mathutils import Quaternion, Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bootstrap  # noqa: E402
from bootstrap import angle_deg, bone_direction  # noqa: E402

LIMBS = [("Arm.L", "arm.L"), ("Forearm.L", "forearm.L"), ("Leg.L", "leg.L"), ("Shin.L", "shin.L")]


class CheckingLayout:
    """Stands in for a UILayout: every property and operator the panel uses must exist."""

    def __init__(self, errors):
        self.errors = errors
        self.enabled = True

    def _sub(self, *_args, **_kwargs):
        return CheckingLayout(self.errors)

    row = column = box = split = _sub

    def label(self, **_kwargs):
        pass

    def separator(self, **_kwargs):
        pass

    def _check_prop(self, data, name):
        if data is None or name not in data.bl_rna.properties:
            self.errors.append(f"unknown property {name} on {data}")

    def prop(self, data, name, **_kwargs):
        self._check_prop(data, name)

    def prop_search(self, data, name, search_data, search_name, **_kwargs):
        self._check_prop(data, name)
        self._check_prop(search_data, search_name)

    def operator(self, idname, **_kwargs):
        module, name = idname.split(".")
        if not hasattr(getattr(bpy.ops, module), name) or getattr(getattr(bpy.ops, module), name).idname() is None:
            self.errors.append(f"unknown operator {idname}")
        return type("Props", (), {})()

    def template_list(self, list_type, _list_id, data, name, active_data, active_name, **_kwargs):
        if not hasattr(bpy.types, list_type):
            self.errors.append(f"unknown UIList {list_type}")
        self._check_prop(data, name)
        self._check_prop(active_data, active_name)
        ui_list = getattr(bpy.types, list_type)
        for index, item in enumerate(getattr(data, name)):
            ui_list.draw_item(None, bpy.context, CheckingLayout(self.errors), data, item, 0, active_data, active_name, index)


def draw_panels():
    errors = []
    from retargetor import ui
    for panel in (ui.RETARGETOR_PT_RetargetPanel, ui.RETARGETOR_PT_RigProfilePanel):
        fake = type("Panel", (), {"layout": CheckingLayout(errors)})()
        panel.draw(fake, bpy.context)
    return errors


def directions_match(source, target, frames):
    scene = bpy.context.scene
    worst = 0.0
    for frame in frames:
        scene.frame_set(frame)
        for src, tgt in LIMBS:
            worst = max(worst, angle_deg(bone_direction(source, src), bone_direction(target, tgt)))
    return worst


def main(scratch):
    checks = bootstrap.Checks("test_panel")
    source, target = bootstrap.make_test_scene()
    bootstrap.register_addon()
    scene = bpy.context.scene
    view_layer = bpy.context.view_layer

    checks.check(draw_panels() == [], "panels draw with no character")
    checks.check(not bpy.ops.retargetor.setup_bone_list.poll(), "Setup Bone list needs a character")

    scene.retargetor_target = target
    state = target.retargetor
    state.source = source
    checks.check(draw_panels() == [], "panels draw with an empty bone list")

    # Bone list, guessed from the names
    checks.check(bpy.ops.retargetor.setup_bone_list() == {'FINISHED'}, "Setup Bone list")
    checks.check([(i.src_name, i.target_name) for i in state.bones] ==
                 [("Hips", "hips"), ("Spine", "spine")] + LIMBS, "bones matched by name")
    for item in state.bones:
        item.offset_mode = 'REST_OFFSET' if item.src_name in ("Hips", "Spine") else 'ROLL'
        item.use_translation = item.src_name == "Hips"
    checks.check(bpy.ops.retargetor.auto_translation_scale() == {'FINISHED'}, "Auto translation scale")
    # Z extent of the mapped bone heads: 1.65 - 0.6 on the target, 1.35 - 0.5 on the source
    checks.close(state.translation_scale, 1.05 / 0.85, 1e-6, "translation scale = height ratio")
    view_layer.objects.active = target
    checks.check(draw_panels() == [], "panels draw with a bone list")

    # Bake over the scene range
    checks.check(bpy.ops.retargetor.simple_retarget() == {'FINISHED'}, "Retarget (bake)")
    checks.below(directions_match(source, target, range(1, 11)), 1e-3, "limbs follow the source (deg)")
    scene.frame_set(10)
    src_move = source.matrix_world @ source.pose.bones["Hips"].head - source.matrix_world @ source.data.bones["Hips"].head_local
    tgt_move = target.matrix_world @ target.pose.bones["hips"].head - target.matrix_world @ target.data.bones["hips"].head_local
    checks.below((tgt_move - state.translation_scale * src_move).length * 100, 1e-3, "hips move scaled (cm)")
    from bpy_extras.anim_utils import action_get_channelbag_for_slot
    channelbag = action_get_channelbag_for_slot(target.animation_data.action, target.animation_data.action_slot)
    fcurve = channelbag.fcurves.find('pose.bones["arm.L"].rotation_quaternion', index=0)
    checks.check(len(fcurve.keyframe_points) == 10, "one key per frame")
    checks.check(channelbag.fcurves.find('pose.bones["arm.L"].location', index=0) is None, "no location key on limbs")

    # Snapping, in Pose Mode on the target
    target.animation_data_clear()
    bpy.ops.object.mode_set(mode='POSE')
    scene.frame_set(7)
    checks.check(bpy.ops.retargetor.snap_full_pose() == {'FINISHED'}, "Snap full pose")
    checks.below(directions_match(source, target, [7]), 1e-3, "snapped pose follows the source (deg)")
    target.data.bones.active = target.data.bones["forearm.L"]
    target.pose.bones["forearm.L"].rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
    checks.check(bpy.ops.retargetor.snap_selected_bone() == {'FINISHED'}, "Snap active bone")
    checks.below(angle_deg(bone_direction(source, "Forearm.L"), bone_direction(target, "forearm.L")), 1e-3,
                 "active bone snapped (deg)")

    # Recording a correction on the forearm
    state.bones_active_index = 3
    checks.check(bpy.ops.retargetor.record_adjustment() == {'FINISHED'}, "Record Correction")
    checks.check(state.is_recording, "recording")
    checks.check(draw_panels() == [], "panels draw while recording")
    extra = Quaternion((0.0, 1.0, 0.0), 0.4)
    pb = target.pose.bones["forearm.L"]
    pb.rotation_quaternion = pb.rotation_quaternion @ extra
    view_layer.update()
    wanted = (target.matrix_world @ pb.matrix).to_quaternion()
    checks.check(bpy.ops.retargetor.finish_record() == {'FINISHED'}, "Finish Recording")
    checks.check(state.bones[3].has_corrective_offset and not state.is_recording, "correction stored")
    pb.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
    bpy.ops.retargetor.snap_selected_bone()
    view_layer.update()
    got = (target.matrix_world @ pb.matrix).to_quaternion()
    checks.below(wanted.rotation_difference(got).angle * 57.3, 1e-3, "snap applies the correction (deg)")

    # A new target bone clears the correction
    state.bones[3].target_name = "shin.L"
    checks.check(not state.bones[3].has_corrective_offset, "changing the target clears the correction")
    state.bones[3].target_name = "forearm.L"
    state.bones[3].has_corrective_offset = True
    state.bones[3].corrective_offset = extra
    checks.check(bpy.ops.retargetor.clear_record() == {'FINISHED'}, "Clear Record")
    checks.check(not state.bones[3].has_corrective_offset, "correction cleared")
    state.bones[3].has_corrective_offset = True
    state.bones[3].corrective_offset = extra
    bpy.ops.object.mode_set(mode='OBJECT')

    # JSON round trip onto a second character in the same scene
    path = os.path.join(scratch, "panel_setup.json")
    checks.check(bpy.ops.retargetor.export_setup_to_json(filepath=path) == {'FINISHED'}, "Export to JSON")
    second = bootstrap.make_armature("TGT2", bootstrap.TARGET_BONES, location=(-2.0, 0.0, 0.0))
    scene.retargetor_target = second
    second.retargetor.source = source
    checks.check(bpy.ops.retargetor.import_retarget_json(filepath=path) == {'FINISHED'}, "Import from JSON")
    first_rows = [(i.src_name, i.target_name, i.offset_mode, i.use_translation, i.has_corrective_offset,
                   tuple(round(v, 6) for v in i.corrective_offset)) for i in state.bones]
    second_rows = [(i.src_name, i.target_name, i.offset_mode, i.use_translation, i.has_corrective_offset,
                    tuple(round(v, 6) for v in i.corrective_offset)) for i in second.retargetor.bones]
    checks.check(first_rows == second_rows, "imported list equals the exported one")
    checks.close(second.retargetor.translation_scale, state.translation_scale, 1e-6, "scale recomputed on import")

    second.retargetor.bones[2].target_name = ""
    checks.check(state.bones[2].target_name == "arm.L", "two characters keep separate lists")
    view_layer.objects.active = second
    checks.check(bpy.ops.retargetor.simple_retarget() == {'FINISHED'}, "bake the second character")
    checks.check(target.animation_data is None or target.animation_data.action is None,
                 "the first character is not touched")

    # Selection handler: selecting a bone in Pose Mode selects its row
    bpy.ops.object.mode_set(mode='POSE')
    second.data.bones.active = second.data.bones["shin.L"]
    view_layer.update()
    checks.check(second.retargetor.bones_active_index == 5, "selecting a target bone selects its row")
    bpy.ops.object.mode_set(mode='OBJECT')

    # Rig profile panel on an armature with a profile
    view_layer.objects.active = target
    checks.check(bpy.ops.retargetor.profile_add_roles() == {'FINISHED'}, "Add Roles")
    profile = target.data.retargetor_profile
    checks.check(len(profile.roles) == 23, "every role added")
    profile.limbs.add().name = "arm.L"
    checks.check(draw_panels() == [], "panels draw with a rig profile")
    path = os.path.join(scratch, "panel_profile.json")
    profile.roles[0].read_bone = "hips"
    checks.check(bpy.ops.retargetor.profile_export_json(filepath=path) == {'FINISHED'}, "Export Profile")
    view_layer.objects.active = second
    checks.check(bpy.ops.retargetor.profile_import_json(filepath=path) == {'FINISHED'}, "Import Profile")
    checks.check(second.data.retargetor_profile.roles[0].read_bone == "hips", "profile imported on another armature")

    from retargetor.profile_operators import parse_frames
    checks.check(parse_frames("1, 61,120") == [1, 61, 120] and parse_frames("3-5, -1") == [-1, 3, 4, 5],
                 "frame lists parsed")
    checks.finish()


if __name__ == "__main__":
    main(bootstrap.script_args()[0])
