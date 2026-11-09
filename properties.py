# type: ignore
"""Where the add-on stores its data (see DESIGN.md, "Where data is stored").

- Armature data: the rig profile (armature.retargetor_profile), shared by the objects using that armature.
- Object: the per-character state (object.retargetor): source armature, manual bone list, translation scale.
- Scene: only which character the panel is editing (scene.retargetor_target).

Every property can be edited in a library override (LIBRARY_OVERRIDABLE), and items can be added to the
collections of an override (USE_INSERTION).
"""
from contextlib import contextmanager

import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty, FloatProperty, FloatVectorProperty,
                       IntProperty, PointerProperty, StringProperty)
from bpy.types import PropertyGroup

from . import segment_track
from .core import profile as core_profile
from .core.retarget.pairs import BonePair, IDENTITY_QUATERNION
from .core.roles import ROLES_BY_ID

OVERRIDABLE = {'LIBRARY_OVERRIDABLE'}
OVERRIDABLE_COLLECTION = {'LIBRARY_OVERRIDABLE', 'USE_INSERTION'}

# Stored as integers in the files: never change the numbers
offset_items = [
    ('ROLL', "Roll", "Copy the direction of the source bone and correct the twist around the bone's axis "
                     "(right for limbs)", 0),
    ('REST_OFFSET', "Offset", "Apply the full rotation difference between the two rest poses", 1),
]


def is_armature(_self, obj):
    return obj.type == 'ARMATURE'


def is_scene_armature(scene, obj):
    """An armature linked to this scene (the scene's pointer keeps a deleted object alive, out of every scene)"""
    return obj.type == 'ARMATURE' and scene in obj.users_scene


# While True, the update callback of RTGTR_BonePairItem.target_name does nothing (list filled from code)
_target_update_suspended = False


@contextmanager
def suspended_target_update():
    """Temporarily disable the update callback of RTGTR_BonePairItem.target_name"""
    global _target_update_suspended
    previous = _target_update_suspended
    _target_update_suspended = True
    try:
        yield
    finally:
        _target_update_suspended = previous


# Stored as integers in the files: never change the numbers
range_items = [
    ('KEY_POSES', "Key Poses", "From the first key pose to the last one", 0),
    ('CUSTOM', "Custom", "From a start frame, for a given duration: with fewer key poses (or none: the prompt "
                         "alone), or to extend an animation. Key poses outside the range are ignored", 1),
]


def update_range_mode(self, context):
    """A custom range starts on the current frame"""
    if self.range_mode == 'CUSTOM' and context is not None and context.scene is not None:
        self.range_start = context.scene.frame_current


def update_target_bone(self, _context):
    """A different target bone makes any recorded correction meaningless"""
    if _target_update_suspended:
        return
    self.has_corrective_offset = False
    self.corrective_offset = IDENTITY_QUATERNION


### Per-character state (Object)

class RTGTR_BonePairItem(PropertyGroup):
    """One row of the manual bone list: a source bone copied onto a target bone"""
    src_name: StringProperty(name="Source Bone", override=OVERRIDABLE)
    target_name: StringProperty(name="Target Bone", update=update_target_bone, override=OVERRIDABLE)
    use_translation: BoolProperty(
        name="Use Translation",
        description="Copy the translation of the source bone onto the target bone (root motion). "
                    "Otherwise only the rotation is transferred",
        default=False, override=OVERRIDABLE)
    offset_mode: EnumProperty(items=offset_items, name="Offset Mode",
                              description="Select the offset to apply after aligning bones", override=OVERRIDABLE)
    has_corrective_offset: BoolProperty(
        name="Has Corrective Offset", description="A corrective offset has been recorded for this bone",
        default=False, override=OVERRIDABLE)
    corrective_offset: FloatVectorProperty(
        name="Corrective Offset", description="Additional rotation applied after aligning bones",
        size=4, default=IDENTITY_QUATERNION, override=OVERRIDABLE)

    def to_pair(self):
        correction = tuple(self.corrective_offset) if self.has_corrective_offset else None
        return BonePair(self.src_name, self.target_name, self.offset_mode, self.use_translation, correction)


