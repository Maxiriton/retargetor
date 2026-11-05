# type: ignore
"""Move setups saved by older versions in scene.retarget_* onto the target armature object.

Older versions stored one setup per scene. The properties are no longer registered, but their values are still
in the file, in the scene's system properties. On file load, each scene's setup is copied into
target_object.retargetor (unless that object already has a bone list), then removed from the scene.
"""
import bpy
from bpy.app.handlers import persistent

from .properties import suspended_target_update

LEGACY_PROPERTIES = (
    "retarget_bones",
    "retarget_bones_active_index",
    "retarget_is_recording",
    "retarget_current_initial_rotation",
    "last_active_bone_name",
    "retarget_source_armature",
    "retarget_target_armature",
    "retarget_translation_scale",
)
# EnumProperty values are stored as integers
LEGACY_OFFSET_MODES = {0: 'ROLL', 1: 'REST_OFFSET'}


def _legacy_properties(scene):
    props = scene.bl_system_properties_get()
    if props is None or "retarget_bones" not in props and "retarget_target_armature" not in props:
        return None
    return props


def _remove_legacy(props):
    for name in LEGACY_PROPERTIES:
        if name in props:
            del props[name]


def migrate_scene(scene):
    """Move the legacy setup of a scene onto its target object. Returns a message, or None if there was nothing to do.
    The legacy data is kept when it can't be moved (no target, linked target, target already set up)."""
    if scene.library is not None:
        return None
    props = _legacy_properties(scene)
    if props is None:
        return None

    rows = list(props.get("retarget_bones", []))
    target = props.get("retarget_target_armature")
    source = props.get("retarget_source_armature")

    if not rows:
        _remove_legacy(props)
        return f"Scene '{scene.name}': empty legacy setup removed."
    if not isinstance(target, bpy.types.Object) or target.type != 'ARMATURE':
        return f"Scene '{scene.name}': legacy setup kept, it has no target armature."
    if not target.is_editable:
        return f"Scene '{scene.name}': legacy setup kept, the target '{target.name}' is linked and can't be edited."
    state = target.retargetor
    if len(state.bones) > 0:
        return f"Scene '{scene.name}': legacy setup kept, '{target.name}' already has a bone list."

    with suspended_target_update():
        for row in rows:
            item = state.bones.add()
            item.src_name = row.get("src_name", "")
            item.target_name = row.get("target_name", "")
            item.use_translation = bool(row.get("use_translation", False))
            item.offset_mode = LEGACY_OFFSET_MODES.get(row.get("offset_mode", 0), 'ROLL')
            item.has_corrective_offset = bool(row.get("has_corrective_offset", False))
            corrective = row.get("corrective_offset")
            if corrective is not None and len(corrective) == 4:
                item.corrective_offset = tuple(corrective)

    if isinstance(source, bpy.types.Object) and source.type == 'ARMATURE':
        state.source = source
    state.bones_active_index = int(props.get("retarget_bones_active_index", 0))
    state.translation_scale = float(props.get("retarget_translation_scale", 1.0))
    if scene.retargetor_target is None:
        scene.retargetor_target = target

    _remove_legacy(props)
    return f"Scene '{scene.name}': setup of {len(rows)} bones moved to the object '{target.name}'."


def migrate_all():
    """Migrate every scene of the file. Returns the list of messages."""
    messages = []
    for scene in bpy.data.scenes:
        message = migrate_scene(scene)
        if message:
            messages.append(message)
    return messages


@persistent
def migrate_on_load(_filepath):
    for message in migrate_all():
        print(f"Retargetor: {message}")


def register():
    if migrate_on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(migrate_on_load)


def unregister():
    if migrate_on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(migrate_on_load)
