# type: ignore
"""Generated keys edited by the animator become user keys, as soon as they are edited (DESIGN.md, "Key poses and
generated keys").

Blender has no "key edited" event, and keying over a GENERATED key keeps it GENERATED. So the add-on remembers the
GENERATED keys it wrote (frames and values, on the character: object.retargetor["generated_keys"]), and a
depsgraph handler compares them whenever a character's action changes. A GENERATED key whose value changed, or
which was moved to another frame, is retyped as a Keyframe, with the other channels of the same property on that
frame (the 4 values of a quaternion). Keys retyped that way go back to GENERATED if their values come back (a
transform cancelled with a right click). The same check runs before each generation.
"""
from contextlib import contextmanager

import bpy
import numpy as np
from bpy.app.handlers import persistent

GENERATED = 'GENERATED'
KEYFRAME = 'KEYFRAME'
RECORD = "generated_keys"
# Values closer than this to the recorded one are unchanged (F-curves store float32 values)
TOLERANCE = 1e-5
_GENERATED_VALUE = bpy.types.Keyframe.bl_rna.properties["type"].enum_items[GENERATED].value

# While above 0, the handler does nothing (the add-on is writing the keys itself)
_suspended = 0


@contextmanager
def suspended():
    """The handler leaves the keys alone meanwhile"""
    global _suspended
    _suspended += 1
    try:
        yield
    finally:
        _suspended -= 1


def _channelbag(obj):
    anim = obj.animation_data
    if anim is None or anim.action is None:
        return None
    from bpy_extras.anim_utils import action_get_channelbag_for_slot
    return action_get_channelbag_for_slot(anim.action, anim.action_slot)


def _points(fcurve):
    """(frames, values, types) of an F-curve's keys, as numpy arrays"""
    points = fcurve.keyframe_points
    count = len(points)
    co = np.empty(2 * count, dtype=np.float64)
    types = np.empty(count, dtype=np.int32)
    if count:
        points.foreach_get("co", co)
        points.foreach_get("type", types)
    return co[0::2], co[1::2], types


def record(rig):
    """Remember every GENERATED key of the rig's action (frames and values). Replaces the previous record: the keys
    still GENERATED were checked before the generation, so they are the generated values."""
    bag = _channelbag(rig)
    curves = []
    if bag is not None:
        for fcurve in bag.fcurves:
            frames, values, types = _points(fcurve)
            generated = types == _GENERATED_VALUE
            if generated.any():
                curves.append({"path": fcurve.data_path, "index": fcurve.array_index,
                               "frames": frames[generated].tolist(), "values": values[generated].tolist(),
                               "retyped": []})
    rig.retargetor[RECORD] = curves


def has_record(rig):
    return bool(rig.retargetor.get(RECORD))


def _point_at(fcurve, frame):
    for point in fcurve.keyframe_points:
        if abs(point.co.x - frame) < 1e-3:
            return point
    return None


def retype_edited(rig):
    """Retype the edited GENERATED keys of the rig as Keyframes, and the keys retyped that way whose values came
    back to GENERATED. Returns (keys retyped as Keyframes, keys back to GENERATED)."""
    entries = rig.retargetor.get(RECORD)
    bag = _channelbag(rig)
    if not entries or bag is None:
        return 0, 0

    # Frames are compared exactly (a key moved by 0.4 frame is edited), rounded to 1e-3 to be dictionary keys.
    # A key retyped here is remembered by its recorded frame (its "origin"), so moving it back is recognized.
    edited = {}         # (data path, frame of an edited GENERATED key): its origin
    unchanged = {}      # (data path, frame): every channel there has its recorded frame and value
    curves = {}         # data path: [(F-curve, record entry)]
    for entry in entries:
        path = entry["path"]
        fcurve = bag.fcurves.find(path, index=entry["index"])
        if fcurve is None:
            continue
        curves.setdefault(path, []).append((fcurve, entry))
        frames, values, types = _points(fcurve)
        recorded_frames = np.asarray(entry["frames"], dtype=np.float64)
        recorded_values = np.asarray(entry["values"], dtype=np.float64)
        if len(recorded_frames) and len(frames):
            nearest = np.clip(np.searchsorted(recorded_frames, frames - 1e-3), 0, len(recorded_frames) - 1)
            on_record = np.abs(recorded_frames[nearest] - frames) < 1e-3
            matches = on_record & (np.abs(recorded_values[nearest] - values) <= TOLERANCE)
            # Recorded frames left without a key: where moved keys come from
            keyed = np.zeros(len(recorded_frames), dtype=bool)
            keyed[nearest[on_record]] = True
            emptied = recorded_frames[~keyed]
        else:
            on_record = matches = np.zeros(len(frames), dtype=bool)
            emptied = recorded_frames
        generated = types == _GENERATED_VALUE
        for frame, is_generated, match, recorded in zip(frames.tolist(), generated.tolist(), matches.tolist(),
                                                        on_record.tolist()):
            key = (path, round(frame, 3))
            if is_generated and not match:
                origin = frame
                if not recorded and len(emptied):
                    origin = float(emptied[np.argmin(np.abs(emptied - frame))])
                edited.setdefault(key, round(float(origin), 3))
            unchanged[key] = unchanged.get(key, True) and match

    retyped = restored = 0
    for (path, frame), origin in edited.items():
        for fcurve, entry in curves[path]:
            point = _point_at(fcurve, frame)
            if point is not None and point.type == GENERATED:
                point.type = KEYFRAME
                retyped += 1
                if all(abs(f - origin) >= 1e-3 for f in entry["retyped"]):
                    entry["retyped"] = [float(f) for f in entry["retyped"]] + [origin]
    # Keys this module retyped, back on their recorded frames with their recorded values on every channel:
    # GENERATED again
    for path, pairs in curves.items():
        origins = {round(frame, 3) for _fcurve, entry in pairs for frame in entry["retyped"]}
        for origin in origins:
            if (path, origin) in edited or not unchanged.get((path, origin), False):
                continue
            # Every channel retyped from this frame must be back on it (a moved key may still be elsewhere)
            channels = [(fcurve, entry, _point_at(fcurve, origin)) for fcurve, entry in pairs
                        if any(abs(f - origin) < 1e-3 for f in entry["retyped"])]
            if any(point is None for _fcurve, _entry, point in channels):
                continue
            for _fcurve, entry, point in channels:
                if point.type == KEYFRAME:
                    point.type = GENERATED
                    restored += 1
                entry["retyped"] = [f for f in entry["retyped"] if abs(f - origin) >= 1e-3]
    return retyped, restored


@persistent
def retype_edited_handler(scene, depsgraph):
    """After an update of a character's action: its edited GENERATED keys become Keyframes"""
    from . import generation
    if _suspended or generation.current_task is not None:
        return
    actions = {update.id.original for update in depsgraph.updates if isinstance(update.id, bpy.types.Action)}
    if not actions:
        return
    for obj in scene.objects:
        if (obj.type == 'ARMATURE' and obj.animation_data is not None and obj.animation_data.action in actions
                and has_record(obj) and obj.is_editable):
            retype_edited(obj)


def register():
    if retype_edited_handler not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(retype_edited_handler)


def unregister():
    if retype_edited_handler in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(retype_edited_handler)
