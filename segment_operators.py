# type: ignore
"""Operators editing a character's prompt segments: add, remove, split, select (see segment_track)."""
import bpy
from bpy.props import IntProperty, StringProperty
from bpy.types import Operator

from . import segment_track
from .core import segments as core_segments
from .properties import get_character


def character_profile(rig):
    """The rig profile of a character (core), the detected preset if it is empty, or None"""
    from .profile_operators import detect_preset
    rig_profile = rig.data.retargetor_profile.to_core()
    if rig_profile.roles:
        return rig_profile
    detected = detect_preset(rig.data)
    return detected[1] if detected else None


def first_segment_range(context, rig):
    """(start, end) of the first segment of a character: the range of its generation without segments (the custom
    range, or its key poses), else NEW_SEGMENT_SECONDS from the current frame"""
    from . import generation
    state = rig.retargetor
    if state.range_mode == 'CUSTOM':
        return state.range_start, state.range_end
    rig_profile = character_profile(rig)
    if rig_profile is not None:
        try:
            start, end, _keys = generation.generation_range(rig, rig_profile)
            return start, end
        except ValueError:
            pass
    start = context.scene.frame_current
    return start, start + round(segment_track.NEW_SEGMENT_SECONDS * segment_track.scene_fps(context.scene)) - 1


def _editable_character(context):
    rig, state = get_character(context)
    if rig is None or not rig.is_editable:
        return None, None
    return rig, state


class RTGTR_OT_SegmentAdd(Operator):
    """Add a prompt segment at the end of the character's track. The first one takes the character's prompt, seed
    and range"""
    bl_idname = "retargetor.segment_add"
    bl_label = "Add Prompt Segment"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _editable_character(context)[0] is not None

    def execute(self, context):
        rig, state = _editable_character(context)
        track = segment_track.read_track(state)
        min_frames, max_frames = segment_track.length_limits(context)
        if not track:
            start, end = first_segment_range(context, rig)
            track = core_segments.append([], end - start + 1, state.prompt, state.seed, start_frame=start)
        else:
            length = round(segment_track.NEW_SEGMENT_SECONDS * segment_track.scene_fps(context.scene))
            if max_frames is not None:
                length = min(length, max_frames)
            track = core_segments.append(track, max(length, min_frames), "", track[-1].seed)
        segment_track.write_track(state, track, active=len(track) - 1)
        return {'FINISHED'}


class RTGTR_OT_SegmentRemove(Operator):
    """Remove a prompt segment: the one before takes its frames (the one after, for the first segment). Without
    segments, the character's prompt and range are used again"""
    bl_idname = "retargetor.segment_remove"
    bl_label = "Remove Prompt Segment"
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty(name="Segment", default=-1, description="Segment to remove (-1: the active one)",
                       options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        rig, state = _editable_character(context)
        return rig is not None and len(state.segments) > 0

    def execute(self, context):
        _rig, state = _editable_character(context)
        index = state.segments_active_index if self.index < 0 else self.index
        if not 0 <= index < len(state.segments):
            self.report({'ERROR'}, f"No segment {index + 1}")
            return {'CANCELLED'}
        track = core_segments.remove(segment_track.read_track(state), index)
        segment_track.write_track(state, track, active=max(0, index - 1))
        return {'FINISHED'}


class RTGTR_OT_SegmentSplit(Operator):
    """Cut a prompt segment in two at the current frame; both parts keep its prompt and seed"""
    bl_idname = "retargetor.segment_split"
    bl_label = "Split at Current Frame"
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty(name="Segment", default=-1, options={'SKIP_SAVE'},
                       description="Segment to cut (-1: the one under the current frame)")

    @classmethod
    def poll(cls, context):
        rig, state = _editable_character(context)
        return rig is not None and len(state.segments) > 0

    def execute(self, context):
        _rig, state = _editable_character(context)
        track = segment_track.read_track(state)
        frame = context.scene.frame_current
        index = core_segments.segment_at(track, frame) if self.index < 0 else self.index
        if index is None or not 0 <= index < len(track):
            self.report({'ERROR'}, f"No segment under frame {frame}")
            return {'CANCELLED'}
        min_frames, _max_frames = segment_track.length_limits(context)
        try:
            track = core_segments.split(track, index, frame, min_frames)
        except ValueError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        segment_track.write_track(state, track, active=index + 1)
        return {'FINISHED'}


class RTGTR_OT_SegmentSelect(Operator):
    """Make a prompt segment the active one; its character becomes the one edited in the panel"""
    bl_idname = "retargetor.segment_select"
    bl_label = "Select Prompt Segment"
    bl_options = {'REGISTER', 'UNDO'}

    character: StringProperty(name="Character", description="Character object (empty: the panel's character)",
                              options={'SKIP_SAVE'})
    index: IntProperty(name="Segment", default=0)

    def execute(self, context):
        if self.character:
            rig = bpy.data.objects.get(self.character)
            if rig is None or rig.type != 'ARMATURE':
                self.report({'ERROR'}, f"No character '{self.character}'")
                return {'CANCELLED'}
            if context.scene.retargetor_target != rig:
                context.scene.retargetor_target = rig
        rig, state = get_character(context)
        if rig is None or not 0 <= self.index < len(state.segments):
            return {'CANCELLED'}
        if state.segments_active_index != self.index:
            state.segments_active_index = self.index
        segment_track.tag_redraw()
        return {'FINISHED'}


class RTGTR_OT_SegmentStep(Operator):
    """Make the previous or the next prompt segment the active one"""
    bl_idname = "retargetor.segment_step"
    bl_label = "Previous / Next Segment"
    bl_options = {'REGISTER', 'UNDO'}

    step: IntProperty(name="Step", default=1)

    @classmethod
    def poll(cls, context):
        rig, state = get_character(context)
        return rig is not None and len(state.segments) > 1

    def execute(self, context):
        _rig, state = get_character(context)
        index = max(0, min(len(state.segments) - 1, state.segments_active_index + self.step))
        if index != state.segments_active_index:
            state.segments_active_index = index
        return {'FINISHED'}


classes = (
    RTGTR_OT_SegmentAdd,
    RTGTR_OT_SegmentRemove,
    RTGTR_OT_SegmentSplit,
    RTGTR_OT_SegmentSelect,
    RTGTR_OT_SegmentStep,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
