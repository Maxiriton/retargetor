# type: ignore
"""Operators editing the rig profile of the active armature (armature.retargetor_profile), and the FK snap."""
import json
import os
import re

import bpy
from bpy.types import Operator
from bpy.props import BoolProperty, EnumProperty, StringProperty
from bpy_extras.io_utils import ExportHelper, ImportHelper

from .core import profile as core_profile
from .core import rig_detect
from .core.retarget.fk_snap import snap_fk_on_frames
from .core.roles import ROLES, get_role

PRESETS_DIR = os.path.join(os.path.dirname(__file__), "presets")
FRAME_RANGE = re.compile(r"^(-?\d+)(?:\s*-\s*(-?\d+))?$")
# The presets' names before they were named after the rig only, as files saved then still record them
RENAMED_PRESETS = {
    "Rigify human (FK controls)": "Rigify",
    "Auto-Rig Pro (FK controls)": "Auto-Rig Pro",
    "CloudRig (FK controls)": "CloudRig",
}


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


def fit_preset(armature, rig_profile):
    """The preset fitted to an armature: its optional roles whose bones are missing left out (a Rigify rig
    without toes). None if a bone of a required role or of a limb is missing."""
    roles = []
    for binding in rig_profile.roles:
        names = [name for name in (binding.read_bone, binding.write_bone) if name]
        if all(armature.bones.get(name) is not None for name in names):
            roles.append(binding)
        elif get_role(binding.role).required:
            return None
    fitted = core_profile.RigProfile(roles=roles, limbs=rig_profile.limbs)
    if missing_bones(armature, fitted):
        return None
    return fitted


def detect_preset(armature):
    """(display name, RigProfile) of the first preset matching the armature's bones (see fit_preset), or None"""
    for _key, (path, name) in preset_files().items():
        try:
            rig_profile = preset_profile(path)
        except (OSError, ValueError):
            continue
        if not rig_profile.roles:
            continue
        fitted = fit_preset(armature, rig_profile)
        if fitted is not None:
            return name, fitted
    return None


# Source of a profile found on a skeleton (RigProfile.source)
DETECTED_SOURCE = "Detected on the skeleton"

# {armature session uid: (bone names, Detection)}: detection is run once per armature (the panels ask on redraw)
_detection_cache = {}


def detect_skeleton(armature):
    """core.rig_detect's Detection on the armature's bones, cached while its bones don't change"""
    names = tuple(bone.name for bone in armature.bones)
    cached = _detection_cache.get(armature.session_uid)
    if cached is None or cached[0] != names:
        bones = [rig_detect.BoneInfo(b.name, b.parent.name if b.parent else None, tuple(b.head_local),
                                     tuple(b.tail_local)) for b in armature.bones]
        cached = (names, rig_detect.detect(bones))
        _detection_cache[armature.session_uid] = cached
    return cached[1]


def detect_profile(armature):
    """(source, RigProfile) for an armature without profile: a preset matching its bones, else the roles detected
    on its skeleton when they are all there (a Mixamo character...). None otherwise."""
    detected = detect_preset(armature)
    if detected is not None:
        return detected
    detection = detect_skeleton(armature)
    if detection.complete:
        return DETECTED_SOURCE, detection.profile()
    return None


def source_label(source):
    """Where a profile comes from, for the panels"""
    if source == DETECTED_SOURCE:
        return "detected on the skeleton"
    source = RENAMED_PRESETS.get(source, source)
    return f"preset '{source}'" if source else "set up by hand"


def describe_source(source):
    """'the preset X' or 'the bones detected on the skeleton', for messages"""
    if source == DETECTED_SOURCE:
        return "the bones detected on its skeleton"
    source = RENAMED_PRESETS.get(source, source)
    return f"the preset '{source}'" if source else "set up by hand"


def apply_detected_profile(armature):
    """If the armature's rig profile is empty and editable, fill it with detect_profile(). Returns the source
    ("" if nothing was applied)."""
    profile = armature.retargetor_profile
    if len(profile.roles) > 0 or not armature.is_editable:
        return ""
    detected = detect_profile(armature)
    if detected is None:
        return ""
    source, rig_profile = detected
    profile.from_core(rig_profile)
    profile.source = source
    return source


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


