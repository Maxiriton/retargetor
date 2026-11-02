# type: ignore
"""Generating a character's in-betweens with a backend (see DESIGN.md, "Key poses and generated keys").

GenerationTask runs it step by step, so the operator can follow it from a timer without freezing Blender:
key poses on the rig -> the model's armature (its skeleton is asked to the backend once) -> the model snapped
to each key pose -> request to the worker -> the motion on the model's armature -> GENERATED keys on the rig.
"""
import re
import time

import bpy
import numpy as np
from mathutils import Matrix

from .backends import process, protocol, registry
from .core import profile as core_profile
from .core.motion import GenerationRequest
from .core.pose_io import read_pose, write_motion_fcurves
from .core.retarget.snap import Retargeter, compute_translation_scale
from .core.skeleton import Skeleton
from .core.skeleton_io import armature_backend, armature_skeleton, build_armature
from .preferences import active_backend, backend_settings

GENERATED = 'GENERATED'
# Value of the GENERATED item of Keyframe.type, for foreach_get
_GENERATED_VALUE = bpy.types.Keyframe.bl_rna.properties["type"].enum_items[GENERATED].value
MODELS_COLLECTION = "Retargetor Models"
_BONE_PATH = re.compile(r'^pose\.bones\["((?:[^"\\]|\\.)*)"\]')


### Keys

def channelbag(obj):
    """The F-curves of the object's action (Blender 5 layered actions), or None"""
    anim = obj.animation_data
    if anim is None or anim.action is None:
        return None
    from bpy_extras.anim_utils import action_get_channelbag_for_slot
    return action_get_channelbag_for_slot(anim.action, anim.action_slot)


def _bone_name(data_path):
    match = _BONE_PATH.match(data_path)
    if match is None:
        return None
    return match.group(1).replace('\\"', '"').replace('\\\\', '\\')


def bone_fcurves(rig, bones=None):
    """F-curves animating the given pose bones (all F-curves if bones is None)"""
    bag = channelbag(rig)
    if bag is None:
        return []
    if bones is None:
        return list(bag.fcurves)
    names = set(bones)
    return [fc for fc in bag.fcurves if _bone_name(fc.data_path) in names]


def user_key_frames(rig, bones=None):
    """Sorted frames where the given bones (any F-curve if None) have a user key: any type but GENERATED"""
    frames = set()
    for fcurve in bone_fcurves(rig, bones):
        points = fcurve.keyframe_points
        count = len(points)
        if count == 0:
            continue
        co = np.empty(2 * count, dtype=np.float32)
        types = np.empty(count, dtype=np.int32)
        points.foreach_get("co", co)
        points.foreach_get("type", types)
        frames.update(np.round(co[0::2][types != _GENERATED_VALUE]).astype(int).tolist())
    return sorted(frames)


def check_limbs_fk(rig, rig_profile, start, end):
    """Raises ValueError if a limb of the profile is in IK somewhere between start and end"""
    bag = channelbag(rig)
    in_ik = []
    for limb in rig_profile.limbs:
        if not limb.switch_bone or not limb.switch_property:
            continue
        switch = rig.pose.bones.get(limb.switch_bone)
        if switch is None or limb.switch_property not in switch:
            continue
        data_path = f'pose.bones["{bpy.utils.escape_identifier(limb.switch_bone)}"]' \
                    f'["{bpy.utils.escape_identifier(limb.switch_property)}"]'
        fcurve = bag.fcurves.find(data_path) if bag is not None else None
        if fcurve is not None:
            values = [fcurve.evaluate(frame) for frame in range(start, end + 1)]
        else:
            values = [float(switch[limb.switch_property])]
        if any(abs(value - limb.fk_value) > 1e-3 for value in values):
            in_ik.append(limb.name)
    if in_ik:
        raise ValueError(f"Limbs in IK on frames {start}-{end}: {', '.join(in_ik)}. The motion is written to the "
                         "FK controls: snap them to the IK pose first (Rig Profile panel, Snap FK to IK).")