class RTGTR_PromptSegment(PropertyGroup):
    """One prompt segment of a character's track (segment_track keeps the track contiguous)"""
    prompt: StringProperty(name="Prompt", description="Text describing the motion of this segment",
                           update=segment_track.update_redraw, override=OVERRIDABLE)
    seed: IntProperty(name="Seed", default=0, min=0, update=segment_track.update_redraw,
                      description="Same seed, same key poses and same prompt: same motion", override=OVERRIDABLE)
    frame_start: IntProperty(name="Start", description="First frame of the segment (the previous one ends before it)",
                             update=segment_track.update_start, override=OVERRIDABLE)
    frame_end: IntProperty(name="End", description="Last frame of the segment (the next one starts after it)",
                           update=segment_track.update_end, override=OVERRIDABLE)
    # segment_track.generated_signature() of the segment at its last generation ("" if never generated)
    generated: StringProperty(name="Generated", options={'HIDDEN'}, override=OVERRIDABLE)


class RTGTR_CharacterState(PropertyGroup):
    """Retargeting state of one character (the target armature object)"""
    source: PointerProperty(type=bpy.types.Object, name="Source Armature", poll=is_armature,
                            description="Armature whose animation is copied onto this one", override=OVERRIDABLE)
    bones: CollectionProperty(type=RTGTR_BonePairItem, name="Bone List", override=OVERRIDABLE_COLLECTION)
    bones_active_index: IntProperty(name="Active Bone", default=0, override=OVERRIDABLE)
    translation_scale: FloatProperty(
        name="Translation Scale",
        description="Scale applied to the movement of the bones flagged 'Use Translation' "
                    "(target size / source size). Not stored in the JSON",
        default=1.0, min=0.0001, soft_max=10.0, precision=4, override=OVERRIDABLE)
    is_recording: BoolProperty(name="Is Recording", default=False,
                               description="A corrective rotation is being recorded", override=OVERRIDABLE)
    recording_initial_rotation: FloatVectorProperty(
        name="Initial Rotation", description="Rotation of the bone when the recording started",
        size=4, default=IDENTITY_QUATERNION, override=OVERRIDABLE)
    # Generation with one prompt (no prompt segments)
    prompt: StringProperty(name="Prompt", description="Text describing the motion to generate",
                           override=OVERRIDABLE)
    seed: IntProperty(name="Seed", default=0, min=0,
                      description="Same seed, same key poses and same prompt: same motion", override=OVERRIDABLE)
    range_mode: EnumProperty(items=range_items, name="Range", default='KEY_POSES', update=update_range_mode,
                             description="Frames to generate", override=OVERRIDABLE)
    range_start: IntProperty(name="Start", default=1, description="First frame of the custom range",
                             override=OVERRIDABLE)
    range_duration: IntProperty(name="Duration", default=120, min=2,
                                description="Number of frames of the custom range", override=OVERRIDABLE)
    # Prompt segments: a track generated as a whole (none: the prompt, seed and range above)
    segments: CollectionProperty(type=RTGTR_PromptSegment, name="Prompt Segments",
                                 override=OVERRIDABLE_COLLECTION)
    segments_active_index: IntProperty(name="Active Segment", default=0, min=0,
                                       update=segment_track.update_redraw, override=OVERRIDABLE)
    model_armature: PointerProperty(type=bpy.types.Object, name="Model Armature", poll=is_armature,
                                    description="The motion model's skeleton, built by the add-on for this character",
                                    override=OVERRIDABLE)

    @property
    def range_end(self):
        """Last frame of the custom range"""
        return self.range_start + self.range_duration - 1

    def pairs(self):
        """The bone list as BonePairs (rows without a target bone are left out)"""
        return [item.to_pair() for item in self.bones if item.src_name and item.target_name]

    def active_item(self):
        """The active row, or None if the list is empty or the index is invalid"""
        if 0 <= self.bones_active_index < len(self.bones):
            return self.bones[self.bones_active_index]
        return None


### Rig profile (Armature data)

class RTGTR_Correction(PropertyGroup):
    backend: StringProperty(name="Backend", description="Id of the motion model backend", override=OVERRIDABLE)
    rotation: FloatVectorProperty(name="Rotation", size=4, default=IDENTITY_QUATERNION, override=OVERRIDABLE)


