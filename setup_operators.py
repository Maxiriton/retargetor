# type: ignore
"""Operators and helpers used to set up the bone matching between source and target armatures"""
import json
import math
from contextlib import contextmanager

import bpy
from bpy.types import Operator
from bpy.props import StringProperty
from bpy_extras.io_utils import ExportHelper, ImportHelper
from mathutils import Vector, Quaternion

IDENTITY_QUATERNION = (1.0, 0.0, 0.0, 0.0)
VALID_OFFSET_MODES = {'ROLL', 'REST_OFFSET'}
INTERNAL_BONE_PREFIXES = ("mch-", "def-", "org-")

# While True, update_target_bone does nothing (used when the list is filled from code)
_target_update_suspended = False


@contextmanager
def suspended_target_update():
    """Temporarily disable the update callback of BoneRetargetInfo.target_name"""
    global _target_update_suspended
    previous = _target_update_suspended
    _target_update_suspended = True
    try:
        yield
    finally:
        _target_update_suspended = previous


def get_active_item(context):
    """Return the active BoneRetargetInfo, or None if the list is empty or the index is invalid"""
    scene = context.scene
    index = scene.retarget_bones_active_index
    if 0 <= index < len(scene.retarget_bones):
        return scene.retarget_bones[index]
    return None


def get_rest_rotations(context, bone_source_name, bone_target_name):
    """World-space rest orientations (scale ignored) of a source/target bone pair.
    Returns None if one of the armatures or bones can't be found."""
    scene = context.scene
    source_obj = scene.retarget_source_armature
    target_obj = scene.retarget_target_armature
    if not source_obj or not target_obj:
        return None

    src_bone = source_obj.data.bones.get(bone_source_name)
    tgt_bone = target_obj.data.bones.get(bone_target_name)
    if src_bone is None or tgt_bone is None:
        return None

    q_src = (source_obj.matrix_world @ src_bone.matrix_local).to_quaternion()
    q_tgt = (target_obj.matrix_world @ tgt_bone.matrix_local).to_quaternion()
    return q_src, q_tgt


def compute_item_offsets(context, item):
    """Compute roll_offset and rest_offset of an item from the rest poses of its two bones.
    Returns True if the offsets could be computed."""
    rotations = get_rest_rotations(context, item.src_name, item.target_name)
    if rotations is None:
        return False
    q_src, q_tgt = rotations

    # Roll: angle around the target's local Y axis, from the source's X axis expressed in the target's local space
    x_src_in_tgt_local = q_tgt.inverted() @ (q_src @ Vector((1.0, 0.0, 0.0)))
    item.roll_offset = math.atan2(x_src_in_tgt_local.z, x_src_in_tgt_local.x)

    # Rest offset: rotation difference between the two bones in their rest pose
    item.rest_offset = q_src.rotation_difference(q_tgt)
    item.is_setup = True
    return True


def compute_translation_scale(context):
    """Ratio target height / source height, measured on the mapped bone pairs only (rest pose, world space).
    The height is the Z extent of the bone heads of the pairs, so both rigs are measured on the same landmarks.
    Returns (scale, source_height, target_height), or None if it can't be measured."""
    scene = context.scene
    source_obj = scene.retarget_source_armature
    target_obj = scene.retarget_target_armature
    if not source_obj or not target_obj:
        return None

    src_z = []
    tgt_z = []
    for item in scene.retarget_bones:
        if not item.target_name:
            continue
        src_bone = source_obj.data.bones.get(item.src_name)
        tgt_bone = target_obj.data.bones.get(item.target_name)
        if src_bone is None or tgt_bone is None:
            continue
        src_z.append((source_obj.matrix_world @ src_bone.head_local).z)
        tgt_z.append((target_obj.matrix_world @ tgt_bone.head_local).z)

    if len(src_z) < 2:
        return None

    source_height = max(src_z) - min(src_z)
    target_height = max(tgt_z) - min(tgt_z)
    if source_height < 1e-6 or target_height < 1e-6:
        return None

    return target_height / source_height, source_height, target_height


def update_translation_scale(context):
    """Compute the translation scale and store it in the scene. Returns the result of compute_translation_scale."""
    result = compute_translation_scale(context)
    if result is not None:
        context.scene.retarget_translation_scale = result[0]
    return result


def update_target_bone(self, context):
    """Callback called when a user sets up a match for a source/target bone"""
    if _target_update_suspended:
        return

    # A different target makes any recorded correction meaningless
    self.has_corrective_offset = False
    self.corrective_offset = IDENTITY_QUATERNION

    if self.target_name and compute_item_offsets(context, self):
        print(f"New offset computed : {Quaternion(self.rest_offset).to_euler()} | New roll computed : {self.roll_offset}")
        return

    self.is_setup = False
    self.roll_offset = 0.0
    self.rest_offset = IDENTITY_QUATERNION


