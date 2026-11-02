"""Build a motion model's armature from its neutral skeleton (core.skeleton.Skeleton)."""
import json

import bpy

from .skeleton import Skeleton

# Custom properties on the armature data: the skeleton it was built from, and which backend described it
SKELETON_PROPERTY = "retargetor_skeleton"
BACKEND_PROPERTY = "retargetor_backend"


def build_armature(context, skeleton, name, collection, backend_id=""):
    """A new armature object in `collection` (which must be in the view layer) with the skeleton's joints as
    bones (quaternion rotation mode). The skeleton is kept on the armature data, so it can be read back without
    asking the backend again. The active object and its mode are restored."""
    data = bpy.data.armatures.new(name)
    obj = bpy.data.objects.new(name, data)
    collection.objects.link(obj)

    # Edit mode can't be entered on the new armature while another object is in pose or edit mode:
    # the active object goes back to object mode meanwhile
    view_layer = context.view_layer
    previous_active = view_layer.objects.active
    previous_mode = previous_active.mode if previous_active is not None else 'OBJECT'
    if previous_mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    view_layer.objects.active = obj
    try:
        bpy.ops.object.mode_set(mode='EDIT')
        try:
            for joint in skeleton.joints:
                bone = data.edit_bones.new(joint.name)
                bone.head = joint.head
                bone.tail = joint.tail
                bone.roll = joint.roll
                if joint.parent is not None:
                    bone.parent = data.edit_bones[joint.parent]
                    bone.use_connect = False
        finally:
            bpy.ops.object.mode_set(mode='OBJECT')
    finally:
        view_layer.objects.active = previous_active
        if previous_mode != 'OBJECT':
            bpy.ops.object.mode_set(mode=previous_mode)

    for pose_bone in obj.pose.bones:
        pose_bone.rotation_mode = 'QUATERNION'
    data[SKELETON_PROPERTY] = json.dumps(skeleton.to_dict())
    data[BACKEND_PROPERTY] = backend_id
    return obj


def armature_skeleton(armature_obj):
    """The Skeleton an armature was built from, or None if it wasn't built by build_armature."""
    if armature_obj is None or armature_obj.type != 'ARMATURE':
        return None
    text = armature_obj.data.get(SKELETON_PROPERTY)
    if not text:
        return None
    try:
        return Skeleton.from_dict(json.loads(text))
    except (ValueError, KeyError):
        return None


def armature_backend(armature_obj):
    """Id of the backend whose skeleton the armature was built from ("" if unknown)."""
    if armature_obj is None or armature_obj.type != 'ARMATURE':
        return ""
    return armature_obj.data.get(BACKEND_PROPERTY, "")
