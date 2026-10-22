# type : ignore
"""This module contains operator for kimodo retargeting"""
import bpy
from bpy.types import Operator
from bpy.props import BoolProperty, IntProperty
from mathutils import Matrix, Quaternion, Vector

def build_target_map(scene):
    """Return {target bone name: BoneRetargetInfo} for every bone that has a target.
    Raises ValueError if several source bones point to the same target bone."""
    mapping = {}
    duplicates = set()
    for item in scene.retarget_bones:
        if not item.target_name:
            continue
        if item.target_name in mapping:
            duplicates.add(item.target_name)
        mapping[item.target_name] = item

    if duplicates:
        raise ValueError(
            "Several source bones point to the same target bone: " + ", ".join(sorted(duplicates))
        )
    return mapping


def scaled_target_location(scene, item, src_pose_bone, tgt_pose_bone):
    """Position of the target bone head (in target armature space) for a bone flagged "Use Translation".

    The source's movement away from its rest position is scaled by scene.retarget_translation_scale
    and added to the target's own rest position:
        target = target rest + k * (source now - source rest)
    Everything is computed in world space, so object transforms and scales are taken into account.
    """
    source_obj = scene.retarget_source_armature
    target_obj = scene.retarget_target_armature

    src_rest_bone = source_obj.data.bones.get(item.src_name)
    tgt_rest_bone = target_obj.data.bones.get(tgt_pose_bone.name)
    if src_rest_bone is None or tgt_rest_bone is None:
        raise KeyError(f"Rest bone not found for the pair '{item.src_name}' / '{tgt_pose_bone.name}'.")

    src_rest_world = source_obj.matrix_world @ src_rest_bone.head_local
    src_now_world = source_obj.matrix_world @ src_pose_bone.head
    tgt_rest_world = target_obj.matrix_world @ tgt_rest_bone.head_local

    tgt_world = tgt_rest_world + scene.retarget_translation_scale * (src_now_world - src_rest_world)
    return target_obj.matrix_world.inverted() @ tgt_world


def snap_bone_rotation(context, bone_target_name, add_roll=True, add_corrective_offset=True, mapping=None):
    scene = context.scene
    target_obj = scene.retarget_target_armature
    source_obj = scene.retarget_source_armature

    if not target_obj or not source_obj:
        raise ValueError("The source or target armature is not set in the scene.")

    tgt_pose_bone = target_obj.pose.bones.get(bone_target_name)
    if tgt_pose_bone is None:
        raise KeyError(f"The target bone '{bone_target_name}' does not exist in the armature '{target_obj.name}'.")

    if mapping is None:
        mapping = build_target_map(scene)

    item = mapping.get(bone_target_name)
    if item is None:
        raise KeyError(f"No match found in 'retarget_bones' for the target bone '{bone_target_name}'.")

    src_pose_bone = source_obj.pose.bones.get(item.src_name)
    if src_pose_bone is None:
        raise KeyError(f"The source bone '{item.src_name}' does not exist in the source armature '{source_obj.name}'.")

    # Source pose expressed in the target armature space (object transforms included).
    # The scale is dropped: only the position and the orientation are copied.
    matrix = target_obj.matrix_world.inverted() @ source_obj.matrix_world @ src_pose_bone.matrix
    location, rotation, _scale = matrix.decompose()

    if item.use_translation:
        location = scaled_target_location(scene, item, src_pose_bone, tgt_pose_bone)

    tgt_pose_bone.rotation_mode = 'QUATERNION'
    tgt_pose_bone.matrix = Matrix.LocRotScale(location, rotation, None)

    q_rot = tgt_pose_bone.rotation_quaternion.copy()

    if add_roll:
        if item.offset_mode == 'ROLL':
            q_rot = q_rot @ Quaternion(Vector((0.0, 1.0, 0.0)), item.roll_offset)
        elif item.offset_mode == 'REST_OFFSET':
            q_rot = q_rot @ Quaternion(item.rest_offset)

    if add_corrective_offset and item.is_setup and item.has_corrective_offset:
        q_rot = q_rot @ Quaternion(item.corrective_offset)

    tgt_pose_bone.rotation_quaternion = q_rot

    # Only the bones flagged "Use Translation" in the bone list keep the copied translation
    if not item.use_translation:
        tgt_pose_bone.location = Vector((0.0, 0.0, 0.0))

    return True