def find_bone_in_target(context, source_bone_name, exclude=()):
    """Find the bone of the target armature that best matches a source bone name.
    An exact (case-insensitive) match wins, then a partial match. Bones listed in `exclude` are ignored."""
    target_obj = context.scene.retarget_target_armature
    if not target_obj:
        return ""

    wanted = source_bone_name.lower()
    candidates = [bone.name for bone in target_obj.pose.bones if bone.name not in exclude]

    for name in candidates:
        if name.lower() == wanted:
            return name

    partial = [
        name for name in candidates
        if wanted in name.lower() or (len(name) >= 3 and name.lower() in wanted)
    ]
    if not partial:
        return ""

    # Prefer deform/control bones over internal ones (MCH-, DEF-, ORG-), then the shortest name
    partial.sort(key=lambda name: (name.lower().startswith(INTERNAL_BONE_PREFIXES), len(name)))
    return partial[0]


class RTGTR_Setup_Bone_List(Operator):
    bl_idname = "retargetor.setup_bone_list"
    bl_label = "Setup Bone list"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.scene.retarget_source_armature is not None and \
               context.scene.retarget_target_armature is not None

    def execute(self, context):
        scene = context.scene
        scene.retarget_bones.clear()
        scene.retarget_bones_active_index = 0
        scene.retarget_is_recording = False

        source_obj = scene.retarget_source_armature
        used_targets = set()

        with suspended_target_update():
            for bone in source_obj.pose.bones:
                rtg_item = scene.retarget_bones.add()
                rtg_item.src_name = bone.name

                # Try to find the matching bone in the target armature (names only).
                # A target bone is never used twice.
                target_name = find_bone_in_target(context, bone.name, exclude=used_targets)
                rtg_item.target_name = target_name
                if target_name:
                    used_targets.add(target_name)
                    compute_item_offsets(context, rtg_item)

        update_translation_scale(context)

        self.report({'INFO'}, f"Found {len(scene.retarget_bones)} bones")
        return {'FINISHED'}


class RTGTR_OT_AutoTranslationScale(Operator):
    """Compute the translation scale from the height of the mapped bones of both armatures"""
    bl_idname = "retargetor.auto_translation_scale"
    bl_label = "Auto"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        scene = context.scene
        return scene.retarget_source_armature is not None and \
               scene.retarget_target_armature is not None and \
               len(scene.retarget_bones) > 0

    def execute(self, context):
        result = update_translation_scale(context)
        if result is None:
            self.report({'WARNING'}, "Unable to measure the heights: at least 2 mapped bones at different heights are needed.")
            return {'CANCELLED'}

        scale, source_height, target_height = result
        self.report({'INFO'}, f"Translation scale = {scale:.4f} (source height {source_height:.3f} m, target height {target_height:.3f} m)")
        return {'FINISHED'}


class RTGTR_Record_to_json(Operator, ExportHelper):
    """Export retarget setup to json"""

    bl_idname = "retargetor.export_setup_to_json"
    bl_label = "Export to JSON"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ".json"

    filter_glob: StringProperty(
        default="*.json",
        options={'HIDDEN'},
        maxlen=255,
    )

    def execute(self, context):
        scene = context.scene

        collection_data = []
        for item in scene.retarget_bones:
            data = {
                "src_name": item.src_name,
                "target_name": item.target_name,
                "rest_offset": list(item.rest_offset),
                "roll_offset": item.roll_offset,
                "is_setup": item.is_setup,
                "use_translation": item.use_translation,
                "offset_mode": item.offset_mode,
                "has_corrective_offset": item.has_corrective_offset,
                "corrective_offset": list(item.corrective_offset),
            }
            collection_data.append(data)

        try:
            with open(self.filepath, 'w', encoding='utf-8') as f:
                json.dump(collection_data, f, indent=4)

            self.report({'INFO'}, f"Export successful: {self.filepath}")
            return {'FINISHED'}

        except Exception as e:
            self.report({'ERROR'}, f"Export failed: {str(e)}")
            return {'CANCELLED'}


