"""Read and write the neutral Pose / Motion types (core.motion) on an armature."""
import bpy
import numpy as np
from mathutils import Matrix, Quaternion, Vector

from .motion import Motion, Pose

# Value of the LINEAR item of Keyframe.interpolation, for foreach_set
_LINEAR = bpy.types.Keyframe.bl_rna.properties["interpolation"].enum_items["LINEAR"].value


def _world_rest(armature_obj, bone):
    return (armature_obj.matrix_world @ bone.matrix_local).to_3x3().normalized()


def read_pose(armature_obj, joints=None, root_joint=None):
    """The armature's current pose as a Pose: rotations from rest in world space, root head position.
    joints: names to read (all bones if None). Raises KeyError for an unknown joint."""
    pose_bones = armature_obj.pose.bones
    names = list(joints) if joints is not None else [pb.name for pb in pose_bones]
    rotations = {}
    for name in names:
        pb = pose_bones.get(name)
        if pb is None:
            raise KeyError(f"The joint '{name}' does not exist in the armature '{armature_obj.name}'.")
        posed = (armature_obj.matrix_world @ pb.matrix).to_3x3().normalized()
        q = (posed @ _world_rest(armature_obj, pb.bone).transposed()).to_quaternion()
        rotations[name] = tuple(q)

    root_position = None
    if root_joint is not None:
        pb = pose_bones.get(root_joint)
        if pb is None:
            raise KeyError(f"The root joint '{root_joint}' does not exist in the armature '{armature_obj.name}'.")
        root_position = tuple(armature_obj.matrix_world @ pb.head)
    return Pose(rotations, root_position)


def _depth(bone):
    depth = 0
    while bone.parent is not None:
        bone = bone.parent
        depth += 1
    return depth


def write_pose(armature_obj, pose, view_layer, root_joint=None):
    """Pose the armature so that read_pose gives `pose` back. Joints missing from the pose are left as they are.
    Bones are rotated in quaternion mode. Only root_joint is moved (to root_position); the others keep their
    head where their parent puts it. Raises KeyError for an unknown joint."""
    pose_bones = armature_obj.pose.bones
    world_inv = armature_obj.matrix_world.inverted()

    targets = []
    for name in pose.rotations:
        pb = pose_bones.get(name)
        if pb is None:
            raise KeyError(f"The joint '{name}' does not exist in the armature '{armature_obj.name}'.")
        targets.append(pb)
    # Parents first, one depth level at a time: a child's head depends on its parent's updated matrix
    targets.sort(key=lambda pb: _depth(pb.bone))

    previous_depth = None
    for pb in targets:
        depth = _depth(pb.bone)
        if previous_depth is not None and depth != previous_depth:
            view_layer.update()
        previous_depth = depth

        rotation = Quaternion(pose.rotations[pb.name]).to_matrix() @ _world_rest(armature_obj, pb.bone)
        if pb.name == root_joint and pose.root_position is not None:
            head = Vector(pose.root_position)
        else:
            head = armature_obj.matrix_world @ pb.head
        pb.rotation_mode = 'QUATERNION'
        pb.matrix = world_inv @ Matrix.LocRotScale(head, rotation.to_quaternion(), None)
        if pb.name != root_joint:
            pb.location = Vector((0.0, 0.0, 0.0))
    view_layer.update()


def write_motion(armature_obj, motion, scene, view_layer, root_joint=None, keytype='KEYFRAME'):
    """Key a Motion on the armature: rotations of every joint in the poses, location of root_joint.
    Frames are Blender frames (motion.start_frame onwards). The current frame is restored at the end."""
    original_frame = scene.frame_current
    previous = {}
    try:
        for frame in motion.frames:
            scene.frame_set(frame)
            pose = motion.pose_at(frame)
            write_pose(armature_obj, pose, view_layer, root_joint)
            for name in pose.rotations:
                pb = armature_obj.pose.bones[name]
                q = pb.rotation_quaternion.copy()
                if name in previous:
                    q.make_compatible(previous[name])
                pb.rotation_quaternion = q
                previous[name] = q
                pb.keyframe_insert("rotation_quaternion", frame=frame, keytype=keytype)
                if name == root_joint:
                    pb.keyframe_insert("location", frame=frame, keytype=keytype)
    finally:
        scene.frame_set(original_frame)


def _hierarchy_order(bones):
    """Bones parents first"""
    order = []
    stack = [bone for bone in bones if bone.parent is None][::-1]
    while stack:
        bone = stack.pop()
        order.append(bone)
        stack.extend(reversed(bone.children))
    return order


def _replace_fcurves(armature_obj, action_name):
    """The channelbag of the armature's action, emptied (a new action is created if it has none)"""
    from bpy_extras.anim_utils import action_ensure_channelbag_for_slot

    anim = armature_obj.animation_data_create()
    if anim.action is None:
        anim.action = bpy.data.actions.new(action_name)
    if anim.action_slot is None:
        anim.action_slot = anim.action.slots.new(id_type='OBJECT', name=armature_obj.name)
    channelbag = action_ensure_channelbag_for_slot(anim.action, anim.action_slot)
    channelbag.fcurves.clear()
    return channelbag