def keep_quaternion_continuous(pose_bone, previous_rotations):
    """Make the bone's rotation_quaternion take the same hemisphere as the one keyed on the previous frame.
    q and -q are the same rotation, but interpolating between them makes the bone spin the long way round.
    Setting -q instead of q doesn't move the pose, it only changes the stored values."""
    q = pose_bone.rotation_quaternion.copy()
    previous = previous_rotations.get(pose_bone.name)
    if previous is None:
        # First frame: use a canonical sign (w >= 0) so the result doesn't depend on the matrix solver
        if q.w < 0.0:
            q.negate()
    else:
        q.make_compatible(previous)
    pose_bone.rotation_quaternion = q
    previous_rotations[pose_bone.name] = q


def snap_bone_hierarchy_recursive(context, bone, mapping, add_roll, errors):
    """Recursively snap the bone (if it is mapped) and then its children, parents first"""
    if bone.name in mapping:
        try:
            snap_bone_rotation(context, bone.name, add_roll=add_roll, mapping=mapping)
        except (KeyError, ValueError, AttributeError) as e:
            errors.add(str(e))

    for child in bone.children:
        snap_bone_hierarchy_recursive(context, child, mapping, add_roll, errors)


def snap_full_pose(context, add_roll=True, repetitions=5, mapping=None):
    """Snap every mapped bone of the target armature. Returns the set of error messages met on the way."""
    armature_obj = context.scene.retarget_target_armature

    if mapping is None:
        mapping = build_target_map(context.scene)

    root_bones = [b for b in armature_obj.data.bones if b.parent is None]
    if not root_bones:
        raise ValueError(f"The armature '{armature_obj.name}' contains no bones.")

    errors = set()
    for _iteration in range(repetitions):
        for root in root_bones:
            snap_bone_hierarchy_recursive(context, root, mapping, add_roll, errors)
        # A child reads its parent's matrix, which is only refreshed by an update
        context.view_layer.update()

    return errors


def report_snap_errors(operator, errors):
    if errors:
        operator.report({'WARNING'}, f"{len(errors)} error(s) while snapping, for example: {sorted(errors)[0]}")


class RTGTR_SimpleRetarget(Operator):
    bl_idname = "retargetor.simple_retarget"
    bl_label = "Retarget"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        scene = context.scene
        return scene.retarget_source_armature is not None and \
               scene.retarget_target_armature is not None and \
               len(scene.retarget_bones) > 0

    def execute(self, context):
        scene = context.scene
        target_obj = scene.retarget_target_armature

        try:
            mapping = build_target_map(scene)
        except ValueError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        # Only the mapped bones are keyed
        mapped_bones = [
            (target_obj.pose.bones[name], item.use_translation)
            for name, item in mapping.items() if name in target_obj.pose.bones
        ]

        start_frame = scene.frame_start
        end_frame = scene.frame_end
        original_frame = scene.frame_current
        errors = set()
        previous_rotations = {}  # {bone name: Quaternion keyed on the previous frame}

        try:
            for frame in range(start_frame, end_frame + 1):
                scene.frame_set(frame)
                errors |= snap_full_pose(context, add_roll=True, repetitions=5, mapping=mapping)

                for bone, use_translation in mapped_bones:
                    keep_quaternion_continuous(bone, previous_rotations)
                    if use_translation:
                        bone.keyframe_insert(data_path="location", frame=frame)
                    bone.keyframe_insert(data_path="rotation_quaternion", frame=frame)
        except ValueError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        finally:
            scene.frame_set(original_frame)

        report_snap_errors(self, errors)
        self.report({'INFO'}, f"Retargeting done on {end_frame - start_frame + 1} frames.")
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
        scene = context.scene
        return scene.retarget_source_armature is not None and \
               scene.retarget_target_armature is not None and \
               context.mode == 'POSE' and \
               context.active_object == scene.retarget_target_armature

    def execute(self, context):
        tgt_bone = context.active_object.data.bones.active
        if tgt_bone is None:
            self.report({'ERROR'}, "No active bone.")
            return {'CANCELLED'}

        try:
            snap_bone_rotation(context, tgt_bone.name, add_roll=self.add_roll)
            self.report({'INFO'}, "Snap done!")
            return {'FINISHED'}

        except (KeyError, ValueError, AttributeError) as e:
            self.report({'ERROR'}, str(e))
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
        scene = context.scene
        return scene.retarget_source_armature is not None and \
               scene.retarget_target_armature is not None and \
               context.mode == 'POSE' and \
               context.active_object == scene.retarget_target_armature

    def execute(self, context):
        try:
            errors = snap_full_pose(context, add_roll=self.add_roll, repetitions=self.repetitions)
        except ValueError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        report_snap_errors(self, errors)
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
