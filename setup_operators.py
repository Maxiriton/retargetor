# type: ignore
"""Operators and helpers used to set up the manual bone list between a source and a target armature.
The setup is stored on the target object (object.retargetor), see properties.py."""
import json

import bpy
from bpy.types import Operator
from bpy.props import StringProperty
from bpy_extras.io_utils import ExportHelper, ImportHelper
from mathutils import Quaternion

from .core.retarget.pairs import IDENTITY_QUATERNION, OFFSET_MODES
from .core.retarget.snap import compute_translation_scale
from .properties import get_character, suspended_target_update

INTERNAL_BONE_PREFIXES = ("mch-", "def-", "org-")


def update_translation_scale(target_obj, state):
    """Compute the translation scale from the bone list and store it on the character.
    Returns the result of compute_translation_scale: (scale, source height, target height) or None."""
    if state.source is None:
        return None
    result = compute_translation_scale(state.source, target_obj, state.pairs())
    if result is not None:
        state.translation_scale = result[0]
    return result


def find_bone_in_target(target_obj, source_bone_name, exclude=()):
    """Find the bone of the target armature that best matches a source bone name.
    An exact (case-insensitive) match wins, then a partial match. Bones listed in `exclude` are ignored."""
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


def character_has_source(context):
    target_obj, state = get_character(context)
    return target_obj is not None and state.source is not None


def character_editable(context):
    target_obj, _state = get_character(context)
    return target_obj is not None and target_obj.is_editable


class RTGTR_Setup_Bone_List(Operator):
    """List every source bone and guess its target bone from the names"""
    bl_idname = "retargetor.setup_bone_list"
    bl_label = "Setup Bone list"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return character_has_source(context) and character_editable(context)

    def execute(self, context):
        target_obj, state = get_character(context)
        state.bones.clear()
        state.bones_active_index = 0
        state.is_recording = False

        used_targets = set()

        with suspended_target_update():
            for bone in state.source.pose.bones:
                rtg_item = state.bones.add()
                rtg_item.src_name = bone.name

                # Try to find the matching bone in the target armature (names only).
                # A target bone is never used twice.
                target_name = find_bone_in_target(target_obj, bone.name, exclude=used_targets)
                rtg_item.target_name = target_name
                if target_name:
                    used_targets.add(target_name)

        update_translation_scale(target_obj, state)

        self.report({'INFO'}, f"Found {len(state.bones)} bones")
        return {'FINISHED'}


class RTGTR_OT_AutoTranslationScale(Operator):
    """Compute the translation scale from the height of the mapped bones of both armatures"""
    bl_idname = "retargetor.auto_translation_scale"
    bl_label = "Auto"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        target_obj, state = get_character(context)
        return target_obj is not None and state.source is not None and len(state.bones) > 0

    def execute(self, context):
        target_obj, state = get_character(context)
        result = update_translation_scale(target_obj, state)
        if result is None:
            self.report({'WARNING'}, "Unable to measure the heights: at least 2 mapped bones at different heights are needed.")
            return {'CANCELLED'}

        scale, source_height, target_height = result
        self.report({'INFO'}, f"Translation scale = {scale:.4f} (source height {source_height:.3f} m, target height {target_height:.3f} m)")
        return {'FINISHED'}


