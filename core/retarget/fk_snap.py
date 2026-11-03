"""Snap a rig's FK controls to the pose of the bones they follow, and switch its limbs to FK; snap its IK
controls back to the FK pose.

Used on limbs posed in IK: the generated motion is always written to the FK controls, so before the key poses
are read, the FK controls are snapped to the IK pose on the key frames (rotations only: FK controls keep their
own length) and the limbs are switched to FK. The user's IK keys are kept. After the generation, the IK controls
are snapped to the generated FK pose on every frame, so the limbs play in IK again.

The limbs are described by core.profile.LimbSnap.
"""
from mathutils import Matrix

from ..profile import IK_FOLLOW, IK_POLE, IK_REST


def _rotation_data_path(pose_bone):
    if pose_bone.rotation_mode == 'QUATERNION':
        return "rotation_quaternion"
    if pose_bone.rotation_mode == 'AXIS_ANGLE':
        return "rotation_axis_angle"
    return "rotation_euler"


def _check_limb(rig_obj, limb):
    pose_bones = rig_obj.pose.bones
    for pair in limb.controls:
        for name in (pair.fk_control, pair.followed_bone):
            if pose_bones.get(name) is None:
                raise KeyError(f"The bone '{name}' of the limb '{limb.name}' does not exist in '{rig_obj.name}'.")
    if limb.switch_bone and pose_bones.get(limb.switch_bone) is None:
        raise KeyError(f"The switch bone '{limb.switch_bone}' of the limb '{limb.name}' does not exist in '{rig_obj.name}'.")


def snap_fk_pose(rig_obj, limbs, view_layer):
    """Rotate the FK controls of the limbs so they match the bones they follow, at the current frame.
    The followed orientations are all captured first, then the controls are set one by one, parents first."""
    for limb in limbs:
        _check_limb(rig_obj, limb)

    pose_bones = rig_obj.pose.bones
    controls = [pair for limb in limbs for pair in limb.controls]
    wanted = {pair.fk_control: pose_bones[pair.followed_bone].matrix.to_quaternion() for pair in controls}
    for pair in controls:
        pb = pose_bones[pair.fk_control]
        pb.matrix = Matrix.LocRotScale(pb.matrix.to_translation(), wanted[pair.fk_control], None)
        view_layer.update()


def _channelbag(rig_obj):
    """The F-curves of the rig's action, or None"""
    anim = rig_obj.animation_data
    if anim is None or anim.action is None:
        return None
    from bpy_extras.anim_utils import action_get_channelbag_for_slot
    return action_get_channelbag_for_slot(anim.action, anim.action_slot)


def _switch_is_animated(rig_obj, limb):
    channelbag = _channelbag(rig_obj)
    if channelbag is None:
        return False
    data_path = f'pose.bones["{limb.switch_bone}"]["{limb.switch_property}"]'
    return channelbag.fcurves.find(data_path) is not None


def set_limbs_fk(rig_obj, limbs, view_layer, frames=(), keytype='KEYFRAME'):
    """Set each limb's IK/FK switch to its FK value. If the switch is animated, it is also keyed on `frames`."""
    for limb in limbs:
        if not limb.switch_bone or not limb.switch_property:
            continue
        _check_limb(rig_obj, limb)
        switch = rig_obj.pose.bones[limb.switch_bone]
        if limb.switch_property not in switch:
            raise KeyError(f"The bone '{limb.switch_bone}' has no property '{limb.switch_property}'.")
        animated = _switch_is_animated(rig_obj, limb)
        switch[limb.switch_property] = limb.fk_value
        if animated:
            for frame in frames:
                switch.keyframe_insert(f'["{limb.switch_property}"]', frame=frame, keytype=keytype)
    # Setting a custom property doesn't tag the object: without this, the drivers reading the switch
    # (Rigify's constraint influences) keep their old value until something else updates the rig
    rig_obj.update_tag()
    view_layer.update()


def _set_key_type(rig_obj, data_path, frame, keytype):
    """Give the keys of a property on a frame the given type. keyframe_insert keeps the type of a key it
    replaces (a GENERATED key stays GENERATED)."""
    channelbag = _channelbag(rig_obj)
    if channelbag is None:
        return
    for fcurve in channelbag.fcurves:
        if fcurve.data_path != data_path:
            continue
        for point in fcurve.keyframe_points:
            if abs(point.co.x - frame) < 0.5:
                point.type = keytype


