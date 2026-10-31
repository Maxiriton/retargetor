# type : ignore
"""Snapping and baking operators. The work is done by core.retarget.snap; these operators only read the
character edited in the panel (scene.retargetor_target and its object.retargetor state)."""
import bpy
from bpy.types import Operator
from bpy.props import BoolProperty, IntProperty

from .core.retarget.snap import Retargeter
from .properties import get_character


def character_retargeter(context):
    """Retargeter for the character edited in the panel. Raises ValueError if it isn't set up."""
    target_obj, state = get_character(context)
    if target_obj is None:
        raise ValueError("No target armature is set.")
    return Retargeter(state.source, target_obj, state.pairs(), state.translation_scale)


def report_snap_errors(operator, errors):
    if errors:
        operator.report({'WARNING'}, f"{len(errors)} error(s) while snapping, for example: {sorted(errors)[0]}")


def character_ready(context):
    target_obj, state = get_character(context)
    return target_obj is not None and state.source is not None and len(state.bones) > 0


def editing_target_in_pose_mode(context):
    target_obj, state = get_character(context)
    return target_obj is not None and state.source is not None and \
           context.mode == 'POSE' and context.active_object == target_obj


class RTGTR_SimpleRetarget(Operator):
    """Bake the source animation onto the target over the scene's frame range"""
    bl_idname = "retargetor.simple_retarget"
    bl_label = "Retarget"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return character_ready(context)

    def execute(self, context):
        scene = context.scene
        frames = range(scene.frame_start, scene.frame_end + 1)
        try:
            retargeter = character_retargeter(context)
            retargeter.bake(scene, context.view_layer, frames)
        except ValueError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        report_snap_errors(self, retargeter.errors)
        self.report({'INFO'}, f"Retargeting done on {len(frames)} frames.")
        return {'FINISHED'}


class RTGTR_snap_selected_bone(Operator):
    """Snap the current selected bone"""

    bl_idname = "retargetor.snap_selected_bone"
    bl_label = "Snap active bone"
    bl_options = {'REGISTER', 'UNDO'}

    add_roll : BoolProperty(
        name="Add roll rotation",
        default=True
    )

    @classmethod
    def poll(cls, context):
        return editing_target_in_pose_mode(context)

    def execute(self, context):
        tgt_bone = context.active_object.data.bones.active
        if tgt_bone is None:
            self.report({'ERROR'}, "No active bone.")
            return {'CANCELLED'}

        try:
            retargeter = character_retargeter(context)
            retargeter.snap_bone(tgt_bone.name, add_roll=self.add_roll)
            self.report({'INFO'}, "Snap done!")
            return {'FINISHED'}

        except (KeyError, ValueError) as e:
            self.report({'ERROR'}, str(e.args[0]) if isinstance(e, KeyError) else str(e))
            return {'CANCELLED'}


class RTGTR_snap_full_pose(Operator):
    """Snap the full pose at the current frame"""
    bl_idname = "retargetor.snap_full_pose"
    bl_label = "Snap full pose"
    bl_options = {'REGISTER', 'UNDO'}

    add_roll : BoolProperty(
        name="Add roll rotation",
        default=True
    )

    repetitions : IntProperty(
        name="Repetitions",
        default=5,
        min=1
    )

    @classmethod
    def poll(cls, context):
        return editing_target_in_pose_mode(context)

    def execute(self, context):
        try:
            retargeter = character_retargeter(context)
            retargeter.snap_pose(context.view_layer, add_roll=self.add_roll, repetitions=self.repetitions)
        except ValueError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        report_snap_errors(self, retargeter.errors)
        self.report({'INFO'}, f"Snapping done for the full pose in {self.repetitions} iterations.")
        return {'FINISHED'}


### Registration
classes = (
    RTGTR_SimpleRetarget,
    RTGTR_snap_selected_bone,
    RTGTR_snap_full_pose,
)

def register():
    for cl in classes:
        bpy.utils.register_class(cl)

def unregister():
    for cl in reversed(classes):
        bpy.utils.unregister_class(cl)