def _write_fcurve(fcurves, data_path, index, group, frames, values):
    fcurve = fcurves.new(data_path, index=index, group_name=group)
    points = fcurve.keyframe_points
    points.add(len(frames))
    co = np.empty(2 * len(frames))
    co[0::2] = frames
    co[1::2] = values
    points.foreach_set("co", co)
    points.foreach_set("handle_left", co)
    points.foreach_set("handle_right", co)
    points.foreach_set("interpolation", np.full(len(frames), _LINEAR, dtype=np.int32))
    fcurve.update()


def write_motion_fcurves(armature_obj, motion, root_joint=None, action_name=None):
    """Replace the armature's animation with a Motion, written straight into F-curves (linear keys on every
    frame). Much faster than write_motion: local rotations are computed from the rotations from rest, with no
    scene update. Every pose must list the same joints; bones missing from the poses keep their rest pose
    relative to their parent. root_joint (a bone without parent) also gets its location keyed.
    Raises KeyError for an unknown joint, ValueError for a root joint with a parent."""
    from . import quat

    poses = motion.poses
    if not poses:
        raise ValueError("The motion is empty.")
    joints = list(poses[0].rotations)
    bones = armature_obj.data.bones
    for name in joints:
        if bones.get(name) is None:
            raise KeyError(f"The joint '{name}' does not exist in the armature '{armature_obj.name}'.")
    rotations = np.array([[pose.rotations[name] for name in joints] for pose in poses], dtype=np.float64)
    given = {name: rotations[:, i] for i, name in enumerate(joints)}

    world_rotation = armature_obj.matrix_world.to_3x3().normalized().to_quaternion()
    frames = np.arange(motion.start_frame, motion.start_frame + len(poses), dtype=np.float64)
    identity = np.tile((1.0, 0.0, 0.0, 0.0), (len(poses), 1))

    channelbag = _replace_fcurves(armature_obj, action_name or f"{armature_obj.name}_motion")
    fcurves = channelbag.fcurves
    # Bones without F-curves keep their current values: put them all at rest first
    for pose_bone in armature_obj.pose.bones:
        pose_bone.matrix_basis = Matrix.Identity(4)
    from_rest = {}  # {bone name: (F, 4) rotation from rest, world space}
    for bone in _hierarchy_order(bones):
        parent = from_rest[bone.parent.name] if bone.parent is not None else identity
        own = given.get(bone.name)
        from_rest[bone.name] = parent if own is None else own
        if own is None:
            continue
        # basis = rest^-1 * parent^-1 * own * rest, with rest the bone's rest orientation in world space
        rest = np.array(world_rotation @ bone.matrix_local.to_quaternion())
        local = quat.multiply(quat.multiply(quat.conjugate(rest), quat.multiply(quat.conjugate(parent), own)), rest)
        if local[0, 0] < 0.0:
            local[0] *= -1.0
        local = quat.make_continuous(local)
        data_path = f'pose.bones["{bone.name}"].rotation_quaternion'
        for index in range(4):
            _write_fcurve(fcurves, data_path, index, bone.name, frames, local[:, index])
        armature_obj.pose.bones[bone.name].rotation_mode = 'QUATERNION'

    if root_joint is not None and poses[0].root_position is not None:
        bone = bones.get(root_joint)
        if bone is None:
            raise KeyError(f"The root joint '{root_joint}' does not exist in the armature '{armature_obj.name}'.")
        if bone.parent is not None:
            raise ValueError(f"The root joint '{root_joint}' must be a bone without parent.")
        positions = np.array([pose.root_position for pose in poses], dtype=np.float64)
        to_armature = np.array(armature_obj.matrix_world.inverted())
        positions = positions @ to_armature[:3, :3].T + to_armature[:3, 3]
        rest = np.array(bone.matrix_local.to_quaternion())
        location = quat.rotate(quat.conjugate(rest), positions - np.array(bone.head_local))
        data_path = f'pose.bones["{root_joint}"].location'
        for index in range(3):
            _write_fcurve(fcurves, data_path, index, root_joint, frames, location[:, index])


def read_motion(armature_obj, frames, scene, joints=None, root_joint=None, fps=None):
    """Read the armature's animation on consecutive frames as a Motion. The current frame is restored."""
    frames = list(frames)
    if not frames:
        raise ValueError("No frame to read.")
    if frames != list(range(frames[0], frames[0] + len(frames))):
        raise ValueError("A Motion is read on consecutive frames.")
    original_frame = scene.frame_current
    poses = []
    try:
        for frame in frames:
            scene.frame_set(frame)
            poses.append(read_pose(armature_obj, joints, root_joint))
    finally:
        scene.frame_set(original_frame)
    if fps is None:
        fps = scene.render.fps / scene.render.fps_base
    return Motion(fps=fps, start_frame=frames[0], poses=poses)
