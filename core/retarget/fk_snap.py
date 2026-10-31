"""Snap a rig's FK controls to the pose of the bones they follow, and switch its limbs to FK.

Used on limbs posed in IK: the generated motion is always written to the FK controls, so before the key poses
are read, the FK controls are snapped to the IK pose on the key frames (rotations only: FK controls keep their
own length) and the limbs are switched to FK. The user's IK keys are kept.

The limbs are described by core.profile.LimbSnap.
"""
from mathutils import Matrix


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


def _switch_is_animated(rig_obj, limb):
    anim = rig_obj.animation_data
    if anim is None or anim.action is None:
        return False
    from bpy_extras.anim_utils import action_get_channelbag_for_slot
    channelbag = action_get_channelbag_for_slot(anim.action, anim.action_slot)
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


def snap_fk_on_frames(rig_obj, limbs, scene, view_layer, frames, keytype='KEYFRAME'):
    """Snap the FK controls to the followed bones on each frame and key their rotation,
    then switch the limbs to FK. The current frame is restored at the end."""
    frames = sorted(set(int(f) for f in frames))
    original_frame = scene.frame_current
    try:
        for frame in frames:
            scene.frame_set(frame)
            snap_fk_pose(rig_obj, limbs, view_layer)
            for limb in limbs:
                for pair in limb.controls:
                    pb = rig_obj.pose.bones[pair.fk_control]
                    pb.keyframe_insert(_rotation_data_path(pb), frame=frame, keytype=keytype)
    finally:
        scene.frame_set(original_frame)
    set_limbs_fk(rig_obj, limbs, view_layer, frames=frames, keytype=keytype)