def find_key_frames(rig, rig_profile):
    """The key poses: frames where a write control of the profile has a user key (sorted, maybe empty).
    Raises ValueError if the profile has no control to write."""
    controls = [b.write_bone for b in rig_profile.roles if b.write_bone]
    if not controls:
        raise ValueError(f"The rig profile of '{rig.name}' has no control to write: load a preset or map the roles.")
    return user_key_frames(rig, controls)


def generation_range(rig, rig_profile):
    """(start frame, end frame, key frames between them) of the character's next generation: from the first to
    the last key pose, or its custom range (key poses outside it are ignored).
    Raises ValueError if the key poses don't make a range."""
    key_frames = find_key_frames(rig, rig_profile)
    state = rig.retargetor
    if state.range_mode == 'CUSTOM':
        start, end = state.range_start, state.range_end
    else:
        if len(key_frames) < 2:
            found = "No key pose" if not key_frames else f"One key pose (frame {key_frames[0]})"
            raise ValueError(f"{found}: the range goes from the first key pose to the last one. Use a custom "
                             "range, or key more poses on the controls of the rig profile.")
        start, end = key_frames[0], key_frames[-1]
    return start, end, [frame for frame in key_frames if start <= frame <= end]


def remove_generated_keys(rig, bones, start, end):
    """Remove the GENERATED keys of the given bones between start and end. Returns how many were removed."""
    removed = 0
    for fcurve in bone_fcurves(rig, bones):
        points = fcurve.keyframe_points
        doomed = [i for i, point in enumerate(points)
                  if point.type == GENERATED and start - 0.5 <= point.co.x <= end + 0.5]
        for i in reversed(doomed):
            points.remove(points[i], fast=True)
        if doomed:
            fcurve.update()
        removed += len(doomed)
    return removed


def fix_quaternion_signs(rig, bones):
    """Give every GENERATED rotation key the sign of the key before it (user keys included), so the rotation
    never spins the long way between a user key and a generated one. q and -q are the same rotation."""
    bag = channelbag(rig)
    if bag is None:
        return
    for bone in bones:
        data_path = f'pose.bones["{bpy.utils.escape_identifier(bone)}"].rotation_quaternion'
        curves = [bag.fcurves.find(data_path, index=i) for i in range(4)]
        if any(fc is None for fc in curves):
            continue
        points = [{round(p.co.x): p for p in fc.keyframe_points} for fc in curves]
        previous = None
        flipped = False
        for frame in sorted(set().union(*points)):
            keys = [p.get(frame) for p in points]
            q = [key.co.y if key is not None else fc.evaluate(frame) for key, fc in zip(keys, curves)]
            generated = all(key is not None and key.type == GENERATED for key in keys)
            if generated and previous is not None and sum(a * b for a, b in zip(q, previous)) < 0.0:
                for key in keys:
                    key.co.y = -key.co.y
                    key.handle_left.y = -key.handle_left.y
                    key.handle_right.y = -key.handle_right.y
                q = [-v for v in q]
                flipped = True
            previous = q
        if flipped:
            for fc in curves:
                fc.update()


### The model's armature

def models_collection(context):
    """The collection holding the models' armatures, linked to the scene"""
    collection = bpy.data.collections.get(MODELS_COLLECTION)
    if collection is None:
        collection = bpy.data.collections.new(MODELS_COLLECTION)
    if collection not in context.scene.collection.children_recursive:
        context.scene.collection.children.link(collection)
    return collection