class RTGTR_OT_ProfileDetect(Operator):
    """Set the rig profile up from the armature's bones: the preset matching them (Rigify, Auto-Rig Pro, CloudRig),
    else the roles found on its skeleton from their names and hierarchy (Mixamo, Unreal, SMPL, VRM...)"""
    bl_idname = "retargetor.profile_detect"
    bl_label = "Detect Bones"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return profile_editable(context)

    def invoke(self, context, event):
        if len(active_armature(context).data.retargetor_profile.roles) > 0:
            return context.window_manager.invoke_confirm(
                self, event, title="Detect Bones", message="Replace the rig profile with the detected bones?",
                confirm_text="Replace")
        return self.execute(context)

    def execute(self, context):
        armature = active_armature(context).data
        preset = detect_preset(armature)
        profile = armature.retargetor_profile
        clear_check(armature)
        if preset is not None:
            profile.from_core(preset[1])
            profile.source = preset[0]
            self.report({'INFO'}, f"The preset '{preset[0]}' matches the bones: applied")
            return {'FINISHED'}
        detection = detect_skeleton(armature)
        if not detection.matches:
            self.report({'WARNING'}, "No humanoid bone recognized: assign the bones of each role by hand")
            return {'CANCELLED'}
        profile.from_core(detection.profile())
        profile.source = DETECTED_SOURCE
        if detection.missing:
            labels = ", ".join(get_role(r).label if r != "spine" else "a spine bone" for r in detection.missing[:4])
            more = f" and {len(detection.missing) - 4} more" if len(detection.missing) > 4 else ""
            self.report({'WARNING'}, f"{len(detection.matches)} roles found; missing: {labels}{more}")
        else:
            self.report({'INFO'}, f"{len(detection.matches)} roles found on the skeleton")
        return {'FINISHED'}


def _binding(profile, role_id, create=False):
    for item in profile.roles:
        if item.role == role_id:
            return item
    if not create:
        return None
    role = get_role(role_id)
    item = profile.roles.add()
    item.role = role.id
    item.offset_mode = role.default_offset_mode
    item.use_translation = role.default_use_translation
    # Keep the roles in the order of ROLES
    order = [r.id for r in ROLES]
    target = sum(1 for other in profile.roles if other.role in order and order.index(other.role) < order.index(role_id))
    profile.roles.move(len(profile.roles) - 1, target)
    return _binding(profile, role_id)


def active_bone_name(context):
    """The active bone of the active armature (pose or edit mode), or an empty string"""
    obj = active_armature(context)
    if obj is None:
        return ""
    bone = obj.data.bones.active
    return bone.name if bone is not None else ""


class RTGTR_OT_ProfileAssign(Operator):
    """Give a role the active bone: select the bone in the viewport, then click"""
    bl_idname = "retargetor.profile_assign"
    bl_label = "Assign Active Bone"
    bl_options = {'REGISTER', 'UNDO'}

    role: StringProperty(name="Role")
    which: EnumProperty(name="Which", items=[
        ('BOTH', "Bone", "The bone read and written"),
        ('READ', "Read", "The bone whose pose is read"),
        ('WRITE', "Control", "The control written"),
    ], default='BOTH')

    @classmethod
    def poll(cls, context):
        if not profile_editable(context):
            return False
        if not active_bone_name(context):
            cls.poll_message_set("Select a bone of the armature first (Pose Mode)")
            return False
        return True

    def execute(self, context):
        armature = active_armature(context).data
        try:
            get_role(self.role)
        except KeyError as e:
            self.report({'ERROR'}, str(e.args[0]))
            return {'CANCELLED'}
        name = active_bone_name(context)
        profile = armature.retargetor_profile
        item = _binding(profile, self.role, create=True)
        if self.which in ('BOTH', 'READ'):
            item.read_bone = name
        if self.which in ('BOTH', 'WRITE'):
            item.write_bone = name
        if self.which == 'BOTH' and profile.use_controls and len(profile.roles) == 1:
            profile.use_controls = False
        clear_check(armature)
        self.report({'INFO'}, f"{get_role(self.role).label}: '{name}'")
        return {'FINISHED'}