def snap_fk_keys(rig_obj, limbs_by_frame, scene, view_layer, keytype='KEYFRAME'):
    """On each frame of {frame: limbs}, snap the FK controls of the limbs to the bones they follow and key their
    rotation with the given type. A quaternion keeps the sign the curve had there, so it doesn't spin the long way
    from the keys around it. The current frame is restored at the end."""
    original_frame = scene.frame_current
    pose_bones = rig_obj.pose.bones
    try:
        for frame in sorted(limbs_by_frame):
            limbs = limbs_by_frame[frame]
            scene.frame_set(frame)
            before = {pair.fk_control: pose_bones[pair.fk_control].rotation_quaternion.copy()
                      for limb in limbs for pair in limb.controls if pose_bones.get(pair.fk_control) is not None}
            snap_fk_pose(rig_obj, limbs, view_layer)
            for limb in limbs:
                for pair in limb.controls:
                    pb = pose_bones[pair.fk_control]
                    if pb.rotation_mode == 'QUATERNION':
                        q = pb.rotation_quaternion.copy()
                        q.make_compatible(before[pair.fk_control])
                        pb.rotation_quaternion = q
                    data_path = _rotation_data_path(pb)
                    pb.keyframe_insert(data_path, frame=frame, keytype=keytype)
                    _set_key_type(rig_obj, pb.path_from_id(data_path), frame, keytype)
    finally:
        scene.frame_set(original_frame)


def _check_ik_snap(rig_obj, limb):
    pose_bones = rig_obj.pose.bones
    for snap in limb.ik_snap:
        names = [snap.ik_control] if snap.mode == IK_REST else [snap.ik_control, snap.followed_bone]
        for name in names:
            if not name or pose_bones.get(name) is None:
                raise KeyError(f"The bone '{name}' of the IK snap of the limb '{limb.name}' does not exist in "
                               f"'{rig_obj.name}'.")
        if snap.mode == IK_POLE and pose_bones[snap.followed_bone].parent is None:
            raise KeyError(f"The pole '{snap.ik_control}' of the limb '{limb.name}' follows "
                           f"'{snap.followed_bone}', which has no parent: a pole follows the lower bone of the chain "
                           "(Rigify: the forearm or the shin).")


def _ik_target(rig_obj, snap):
    """The pose matrix an IK control takes from the current pose of the bone it follows"""
    pose_bones = rig_obj.pose.bones
    control = pose_bones[snap.ik_control]
    followed = pose_bones[snap.followed_bone]
    if snap.mode == IK_FOLLOW:
        return followed.matrix @ followed.bone.matrix_local.inverted() @ control.bone.matrix_local
    # A pole: in the plane of the chain (the followed bone's parent, then the followed bone), on the side the joint
    # bends, at its rest distance from the joint. Only its position counts: it keeps its orientation.
    parent = followed.parent
    matrix = control.matrix.copy()
    root, joint, end = parent.head, followed.head, followed.tail
    bend = (joint - root) - (joint - root).project(end - root)
    if bend.length > 1e-4 * (end - root).length:
        distance = (control.bone.head_local - followed.bone.head_local).length
        matrix.translation = joint + bend.normalized() * distance
    else:  # a straight limb has no bend side: where the parent puts it at rest
        matrix.translation = (parent.matrix @ parent.bone.matrix_local.inverted() @ control.bone.matrix_local).translation
    return matrix


def ik_offsets(rig_obj, limbs):
    """{IK control: offset} of the limbs' FOLLOW controls at the current frame: how the control is posed (the
    user's IK pose, on a key pose) relative to the target the bone it follows gives it (the FK pose), as a matrix
    in the target's space, for snap_ik_pose's `corrections`. Rigify's IK chain is a little shorter than the FK one,
    so on a key pose the IK hand isn't quite where the snapped FK hand is: blending these offsets between the key
    poses keeps the IK motion from jumping there."""
    for limb in limbs:
        _check_ik_snap(rig_obj, limb)
    pose_bones = rig_obj.pose.bones
    return {snap.ik_control: _ik_target(rig_obj, snap).inverted() @ pose_bones[snap.ik_control].matrix
            for limb in limbs for snap in limb.ik_snap if snap.mode == IK_FOLLOW}


def _rotation_values(pose_bone):
    return tuple(getattr(pose_bone, _rotation_data_path(pose_bone)))


def _keep_locked(pose_bone, location, rotation):
    """Put back the locked channels of a pose bone, from its location and rotation (in its own mode) before"""
    for i, locked in enumerate(pose_bone.lock_location):
        if locked:
            pose_bone.location[i] = location[i]
    if not any(pose_bone.lock_rotation):
        return
    if pose_bone.rotation_mode == 'QUATERNION':
        q = pose_bone.rotation_quaternion.copy()
        for i, locked in enumerate(pose_bone.lock_rotation):
            if locked:
                q[i + 1] = rotation[i + 1]
        q.normalize()
        pose_bone.rotation_quaternion = q
    elif pose_bone.rotation_mode == 'AXIS_ANGLE':
        for i, locked in enumerate(pose_bone.lock_rotation):
            if locked:
                pose_bone.rotation_axis_angle[i + 1] = rotation[i + 1]
    else:
        for i, locked in enumerate(pose_bone.lock_rotation):
            if locked:
                pose_bone.rotation_euler[i] = rotation[i]