class RTGTR_Record_to_json(Operator, ExportHelper):
    """Export the bone list to JSON"""

    bl_idname = "retargetor.export_setup_to_json"
    bl_label = "Export to JSON"
    bl_options = {'REGISTER'}

    filename_ext = ".json"

    filter_glob: StringProperty(
        default="*.json",
        options={'HIDDEN'},
        maxlen=255,
    )

    @classmethod
    def poll(cls, context):
        target_obj, _state = get_character(context)
        return target_obj is not None

    def execute(self, context):
        _target_obj, state = get_character(context)

        # Rest offsets are no longer stored: they are computed from the two rigs when retargeting
        collection_data = []
        for item in state.bones:
            data = {
                "src_name": item.src_name,
                "target_name": item.target_name,
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
    """Import the bone list from a JSON file"""

    bl_idname = "retargetor.import_retarget_json"
    bl_label = "Import from JSON"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ".json"

    filter_glob: StringProperty(
        default="*.json",
        options={'HIDDEN'},
        maxlen=255,
    )

    @classmethod
    def poll(cls, context):
        return character_editable(context)

    def execute(self, context):
        target_obj, state = get_character(context)

        try:
            with open(self.filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            self.report({'ERROR'}, f"Unable to read the file: {str(e)}")
            return {'CANCELLED'}

        if not isinstance(data, list):
            self.report({'ERROR'}, "The JSON file has the wrong format (a list of items is expected)")
            return {'CANCELLED'}

        collection = state.bones
        collection.clear()
        state.bones_active_index = 0
        state.is_recording = False

        # The update callback is suspended: values come from the file, not from a user edit.
        # Rest offsets written by older versions are ignored: they are computed from the two rigs.
        with suspended_target_update():
            for item_data in data:
                new_item = collection.add()

                new_item.src_name = item_data.get("src_name", "")
                new_item.target_name = item_data.get("target_name", "")
                # Files exported by older versions don't contain it: no translation by default
                new_item.use_translation = item_data.get("use_translation", False)

                if item_data.get("offset_mode") in OFFSET_MODES:
                    new_item.offset_mode = item_data["offset_mode"]

                # Files exported by older versions don't contain the corrective offset
                corrective_offset = item_data.get("corrective_offset", list(IDENTITY_QUATERNION))
                if len(corrective_offset) == 4:
                    new_item.corrective_offset = corrective_offset
                new_item.has_corrective_offset = item_data.get("has_corrective_offset", False)

        # The scale isn't stored in the JSON: it comes from the two rigs
        if update_translation_scale(target_obj, state) is not None:
            self.report({'INFO'}, f"Import successful ({len(data)} bones, translation scale recomputed)")
        else:
            self.report({'INFO'}, f"Import successful ({len(data)} bones)")
        return {'FINISHED'}


def recording_ready(context):
    """The active row can be recorded: it has a target bone and the target armature is the active object"""
    target_obj, state = get_character(context)
    if target_obj is None or context.active_object != target_obj:
        return False
    item = state.active_item()
    return item is not None and bool(item.target_name)


class RTGTR_OT_RecordAdjustment(Operator):
    """Record an extra rotation offset for the current selected bone"""
    bl_idname = "retargetor.record_adjustment"
    bl_label = "Record Adjustment"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return recording_ready(context)

    def execute(self, context):
        armature_obj, state = get_character(context)
        item = state.active_item()

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

        state.recording_initial_rotation = pose_bone.rotation_quaternion
        state.is_recording = True

        self.report({'INFO'}, f"Ready to record pose for {data_bone.name}")
        return {'FINISHED'}


class RTGTR_OT_FinishRecord(Operator):
    """Store the corrective rotation for the current selected bone"""
    bl_idname = "retargetor.finish_record"
    bl_label = "Finish Recording"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        target_obj, state = get_character(context)
        return target_obj is not None and state.is_recording and context.active_object == target_obj

    def execute(self, context):
        armature_obj, state = get_character(context)
        item = state.active_item()
        if item is None:
            self.report({'ERROR'}, "No active bone in the list.")
            return {'CANCELLED'}

        pose_bone = armature_obj.pose.bones.get(item.target_name)
        if pose_bone is None:
            self.report({'ERROR'}, f"The target bone '{item.target_name}' was not found.")
            return {'CANCELLED'}

        initial = Quaternion(state.recording_initial_rotation)
        difference = initial.rotation_difference(pose_bone.rotation_quaternion)

        # The initial pose was snapped with the previous correction already applied:
        # the new correction is added on top of it instead of replacing it.
        previous = Quaternion(item.corrective_offset) if item.has_corrective_offset else Quaternion()
        item.corrective_offset = previous @ difference
        item.has_corrective_offset = True
        state.is_recording = False
        self.report({'INFO'}, f"Saved transforms for {pose_bone.name}")
        return {'FINISHED'}


class RTGTR_OT_ClearRecord(Operator):
    """Clear the corrective offset for the current selected bone"""
    bl_idname = "retargetor.clear_record"
    bl_label = "Clear Record"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return recording_ready(context)

    def execute(self, context):
        _target_obj, state = get_character(context)
        item = state.active_item()
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
    RTGTR_OT_RecordAdjustment,
    RTGTR_OT_FinishRecord,
    RTGTR_OT_ClearRecord
)

def register():
    for cl in classes:
        bpy.utils.register_class(cl)

def unregister():
    for cl in reversed(classes):
        bpy.utils.unregister_class(cl)