def model_armature(context, rig, backend, skeleton=None):
    """The character's armature for this backend's skeleton. Reused if it was built from that skeleton;
    otherwise rebuilt from `skeleton` (the previous one is deleted). None if it must be built and no skeleton
    is given."""
    state = rig.retargetor
    current = state.model_armature
    if (current is not None and armature_backend(current) == backend.id
            and (skeleton is None or armature_skeleton(current) == skeleton)
            and current.name in context.view_layer.objects):
        return current
    if skeleton is None:
        return None
    if current is not None and armature_skeleton(current) is not None:
        remove_model_armature(current)
    obj = build_armature(context, skeleton, f"{rig.name}_{backend.id}", models_collection(context), backend.id)
    obj.show_in_front = True
    obj.display_type = 'WIRE'
    obj.hide_render = True
    obj.hide_set(True)
    state.model_armature = obj
    return obj


def remove_model_armature(obj):
    data = obj.data
    action = obj.animation_data.action if obj.animation_data else None
    bpy.data.objects.remove(obj)
    if data.users == 0:
        bpy.data.armatures.remove(data)
    if action is not None and action.users == 0:
        bpy.data.actions.remove(action)


def place_model(model, rig, view_layer):
    """Where the rig is, turned like it (not scaled), at rest and without animation. The model's poses are read
    and written in its own armature space: the motion is generated in the character's space, so moving or
    turning the rig object moves or turns the result the same way."""
    if model.animation_data is not None and model.animation_data.action is not None:
        action = model.animation_data.action
        model.animation_data.action = None
        if action.users == 0:
            bpy.data.actions.remove(action)
    for pose_bone in model.pose.bones:
        pose_bone.rotation_mode = 'QUATERNION'
        pose_bone.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
        pose_bone.location = (0.0, 0.0, 0.0)
    rotation = rig.matrix_world.to_3x3().normalized().to_quaternion()
    model.matrix_world = Matrix.LocRotScale(rig.matrix_world.to_translation(), rotation, None)
    view_layer.update()


### Request and result

def build_request(context, rig, model, backend, rig_profile, start, end, key_frames, prompt="", seed=None):
    """Snap the model to the rig on each key frame, and on the start frame (the request's origin), and read
    its poses. Returns (GenerationRequest, translation scale rig -> model, retargeting errors)."""
    scene, view_layer = context.scene, context.view_layer
    skeleton = armature_skeleton(model)
    pairs = core_profile.compose(rig_profile, backend.joint_map, core_profile.TO_MODEL)
    if not pairs:
        raise ValueError(f"No role of the rig profile has a bone to read for {backend.label}.")
    place_model(model, rig, view_layer)
    scale = compute_translation_scale(rig, model, pairs)
    if scale is None:
        raise ValueError(f"Unable to compare the sizes of '{rig.name}' and of the model: map more roles.")
    retargeter = Retargeter(rig, model, pairs, scale[0])

    poses = {}
    original_frame = scene.frame_current
    try:
        for frame in sorted(set(key_frames) | {start}):
            scene.frame_set(frame)
            retargeter.snap_pose(view_layer)
            poses[frame] = read_pose(model, skeleton.names, skeleton.root, world=False)
    finally:
        scene.frame_set(original_frame)

    caps = backend.capabilities
    request = GenerationRequest(start, end, scene.render.fps / scene.render.fps_base,
                                {frame: poses[frame] for frame in key_frames},
                                prompt=prompt if caps.prompt else "", seed=seed if caps.seed else None,
                                origin=poses[start])
    backend.check_request(request)
    return request, scale[0], retargeter.errors


