"""Read and write the neutral Pose / Motion types (core.motion) on an armature."""
from mathutils import Matrix, Quaternion, Vector

from .motion import Motion, Pose


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