def snap_ik_pose(rig_obj, limbs, view_layer, corrections=None):
    """Snap the IK controls of the limbs (LimbSnap.ik_snap) to the current pose of the bones they follow, which
    play the FK pose (the limbs in FK). corrections: {IK control: matrix} applied in the target's space (see
    ik_offsets). The targets are all captured first, then the controls are set in the profile's order, the limbs
    side by side. Scales and locked channels are kept."""
    for limb in limbs:
        _check_ik_snap(rig_obj, limb)
    pose_bones = rig_obj.pose.bones
    corrections = corrections or {}
    wanted = {}
    for limb in limbs:
        for snap in limb.ik_snap:
            if snap.mode != IK_REST:
                wanted[snap.ik_control] = _ik_target(rig_obj, snap)
                if snap.ik_control in corrections:
                    wanted[snap.ik_control] = wanted[snap.ik_control] @ corrections[snap.ik_control]
    for step in range(max((len(limb.ik_snap) for limb in limbs), default=0)):
        for limb in limbs:
            if step >= len(limb.ik_snap):
                continue
            snap = limb.ik_snap[step]
            pb = pose_bones[snap.ik_control]
            location, rotation, scale = pb.location.copy(), _rotation_values(pb), pb.scale.copy()
            if snap.mode == IK_REST:
                pb.location = (0.0, 0.0, 0.0)
                if pb.rotation_mode == 'QUATERNION':
                    pb.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
                elif pb.rotation_mode == 'AXIS_ANGLE':
                    pb.rotation_axis_angle = (0.0, 0.0, 1.0, 0.0)
                else:
                    pb.rotation_euler = (0.0, 0.0, 0.0)
            else:
                pb.matrix = wanted[snap.ik_control]
                pb.scale = scale
            _keep_locked(pb, location, rotation)
        view_layer.update()


def _key_types(rig_obj, data_path, frame):
    """The types of the keys of a property on a frame"""
    channelbag = _channelbag(rig_obj)
    if channelbag is None:
        return set()
    return {point.type for fcurve in channelbag.fcurves if fcurve.data_path == data_path
            for point in fcurve.keyframe_points if abs(point.co.x - frame) < 0.5}


def key_ik_controls(rig_obj, limbs, frame, keytype, previous=None, user_keys=False, before=None):
    """Key the location and rotation (location only for a pole) of the limbs' IK snap controls on the frame, as
    they are posed. A quaternion takes the sign of `previous` ({control: quaternion}, updated), or else of `before`
    ({control: quaternion}, the curve there), so the curve doesn't spin the long way.
    user_keys: the keys are user keys of type `keytype`: a property that already has a user key on the frame is
    left as it is, a Generated key there gets the type (keyframe_insert keeps the type of a key it replaces)."""
    pose_bones = rig_obj.pose.bones
    for limb in limbs:
        for snap in limb.ik_snap:
            pb = pose_bones[snap.ik_control]
            paths = []
            if not all(pb.lock_location):
                paths.append("location")
            if snap.mode != IK_POLE and (not all(pb.lock_rotation)
                                         or pb.rotation_mode in ('QUATERNION', 'AXIS_ANGLE')):
                paths.append(_rotation_data_path(pb))
            if pb.rotation_mode == 'QUATERNION' and previous is not None:
                q = pb.rotation_quaternion.copy()
                reference = previous.get(snap.ik_control, (before or {}).get(snap.ik_control))
                if reference is not None:
                    q.make_compatible(reference)
                    pb.rotation_quaternion = q
                previous[snap.ik_control] = q
            for data_path in paths:
                full_path = pb.path_from_id(data_path)
                if user_keys and _key_types(rig_obj, full_path, frame) - {'GENERATED'}:
                    continue
                pb.keyframe_insert(data_path, frame=frame, keytype=keytype)
                if user_keys:
                    _set_key_type(rig_obj, full_path, frame, keytype)


def snap_ik_keys(rig_obj, limbs_by_frame, scene, view_layer, keytype, previous=None, corrections=None):
    """On each frame of {frame: limbs}, snap the IK controls of the limbs to the FK pose and key them. previous:
    {control: quaternion} keeping the signs continuous from one call to the next. corrections: {frame: {IK
    control: matrix}} (see snap_ik_pose). The current frame is restored at the end."""
    original_frame = scene.frame_current
    previous = {} if previous is None else previous
    pose_bones = rig_obj.pose.bones
    try:
        for frame in sorted(limbs_by_frame):
            limbs = limbs_by_frame[frame]
            scene.frame_set(frame)
            before = {snap.ik_control: pose_bones[snap.ik_control].rotation_quaternion.copy()
                      for limb in limbs for snap in limb.ik_snap}
            snap_ik_pose(rig_obj, limbs, view_layer, (corrections or {}).get(frame))
            key_ik_controls(rig_obj, limbs, frame, keytype, previous, before=before)
    finally:
        scene.frame_set(original_frame)


def snap_fk_on_frames(rig_obj, limbs, scene, view_layer, frames, keytype='KEYFRAME'):
    """Snap the FK controls to the followed bones on each frame and key their rotation,
    then switch the limbs to FK. The current frame is restored at the end."""
    frames = sorted(set(int(f) for f in frames))
    snap_fk_keys(rig_obj, {frame: limbs for frame in frames}, scene, view_layer, keytype)
    set_limbs_fk(rig_obj, limbs, view_layer, frames=frames, keytype=keytype)