class MotionWriter:
    """Writes a motion onto the rig in several steps, so Blender stays responsive (about 22 ms per frame on
    Rigify, all of it in the rig's evaluation). The motion goes on the model's armature first, then is baked onto
    the rig's write controls as GENERATED keys, from start to end. Frames carrying a user key are never written;
    the GENERATED keys already in the range are removed when the writer is made.
    step() until it returns True; then `frames`, `removed` and `errors` hold the result."""

    def __init__(self, context, rig, model, backend, rig_profile, motion, start, end, translation_scale):
        skeleton = armature_skeleton(model)
        if motion.start_frame > start or motion.end_frame < end:
            raise ValueError(f"The backend returned frames {motion.start_frame}-{motion.end_frame}, "
                             f"{start}-{end} were asked.")
        write_motion_fcurves(model, motion, root_joint=skeleton.root, action_name=f"{model.name}_motion",
                             world=False)
        context.view_layer.update()

        pairs = core_profile.compose(rig_profile, backend.joint_map, core_profile.FROM_MODEL, backend=backend.id)
        # The inverse of the rig -> model scale, so a key pose comes back where it was
        self.retargeter = Retargeter(model, rig, pairs, 1.0 / translation_scale)
        self.rig = rig
        self.controls = [resolved.pair.target for resolved in self.retargeter.order]
        self.removed = remove_generated_keys(rig, self.controls, start, end)
        user_frames = set(user_key_frames(rig, self.controls))
        self.frames = [frame for frame in range(start, end + 1) if frame not in user_frames]
        self.done = 0
        self._previous_rotations = {}
        self._chunk = 2  # frames per step, adjusted to the time budget after each step

    @property
    def errors(self):
        return self.retargeter.errors

    @property
    def fraction(self):
        return self.done / len(self.frames) if self.frames else 1.0

    @property
    def finished(self):
        return self.done >= len(self.frames)

    def step(self, context, budget=0.1):
        """Write the next frames, about `budget` seconds of work. Returns True once every frame is written."""
        if not self.finished:
            chunk = self.frames[self.done:self.done + self._chunk]
            begin = time.perf_counter()
            self.retargeter.bake(context.scene, context.view_layer, chunk, keytype=GENERATED,
                                 previous_rotations=self._previous_rotations)
            per_frame = (time.perf_counter() - begin) / len(chunk)
            self._chunk = max(1, min(100, int(budget / max(per_frame, 1e-4))))
            self.done += len(chunk)
        if self.finished:
            fix_quaternion_signs(self.rig, self.controls)
            return True
        return False


### The task

# Stages of a GenerationTask
SKELETON = "SKELETON"
GENERATING = "GENERATING"
WRITING = "WRITING"
FINISHED = "FINISHED"

# Share of the progress bar taken by the backend's generation; writing the keys takes the rest
GENERATION_SHARE = 0.8


class GenerationError(Exception):
    pass


