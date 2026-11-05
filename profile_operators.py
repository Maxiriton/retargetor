# type: ignore
"""Operators editing the rig profile of the active armature (armature.retargetor_profile), and the FK snap."""
import json
import os
import re

import bpy
from bpy.types import Operator
from bpy.props import EnumProperty, StringProperty
from bpy_extras.io_utils import ExportHelper, ImportHelper

from .core import profile as core_profile
from .core.retarget.fk_snap import snap_fk_on_frames
from .core.roles import ROLES

PRESETS_DIR = os.path.join(os.path.dirname(__file__), "presets")
FRAME_RANGE = re.compile(r"^(-?\d+)(?:\s*-\s*(-?\d+))?$")


def preset_files():
    """{preset id: (path, display name)} for the JSON files of the presets folder"""
    presets = {}
    if not os.path.isdir(PRESETS_DIR):
        return presets
    for filename in sorted(os.listdir(PRESETS_DIR)):
        if not filename.endswith(".json"):
            continue
        path = os.path.join(PRESETS_DIR, filename)
        try:
            with open(path, encoding="utf-8") as f:
                name = json.load(f).get("name", filename)
        except (OSError, ValueError):
            continue
        presets[filename[:-5]] = (path, name)
    return presets


def load_profile_file(path):
    """Read a rig profile JSON file. Raises ValueError with an explicit message."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        raise ValueError(f"Unable to read the file: {e}") from e
    return core_profile.RigProfile.from_dict(data)


# {preset path: (modification time, RigProfile)}: presets are read once (the panel looks for one on each redraw)
_preset_cache = {}


def preset_profile(path):
    """The RigProfile of a preset file, read once. Raises ValueError."""
    mtime = os.path.getmtime(path)
    cached = _preset_cache.get(path)
    if cached is None or cached[0] != mtime:
        cached = (mtime, load_profile_file(path))
        _preset_cache[path] = cached
    return cached[1]


def detect_preset(armature):
    """(display name, RigProfile) of the first preset whose bones all exist in the armature, or None"""
    for _key, (path, name) in preset_files().items():
        try:
            rig_profile = preset_profile(path)
        except (OSError, ValueError):
            continue
        if rig_profile.roles and not missing_bones(armature, rig_profile):
            return name, rig_profile
    return None


def apply_detected_preset(armature):
    """If the armature's rig profile is empty and editable, fill it with the preset matching its bones.
    Returns the preset's name, or "" if nothing was applied."""
    profile = armature.retargetor_profile
    if len(profile.roles) > 0 or not armature.is_editable:
        return ""
    detected = detect_preset(armature)
    if detected is None:
        return ""
    name, rig_profile = detected
    profile.from_core(rig_profile)
    profile.source = name
    return name


def missing_bones(armature, rig_profile):
    """Names used by the profile that don't exist in the armature"""
    used = set()
    for b in rig_profile.roles:
        used.update(name for name in (b.read_bone, b.write_bone) if name)
    for limb in rig_profile.limbs:
        used.update(name for pair in limb.controls for name in (pair.fk_control, pair.followed_bone))
        used.update(limb.ik_controls)
        used.update(name for snap in limb.ik_snap for name in (snap.ik_control, snap.followed_bone) if name)
        if limb.switch_bone:
            used.add(limb.switch_bone)
    return sorted(name for name in used if armature.bones.get(name) is None)


def apply_profile(operator, armature, rig_profile, source, preset_name=""):
    armature.retargetor_profile.from_core(rig_profile)
    armature.retargetor_profile.source = preset_name
    missing = missing_bones(armature, rig_profile)
    if missing:
        operator.report({'WARNING'}, f"Profile loaded from {source}, but {len(missing)} bone(s) are missing in "
                                     f"'{armature.name}', for example '{missing[0]}'")
    else:
        operator.report({'INFO'}, f"Profile loaded from {source}")


def active_armature(context):
    obj = context.active_object
    return obj if obj is not None and obj.type == 'ARMATURE' else None


def profile_editable(context):
    obj = active_armature(context)
    return obj is not None and obj.data.is_editable


class RTGTR_OT_ProfileAddRoles(Operator):
    """Add the humanoid roles missing from the rig profile, with their default settings"""
    bl_idname = "retargetor.profile_add_roles"
    bl_label = "Add Roles"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return profile_editable(context)

    def execute(self, context):
        profile = active_armature(context).data.retargetor_profile
        existing = {b.role for b in profile.roles}
        added = 0
        for role in ROLES:
            if role.id in existing:
                continue
            item = profile.roles.add()
            item.role = role.id
            item.offset_mode = role.default_offset_mode
            item.use_translation = role.default_use_translation
            added += 1
        self.report({'INFO'}, f"{added} role(s) added")
        return {'FINISHED'}