class RTGTR_RoleBinding(PropertyGroup):
    """The rig bones playing one humanoid role"""
    role: StringProperty(name="Role", description="Humanoid role id", override=OVERRIDABLE)
    read_bone: StringProperty(
        name="Read", description="Bone whose pose is read (for example the ORG bone of a Rigify rig)",
        override=OVERRIDABLE)
    write_bone: StringProperty(
        name="Write", description="Control that receives the motion (for example the FK control of a Rigify rig). "
                                  "Empty: this role is not written",
        override=OVERRIDABLE)
    offset_mode: EnumProperty(items=offset_items, name="Offset Mode", override=OVERRIDABLE)
    use_translation: BoolProperty(name="Use Translation", description="This role carries the root motion",
                                  override=OVERRIDABLE)
    corrections: CollectionProperty(type=RTGTR_Correction, override=OVERRIDABLE_COLLECTION)

    @property
    def label(self):
        role = ROLES_BY_ID.get(self.role)
        return role.label if role else self.role


class RTGTR_FkPair(PropertyGroup):
    fk_control: StringProperty(name="FK Control", override=OVERRIDABLE)
    followed_bone: StringProperty(name="Followed Bone", description="Bone whose orientation the FK control takes",
                                  override=OVERRIDABLE)


class RTGTR_BoneRef(PropertyGroup):
    bone: StringProperty(name="Bone", override=OVERRIDABLE)


ik_snap_mode_items = (
    (core_profile.IK_FOLLOW, "Follow", "Takes the followed bone's transform, with the offset of their rest poses"),
    (core_profile.IK_POLE, "Pole", "Pole target: placed in the plane of the followed bone and its parent, on the "
                                   "side the joint bends"),
    (core_profile.IK_REST, "Rest", "Reset to its rest pose"),
)


class RTGTR_IkSnap(PropertyGroup):
    ik_control: StringProperty(name="IK Control", override=OVERRIDABLE)
    followed_bone: StringProperty(name="Followed Bone", description="Bone the IK control is snapped to",
                                  override=OVERRIDABLE)
    mode: EnumProperty(name="Mode", items=ik_snap_mode_items, default=core_profile.IK_FOLLOW, override=OVERRIDABLE)


class RTGTR_LimbSnap(PropertyGroup):
    """How to snap one limb's FK controls to its IK pose and switch it to FK"""
    name: StringProperty(name="Limb", override=OVERRIDABLE)
    switch_bone: StringProperty(name="Switch Bone", description="Bone holding the IK/FK switch property",
                                override=OVERRIDABLE)
    switch_property: StringProperty(name="Switch Property", description="Custom property switching IK/FK",
                                    override=OVERRIDABLE)
    fk_value: FloatProperty(name="FK Value", description="Value of the switch property in FK", default=1.0,
                            override=OVERRIDABLE)
    controls: CollectionProperty(type=RTGTR_FkPair, override=OVERRIDABLE_COLLECTION)
    ik_controls: CollectionProperty(type=RTGTR_BoneRef, override=OVERRIDABLE_COLLECTION,
                                    description="Controls posing the limb in IK: their keys make key poses")
    ik_snap: CollectionProperty(type=RTGTR_IkSnap, override=OVERRIDABLE_COLLECTION,
                                description="How the IK controls are snapped to the generated FK motion, in order")