class GenerationTask:
    """One generation for one character. start(), then update() until it returns True.
    Raises ValueError / KeyError / GenerationError with an explicit message."""

    def __init__(self):
        self.rig_name = ""
        self.backend = None
        self.worker = None
        self.job = None
        self.stage = ""
        self.start_frame = self.end_frame = 0
        self.key_frames = []
        self.rig_profile = None
        self.translation_scale = 1.0
        self.errors = set()
        self.result = None  # (frames written, keys removed) once finished
        self.writer = None
        self.cancel_requested = False
        # The rig was changed before the backend answered (FK snap...): a cancelled generation keeps it
        self.modified = False
        self.started = time.perf_counter()
        self.timings = {}

    @property
    def fraction(self):
        if self.stage == FINISHED:
            return 1.0
        if self.stage == WRITING:
            return GENERATION_SHARE + (1.0 - GENERATION_SHARE) * self.writer.fraction
        if self.stage == GENERATING and self.job is not None:
            return GENERATION_SHARE * self.job.fraction
        return 0.0

    @property
    def message(self):
        if self.stage == SKELETON:
            return f"Starting {self.backend.label}"
        if self.stage == WRITING:
            return f"Writing keys {self.writer.done}/{len(self.writer.frames)}"
        if self.job is not None and self.job.message:
            return self.job.message
        return "Generating"

    @property
    def cancelled(self):
        return self.job is not None and self.job.state == process.CANCELLED

    def _rig(self):
        rig = bpy.data.objects.get(self.rig_name)
        if rig is None or rig.type != 'ARMATURE':
            raise GenerationError(f"The character '{self.rig_name}' doesn't exist anymore.")
        return rig

    def start(self, context, rig):
        self.rig_name = rig.name
        self.backend = active_backend(context)
        self.rig_profile = rig.data.retargetor_profile.to_core()
        self.start_frame, self.end_frame, self.key_frames = generation_range(rig, self.rig_profile)
        scene = context.scene
        problem = self.backend.range_problem(self.start_frame, self.end_frame,
                                             scene.render.fps / scene.render.fps_base, len(self.key_frames))
        if problem:
            raise ValueError(problem)
        check_limbs_fk(rig, self.rig_profile, self.start_frame, self.end_frame)
        self.worker = registry.worker_for(self.backend, backend_settings(context, self.backend))
        model = model_armature(context, rig, self.backend)
        if model is None:
            self.stage = SKELETON
            self.job = self.worker.submit("skeleton")
            self._check_job()
        else:
            self._send_request(context, rig, model)

    def _send_request(self, context, rig, model):
        state = rig.retargetor
        start = time.perf_counter()
        request, self.translation_scale, errors = build_request(
            context, rig, model, self.backend, self.rig_profile, self.start_frame, self.end_frame, self.key_frames,
            state.prompt, state.seed)
        self.timings["key poses"] = time.perf_counter() - start
        self.errors |= errors
        self.stage = GENERATING
        self.job = self.worker.submit("generate", request=request.to_dict())
        self._check_job()

    def _check_job(self):
        if self.job.state == process.FAILED:
            raise GenerationError(f"{self.backend.label}: {self.job.error}")

    @property
    def cancellable(self):
        """Writing the keys can't be cancelled: it would leave the range half written"""
        return self.stage in (SKELETON, GENERATING)

    def update(self, context, budget=0.1):
        """Advance the generation. Returns True when it is finished (or cancelled: see `cancelled`).
        budget: seconds of work at most when writing the keys (a few frames per call)."""
        if self.stage == WRITING:
            return self._write(context, budget)
        self.worker.pump()
        if self.job.active:
            return False
        if self.job.state == process.CANCELLED:
            return True
        self._check_job()

        rig = self._rig()
        if self.stage == SKELETON:
            skeleton = Skeleton.from_dict(self.job.result)
            model = model_armature(context, rig, self.backend, skeleton)
            self._send_request(context, rig, model)
            return False

        if self.stage == GENERATING:
            self.timings["generation"] = self.job.duration
            model = rig.retargetor.model_armature
            skeleton = armature_skeleton(model)
            if model is None or skeleton is None:
                raise GenerationError("The model's armature was deleted during the generation.")
            self._write_started = time.perf_counter()
            motion = protocol.motion_from_frames(self.job.frames, skeleton.names)
            self.worker.forget(self.job)
            self.writer = MotionWriter(context, rig, model, self.backend, self.rig_profile, motion,
                                       self.start_frame, self.end_frame, self.translation_scale)
            self.stage = WRITING
            return False
        return True

    def _write(self, context, budget):
        self._rig()
        if not self.writer.step(context, budget):
            return False
        self.timings["writing"] = time.perf_counter() - self._write_started
        self.errors |= self.writer.errors
        self.result = (len(self.writer.frames), self.writer.removed)
        self.stage = FINISHED
        return True

    def cancel(self):
        if self.cancellable and self.job is not None and self.job.active:
            self.worker.cancel(self.job)

    def run(self, context, rig, timeout=None):
        """Run the whole generation, blocking (scripts, tests). Returns False if it was cancelled."""
        self.start(context, rig)
        limit = timeout or (self.backend.load_timeout + self.backend.generate_timeout)
        begin = time.perf_counter()
        while not self.update(context, budget=1.0):
            if time.perf_counter() - begin > limit:
                self.cancel()
                raise GenerationError(f"{self.backend.label} didn't finish within {limit:.0f} s.")
            time.sleep(0.01)
        return not self.cancelled


# The generation running from the panel, if any (read by the UI for its progress bar)
current_task = None