class RTGTR_import_retarget_json(Operator, ImportHelper):
    """Import the retarget setup from a JSON file"""

    bl_idname = "retargetor.import_retarget_json"
    bl_label = "Import from JSON"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ".json"

    filter_glob: StringProperty(
        default="*.json",
        options={'HIDDEN'},
        maxlen=255,
    )

    def execute(self, context):
        scene = context.scene

        try:
            with open(self.filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            self.report({'ERROR'}, f"Unable to read the file: {str(e)}")
            return {'CANCELLED'}

        if not isinstance(data, list):
            self.report({'ERROR'}, "The JSON file has the wrong format (a list of items is expected)")
            return {'CANCELLED'}

        collection = scene.retarget_bones
        collection.clear()
        scene.retarget_bones_active_index = 0
        scene.retarget_is_recording = False

        # The update callback is suspended: values come from the file, not from a user edit
        with suspended_target_update():
            for item_data in data:
                new_item = collection.add()

                new_item.src_name = item_data.get("src_name", "")
                new_item.target_name = item_data.get("target_name", "")

                rest_offset = item_data.get("rest_offset", list(IDENTITY_QUATERNION))
                if len(rest_offset) == 4:
                    new_item.rest_offset = rest_offset

                new_item.roll_offset = item_data.get("roll_offset", 0.0)
                new_item.is_setup = item_data.get("is_setup", False)
                # Files exported by older versions don't contain it: no translation by default
                new_item.use_translation = item_data.get("use_translation", False)

                if item_data.get("offset_mode") in VALID_OFFSET_MODES:
                    new_item.offset_mode = item_data["offset_mode"]

                # Files exported by older versions don't contain the corrective offset
                corrective_offset = item_data.get("corrective_offset", list(IDENTITY_QUATERNION))
                if len(corrective_offset) == 4:
                    new_item.corrective_offset = corrective_offset
                new_item.has_corrective_offset = item_data.get("has_corrective_offset", False)

        # Offsets only depend on the two rigs: when both armatures are set, recompute them
        # so they are always consistent with the current scene.
        armatures_ready = scene.retarget_source_armature is not None and \
                          scene.retarget_target_armature is not None
        recomputed = 0
        if armatures_ready:
            for item in collection:
                if item.target_name and compute_item_offsets(context, item):
                    recomputed += 1
                else:
                    item.is_setup = False

        if armatures_ready:
            # The scale isn't stored in the JSON: it comes from the two rigs of the current scene
            update_translation_scale(context)
            self.report({'INFO'}, f"Import successful ({len(data)} bones, offsets recomputed for {recomputed})")
        else:
            self.report({'INFO'}, f"Import successful ({len(data)} bones). Armatures not set: offsets from the file were kept")
        return {'FINISHED'}


class RTGTR_OT_RecordAdjustement(Operator):
    """Record an extra rotation offset for the current selected bone"""
    bl_idname = "retargetor.record_adjustement"
    bl_label = "Record Adjustment"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        item = get_active_item(context)
        return item is not None and item.is_setup and \
               context.active_object == context.scene.retarget_target_armature

    def execute(self, context):
        scene = context.scene
        item = get_active_item(context)
        armature_obj = context.active_object

        bpy.ops.object.mode_set(mode='POSE')
        data_bone = armature_obj.data.bones.get(item.target_name)
        pose_bone = armature_obj.pose.bones.get(item.target_name)
        if data_bone is None or pose_bone is None:
            self.report({'ERROR'}, f"The target bone '{item.target_name}' was not found.")
            return {'CANCELLED'}

        armature_obj.data.bones.active = data_bone
        bpy.ops.pose.select_all(action='DESELECT')
        pose_bone.select = True
        pose_bone.rotation_mode = 'QUATERNION'

        scene.retarget_current_initial_rotation = pose_bone.rotation_quaternion
        scene.retarget_is_recording = True

        self.report({'INFO'}, f"Ready to record pose for {data_bone.name}")
        return {'FINISHED'}


class RTGTR_OT_FinishRecord(Operator):
    """Store the corrective rotation for the current selected bone"""
    bl_idname = "retargetor.finish_record"
    bl_label = "Finish Recording"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.scene.retarget_is_recording and \
               context.active_object == context.scene.retarget_target_armature

    def execute(self, context):
        scene = context.scene
        armature_obj = scene.retarget_target_armature
        item = get_active_item(context)
        if item is None:
            self.report({'ERROR'}, "No active bone in the list.")
            return {'CANCELLED'}

        pose_bone = armature_obj.pose.bones.get(item.target_name)
        if pose_bone is None:
            self.report({'ERROR'}, f"The target bone '{item.target_name}' was not found.")
            return {'CANCELLED'}

        initial = Quaternion(scene.retarget_current_initial_rotation)
        difference = initial.rotation_difference(pose_bone.rotation_quaternion)

        # The initial pose was snapped with the previous correction already applied:
        # the new correction is added on top of it instead of replacing it.
        previous = Quaternion(item.corrective_offset) if item.has_corrective_offset else Quaternion()
        item.corrective_offset = previous @ difference
        item.has_corrective_offset = True
        scene.retarget_is_recording = False
        self.report({'INFO'}, f"Saved transforms for {pose_bone.name}")
        return {'FINISHED'}


class RTGTR_OT_ClearRecord(Operator):
    """Clear the corrective offset for the current selected bone"""
    bl_idname = "retargetor.clear_record"
    bl_label = "Clear Record"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        item = get_active_item(context)
        return item is not None and item.is_setup and \
               context.active_object == context.scene.retarget_target_armature

    def execute(self, context):
        item = get_active_item(context)
        item.corrective_offset = IDENTITY_QUATERNION
        item.has_corrective_offset = False
        self.report({'INFO'}, f"Cleared corrective offset for {item.target_name}")
        return {'FINISHED'}


### Registration
classes = (
    RTGTR_Setup_Bone_List,
    RTGTR_OT_AutoTranslationScale,
    RTGTR_Record_to_json,
    RTGTR_import_retarget_json,
    RTGTR_OT_RecordAdjustement,
    RTGTR_OT_FinishRecord,
    RTGTR_OT_ClearRecord
)

def register():
    for cl in classes:
        bpy.utils.register_class(cl)

def unregister():
    for cl in reversed(classes):
        bpy.utils.unregister_class(cl)