class RTGTR_OT_ProfileClearRole(Operator):
    """Take the role out of the rig profile: the motion won't be read or written there"""
    bl_idname = "retargetor.profile_clear_role"
    bl_label = "Clear Role"
    bl_options = {'REGISTER', 'UNDO'}

    role: StringProperty(name="Role")

    @classmethod
    def poll(cls, context):
        return profile_editable(context)

    def execute(self, context):
        armature = active_armature(context).data
        profile = armature.retargetor_profile
        for i, item in enumerate(profile.roles):
            if item.role == self.role:
                profile.roles.remove(i)
                clear_check(armature)
                return {'FINISHED'}
        return {'CANCELLED'}


class RTGTR_OT_ProfileSelectRole(Operator):
    """Select the role's bones in the viewport (Pose Mode), to see them"""
    bl_idname = "retargetor.profile_select_role"
    bl_label = "Select Bones"
    bl_options = {'REGISTER', 'UNDO'}

    role: StringProperty(name="Role")
    extend: BoolProperty(name="Extend", default=False, options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return active_armature(context) is not None

    def invoke(self, context, event):
        self.extend = event.shift
        return self.execute(context)

    def execute(self, context):
        obj = active_armature(context)
        item = _binding(obj.data.retargetor_profile, self.role)
        if item is None:
            return {'CANCELLED'}
        names = [name for name in dict.fromkeys((item.write_bone, item.read_bone)) if name]
        if context.mode != 'POSE':
            bpy.ops.object.mode_set(mode='POSE')
        if not self.extend:
            for pb in obj.pose.bones:
                pb.select = False
        for name in names:
            pb = obj.pose.bones.get(name)
            if pb is not None:
                pb.select = True
                obj.data.bones.active = pb.bone
        return {'FINISHED'}


# {armature session uid: (profile, problems)}: the last check of each armature, for the panel and Generate
_checks = {}


def clear_check(armature):
    _checks.pop(armature.session_uid, None)


def last_check(armature, rig_profile=None):
    """The problems of the last check of this armature, or None if it wasn't checked with this profile"""
    cached = _checks.get(armature.session_uid)
    if cached is None:
        return None
    if rig_profile is not None and cached[0] != rig_profile.to_dict():
        return None
    return cached[1]


def run_check(rig_obj, rig_profile, view_layer):
    """rig_check.check(), remembered for this armature and profile"""
    from . import rig_check
    problems = rig_check.check(rig_obj, rig_profile, view_layer)
    _checks[rig_obj.data.session_uid] = (rig_profile.to_dict(), problems)
    return problems


def checked(rig_obj, rig_profile, view_layer):
    """The problems of this profile on this rig: the last check's if it was made with it, else a new check"""
    problems = last_check(rig_obj.data, rig_profile)
    return problems if problems is not None else run_check(rig_obj, rig_profile, view_layer)


class RTGTR_OT_CheckRig(Operator):
    """Check the rig profile: the bones of each role, then what the controls do (each one turned, each IK limb
    snapped and switched). The pose is put back, nothing is keyed"""
    bl_idname = "retargetor.check_rig"
    bl_label = "Check Rig"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return active_armature(context) is not None

    def execute(self, context):
        obj = active_armature(context)
        try:
            rig_profile = obj.data.retargetor_profile.to_core()
        except ValueError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        if not rig_profile.roles:
            detected = detect_profile(obj.data)
            if detected is None:
                self.report({'ERROR'}, "No rig profile: detect the bones or assign them first")
                return {'CANCELLED'}
            rig_profile = detected[1]
        from . import rig_check
        problems = run_check(obj, rig_profile, context.view_layer)
        errors = sum(p.level == rig_check.ERROR for p in problems)
        if errors:
            self.report({'ERROR'}, f"{errors} problem(s) to fix: {problems[0].message}")
        elif problems:
            self.report({'WARNING'}, f"Ready, with {len(problems)} warning(s): {problems[0].message}")
        else:
            self.report({'INFO'}, "The rig is ready")
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
    RTGTR_OT_ProfileDetect,
    RTGTR_OT_ProfileAssign,
    RTGTR_OT_ProfileClearRole,
    RTGTR_OT_ProfileSelectRole,
    RTGTR_OT_CheckRig,
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