def preset_enum_items(_self, _context):
    return [(key, name, f"Load the {name} preset") for key, (_path, name) in preset_files().items()]


class RTGTR_OT_ProfileLoadPreset(Operator):
    """Replace the rig profile with a preset"""
    bl_idname = "retargetor.profile_load_preset"
    bl_label = "Load Preset"
    bl_options = {'REGISTER', 'UNDO'}
    bl_property = "preset"

    preset: EnumProperty(name="Preset", items=preset_enum_items)

    @classmethod
    def poll(cls, context):
        return profile_editable(context)

    def invoke(self, context, _event):
        context.window_manager.invoke_search_popup(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        presets = preset_files()
        if self.preset not in presets:
            self.report({'ERROR'}, f"Unknown preset '{self.preset}'")
            return {'CANCELLED'}
        path, name = presets[self.preset]
        try:
            rig_profile = load_profile_file(path)
        except ValueError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        apply_profile(self, active_armature(context).data, rig_profile, f"the preset '{name}'", name)
        return {'FINISHED'}


class RTGTR_OT_ProfileExport(Operator, ExportHelper):
    """Export the rig profile of the active armature to JSON"""
    bl_idname = "retargetor.profile_export_json"
    bl_label = "Export Profile"
    bl_options = {'REGISTER'}

    filename_ext = ".json"
    filter_glob: StringProperty(default="*.json", options={'HIDDEN'}, maxlen=255)

    @classmethod
    def poll(cls, context):
        return active_armature(context) is not None

    def execute(self, context):
        try:
            data = active_armature(context).data.retargetor_profile.to_core().to_dict()
            with open(self.filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)
        except (OSError, ValueError) as e:
            self.report({'ERROR'}, f"Export failed: {e}")
            return {'CANCELLED'}
        self.report({'INFO'}, f"Export successful: {self.filepath}")
        return {'FINISHED'}


class RTGTR_OT_ProfileImport(Operator, ImportHelper):
    """Replace the rig profile of the active armature with a JSON file"""
    bl_idname = "retargetor.profile_import_json"
    bl_label = "Import Profile"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ".json"
    filter_glob: StringProperty(default="*.json", options={'HIDDEN'}, maxlen=255)

    @classmethod
    def poll(cls, context):
        return profile_editable(context)

    def execute(self, context):
        try:
            rig_profile = load_profile_file(self.filepath)
        except ValueError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        apply_profile(self, active_armature(context).data, rig_profile, os.path.basename(self.filepath))
        return {'FINISHED'}


def parse_frames(text):
    """'1, 61, 120' or '1-5, 10' -> sorted list of frames. Raises ValueError."""
    frames = set()
    for part in text.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        match = FRAME_RANGE.match(part)
        if match is None:
            raise ValueError(f"'{part}' is not a frame number or a range like 10-20.")
        start, end = match.group(1), match.group(2) or match.group(1)
        frames.update(range(int(start), int(end) + 1))
    return sorted(frames)


class RTGTR_OT_SnapFkToIk(Operator):
    """Snap the FK controls of the profile's limbs to their current pose on the given frames, key them,
    then switch the limbs to FK. The IK keys are kept"""
    bl_idname = "retargetor.snap_fk_to_ik"
    bl_label = "Snap FK to IK"
    bl_options = {'REGISTER', 'UNDO'}

    frames: StringProperty(
        name="Frames",
        description="Frames to snap, for example '1, 61, 120' or '1-10'. Empty: the current frame")

    @classmethod
    def poll(cls, context):
        obj = active_armature(context)
        return obj is not None and obj.is_editable and len(obj.data.retargetor_profile.limbs) > 0

    def execute(self, context):
        obj = active_armature(context)
        try:
            frames = parse_frames(self.frames) or [context.scene.frame_current]
            limbs = obj.data.retargetor_profile.to_core().limbs
            snap_fk_on_frames(obj, limbs, context.scene, context.view_layer, frames)
        except (KeyError, ValueError) as e:
            self.report({'ERROR'}, str(e.args[0]) if isinstance(e, KeyError) else str(e))
            return {'CANCELLED'}
        self.report({'INFO'}, f"FK snapped on {len(frames)} frame(s), {len(limbs)} limb(s) switched to FK")
        return {'FINISHED'}


### Registration
classes = (
    RTGTR_OT_ProfileAddRoles,
    RTGTR_OT_ProfileLoadPreset,
    RTGTR_OT_ProfileExport,
    RTGTR_OT_ProfileImport,
    RTGTR_OT_SnapFkToIk,
)

def register():
    for cl in classes:
        bpy.utils.register_class(cl)

def unregister():
    for cl in reversed(classes):
        bpy.utils.unregister_class(cl)