class RTGTR_RigProfile(PropertyGroup):
    """How this armature maps to the humanoid roles"""
    roles: CollectionProperty(type=RTGTR_RoleBinding, override=OVERRIDABLE_COLLECTION)
    roles_active_index: IntProperty(default=0, override=OVERRIDABLE)
    limbs: CollectionProperty(type=RTGTR_LimbSnap, override=OVERRIDABLE_COLLECTION)
    limbs_active_index: IntProperty(default=0, override=OVERRIDABLE)
    source: StringProperty(name="Preset", description="Preset the profile was loaded from (empty: set up by hand "
                                                      "or imported)", override=OVERRIDABLE)
    use_controls: BoolProperty(
        name="Separate Controls", default=True, override=OVERRIDABLE,
        description="The rig reads one bone per role and writes another, its control (Rigify, Auto-Rig Pro, "
                    "CloudRig...). Off: each role's bone is read and written (a skeleton: Mixamo, a mocap import...)")

    def to_core(self):
        """The profile as a core.profile.RigProfile. Raises ValueError on an invalid profile."""
        result = core_profile.RigProfile()
        for b in self.roles:
            write_bone = b.write_bone if self.use_controls else b.read_bone
            try:
                result.roles.append(core_profile.RoleBinding(
                    role=b.role, read_bone=b.read_bone, write_bone=write_bone, offset_mode=b.offset_mode,
                    use_translation=b.use_translation,
                    corrections={c.backend: tuple(c.rotation) for c in b.corrections},
                ))
            except KeyError as e:
                raise ValueError(str(e.args[0])) from e
        for limb in self.limbs:
            result.limbs.append(core_profile.LimbSnap(
                name=limb.name, switch_bone=limb.switch_bone, switch_property=limb.switch_property,
                fk_value=limb.fk_value,
                controls=[core_profile.FkPair(p.fk_control, p.followed_bone) for p in limb.controls],
                ik_controls=[ref.bone for ref in limb.ik_controls if ref.bone],
                ik_snap=[core_profile.IkSnap(s.ik_control, s.followed_bone, s.mode)
                         for s in limb.ik_snap if s.ik_control],
            ))
        return result

    def from_core(self, rig_profile):
        """Replace the whole profile with a core.profile.RigProfile"""
        self.roles.clear()
        self.limbs.clear()
        self.roles_active_index = 0
        self.limbs_active_index = 0
        self.use_controls = bool(rig_profile.limbs) or any(b.write_bone != b.read_bone for b in rig_profile.roles)
        for b in rig_profile.roles:
            item = self.roles.add()
            item.role = b.role
            item.read_bone = b.read_bone
            item.write_bone = b.write_bone
            item.offset_mode = b.offset_mode
            item.use_translation = b.use_translation
            for backend, q in b.corrections.items():
                correction = item.corrections.add()
                correction.backend = backend
                correction.rotation = q
        for limb in rig_profile.limbs:
            item = self.limbs.add()
            item.name = limb.name
            item.switch_bone = limb.switch_bone
            item.switch_property = limb.switch_property
            item.fk_value = limb.fk_value
            for pair in limb.controls:
                control = item.controls.add()
                control.fk_control = pair.fk_control
                control.followed_bone = pair.followed_bone
            for name in limb.ik_controls:
                item.ik_controls.add().bone = name
            for snap in limb.ik_snap:
                entry = item.ik_snap.add()
                entry.ik_control = snap.ik_control
                entry.followed_bone = snap.followed_bone
                entry.mode = snap.mode


classes = (
    RTGTR_BonePairItem,
    RTGTR_PromptSegment,
    RTGTR_CharacterState,
    RTGTR_Correction,
    RTGTR_RoleBinding,
    RTGTR_FkPair,
    RTGTR_BoneRef,
    RTGTR_IkSnap,
    RTGTR_LimbSnap,
    RTGTR_RigProfile,
)


def update_target(scene, _context):
    """A character whose rig profile is empty gets the preset matching its bones (Rigify...), or the roles found on
    its skeleton (Mixamo...)"""
    target = scene.retargetor_target
    if target is not None and target.type == 'ARMATURE':
        from .profile_operators import apply_detected_profile
        apply_detected_profile(target.data)


def get_character(context):
    """(target armature object, its RTGTR_CharacterState) for the character edited in the panel, or (None, None),
    also when the target isn't in the scene anymore (deleted: the pointer alone keeps it alive)"""
    target = context.scene.retargetor_target
    if target is None or not is_scene_armature(context.scene, target):
        return None, None
    return target, target.retargetor


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Armature.retargetor_profile = PointerProperty(type=RTGTR_RigProfile, override=OVERRIDABLE)
    bpy.types.Object.retargetor = PointerProperty(type=RTGTR_CharacterState, override=OVERRIDABLE)
    bpy.types.Scene.retargetor_target = PointerProperty(
        type=bpy.types.Object, name="Target Armature", poll=is_scene_armature, update=update_target,
        description="Character edited in the Retarget panel. Its setup is stored on the object itself. An empty "
                    "rig profile gets the preset matching the armature's bones, if there is one")


def unregister():
    del bpy.types.Scene.retargetor_target
    del bpy.types.Object.retargetor
    del bpy.types.Armature.retargetor_profile

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
