"""Snapping and baking a target armature onto a source armature.

Everything comes in as arguments: the two armature objects, the bone pairs (core.retarget.pairs.BonePair),
the translation scale and the frames. Nothing is read from the scene properties.

Rest offsets (roll and rest rotation difference) are computed here from the two rest poses: they depend on
both skeletons, so they are not stored.
"""
import math

from mathutils import Matrix, Quaternion, Vector

from .pairs import target_map


def rest_rotations(source_obj, target_obj, source_name, target_name):
    """World-space rest orientations (scale ignored) of a source/target bone pair.
    Raises KeyError if one of the bones doesn't exist."""
    src_bone = source_obj.data.bones.get(source_name)
    if src_bone is None:
        raise KeyError(f"The source bone '{source_name}' does not exist in the armature '{source_obj.name}'.")
    tgt_bone = target_obj.data.bones.get(target_name)
    if tgt_bone is None:
        raise KeyError(f"The target bone '{target_name}' does not exist in the armature '{target_obj.name}'.")

    q_src = (source_obj.matrix_world @ src_bone.matrix_local).to_quaternion()
    q_tgt = (target_obj.matrix_world @ tgt_bone.matrix_local).to_quaternion()
    return q_src, q_tgt


def rest_offsets(source_obj, target_obj, source_name, target_name):
    """(roll offset in radians, rest offset Quaternion) of a pair, from the rest poses of its two bones."""
    q_src, q_tgt = rest_rotations(source_obj, target_obj, source_name, target_name)

    # Roll: angle around the target's local Y axis, from the source's X axis expressed in the target's local space
    x_src_in_tgt_local = q_tgt.inverted() @ (q_src @ Vector((1.0, 0.0, 0.0)))
    roll = math.atan2(x_src_in_tgt_local.z, x_src_in_tgt_local.x)

    # Rest offset: rotation difference between the two bones in their rest pose
    return roll, q_src.rotation_difference(q_tgt)


def compute_translation_scale(source_obj, target_obj, pairs):
    """Ratio target height / source height, measured on the given pairs only (rest pose, world space).
    The height is the Z extent of the bone heads of the pairs, so both rigs are measured on the same landmarks.
    Returns (scale, source_height, target_height), or None if it can't be measured."""
    src_z = []
    tgt_z = []
    for pair in pairs:
        if not pair.source or not pair.target:
            continue
        src_bone = source_obj.data.bones.get(pair.source)
        tgt_bone = target_obj.data.bones.get(pair.target)
        if src_bone is None or tgt_bone is None:
            continue
        src_z.append((source_obj.matrix_world @ src_bone.head_local).z)
        tgt_z.append((target_obj.matrix_world @ tgt_bone.head_local).z)

    if len(src_z) < 2:
        return None

    source_height = max(src_z) - min(src_z)
    target_height = max(tgt_z) - min(tgt_z)
    if source_height < 1e-6 or target_height < 1e-6:
        return None

    return target_height / source_height, source_height, target_height


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


def rotation_data_path(pose_bone):
    """The rotation property used by the bone's rotation mode"""
    if pose_bone.rotation_mode == 'QUATERNION':
        return "rotation_quaternion"
    if pose_bone.rotation_mode == 'AXIS_ANGLE':
        return "rotation_axis_angle"
    return "rotation_euler"


def set_rotation(pose_bone, rotation_mode, q):
    """Give the bone the rotation q (a Quaternion) in its own rotation mode. Euler angles stay close to the
    bone's current ones, so keys made frame after frame don't jump by 360 degrees."""
    if rotation_mode == 'QUATERNION':
        pose_bone.rotation_mode = 'QUATERNION'
        pose_bone.rotation_quaternion = q
        return
    previous = pose_bone.rotation_euler.copy()
    pose_bone.rotation_mode = rotation_mode
    if rotation_mode == 'AXIS_ANGLE':
        axis, angle = q.to_axis_angle()
        pose_bone.rotation_axis_angle = (angle, axis.x, axis.y, axis.z)
    else:
        pose_bone.rotation_euler = q.to_euler(rotation_mode, previous)


def _same_matrix(a, b, tolerance=1e-6):
    return all(abs(x - y) <= tolerance for row_a, row_b in zip(a, b) for x, y in zip(row_a, row_b))


class _ResolvedPair:
    """A BonePair with its pose bones and rest offsets looked up once."""
    __slots__ = ("pair", "src_pose_bone", "tgt_pose_bone", "roll", "rest_offset", "correction", "rotation_mode",
                 "pivot_bone")

    def __init__(self, source_obj, target_obj, pair):
        self.pair = pair
        self.src_pose_bone = source_obj.pose.bones.get(pair.source)
        if self.src_pose_bone is None:
            raise KeyError(f"The source bone '{pair.source}' does not exist in the source armature '{source_obj.name}'.")
        self.tgt_pose_bone = target_obj.pose.bones.get(pair.target)
        if self.tgt_pose_bone is None:
            raise KeyError(f"The target bone '{pair.target}' does not exist in the armature '{target_obj.name}'.")
        self.roll, self.rest_offset = rest_offsets(source_obj, target_obj, pair.source, pair.target)
        self.correction = Quaternion(pair.correction) if pair.correction is not None else None
        # The target keeps its rotation mode (Rigify's shoulders are in Euler, for example)
        self.rotation_mode = self.tgt_pose_bone.rotation_mode
        self.pivot_bone = None
        if pair.pivot:
            self.pivot_bone = target_obj.data.bones.get(pair.pivot)
            if self.pivot_bone is None:
                raise KeyError(f"The pivot bone '{pair.pivot}' does not exist in the armature '{target_obj.name}'.")


class Retargeter:
    """Copies the pose of a source armature onto a target armature, for a given list of bone pairs.

    Raises ValueError if an armature is missing or several pairs write to the same target bone.
    Pairs whose bones can't be found are skipped; their messages are in `errors`.
    """

    def __init__(self, source_obj, target_obj, pairs, translation_scale=1.0):
        if source_obj is None or target_obj is None:
            raise ValueError("The source or target armature is not set.")
        if source_obj.type != 'ARMATURE' or target_obj.type != 'ARMATURE':
            raise ValueError("The source and the target must both be armatures.")

        self.source_obj = source_obj
        self.target_obj = target_obj
        self.translation_scale = translation_scale

        self.resolved = {}  # {target bone name: _ResolvedPair}
        self._unresolved = {}  # {target bone name: why the pair was skipped}
        for target_name, pair in target_map(pairs).items():
            try:
                self.resolved[target_name] = _ResolvedPair(source_obj, target_obj, pair)
            except KeyError as e:
                self._unresolved[target_name] = str(e.args[0])
        self.errors = set(self._unresolved.values())

        # Target bones in hierarchy order (parents first), so a child is snapped after its parent
        self.order = []
        roots = [bone for bone in target_obj.data.bones if bone.parent is None]
        if not roots:
            raise ValueError(f"The armature '{target_obj.name}' contains no bones.")
        stack = list(reversed(roots))
        while stack:
            bone = stack.pop()
            if bone.name in self.resolved:
                self.order.append(self.resolved[bone.name])
            stack.extend(reversed(bone.children))

        # Snapping levels, worked out on the first snap (see _dependency_levels)
        self._levels = None

    @property
    def target_bones(self):
        """Pose bones of the target that receive the pose, in hierarchy order."""
        return [r.tgt_pose_bone for r in self.order]

    def _scaled_target_location(self, resolved):
        """Position of the target bone head (in target armature space) for a bone flagged "Use Translation".

        The source's movement away from its rest position is scaled by the translation scale
        and added to the target's own rest position:
            target = target rest + k * (source now - source rest)
        With a pivot (BonePair.pivot), the movement goes to the pivot, and the target keeps its rest offset to
        the pivot, turned like the source bone:
            target = pivot rest + k * (source now - source rest) + R * (target rest - pivot rest)
        Everything is computed in world space, so object transforms and scales are taken into account.
        """
        source_obj, target_obj = self.source_obj, self.target_obj
        src_bone = resolved.src_pose_bone
        src_rest_world = source_obj.matrix_world @ src_bone.bone.head_local
        src_now_world = source_obj.matrix_world @ src_bone.head
        tgt_rest_world = target_obj.matrix_world @ resolved.tgt_pose_bone.bone.head_local
        movement = self.translation_scale * (src_now_world - src_rest_world)

        if resolved.pivot_bone is None:
            tgt_world = tgt_rest_world + movement
        else:
            pivot_rest_world = target_obj.matrix_world @ resolved.pivot_bone.head_local
            # The source bone's rotation from rest, in world space
            now = (source_obj.matrix_world @ src_bone.matrix).to_3x3().normalized()
            rest = (source_obj.matrix_world @ src_bone.bone.matrix_local).to_3x3().normalized()
            turn = now @ rest.transposed()
            tgt_world = pivot_rest_world + movement + turn @ (tgt_rest_world - pivot_rest_world)
        return target_obj.matrix_world.inverted() @ tgt_world

    def _snap(self, resolved, add_roll=True, add_correction=True):
        pair = resolved.pair
        tgt_pose_bone = resolved.tgt_pose_bone

        # Source pose expressed in the target armature space (object transforms included).
        # The scale is dropped: only the position and the orientation are copied.
        matrix = self.target_obj.matrix_world.inverted() @ self.source_obj.matrix_world @ resolved.src_pose_bone.matrix
        location, rotation, _scale = matrix.decompose()

        if pair.use_translation:
            location = self._scaled_target_location(resolved)

        previous_euler = tgt_pose_bone.rotation_euler.copy()
        tgt_pose_bone.rotation_mode = 'QUATERNION'
        tgt_pose_bone.matrix = Matrix.LocRotScale(location, rotation, None)

        q_rot = tgt_pose_bone.rotation_quaternion.copy()

        if add_roll:
            if pair.offset_mode == 'ROLL':
                q_rot = q_rot @ Quaternion(Vector((0.0, 1.0, 0.0)), resolved.roll)
            elif pair.offset_mode == 'REST_OFFSET':
                q_rot = q_rot @ resolved.rest_offset

        if add_correction and resolved.correction is not None:
            q_rot = q_rot @ resolved.correction

        tgt_pose_bone.rotation_euler = previous_euler
        set_rotation(tgt_pose_bone, resolved.rotation_mode, q_rot)

        # Only the bones flagged "Use Translation" keep the copied translation
        if not pair.use_translation:
            tgt_pose_bone.location = Vector((0.0, 0.0, 0.0))

    def snap_bone(self, target_name, add_roll=True, add_correction=True):
        """Snap a single target bone at the current frame. Raises KeyError if it isn't mapped."""
        resolved = self.resolved.get(target_name)
        if resolved is None:
            raise KeyError(self._unresolved.get(
                target_name, f"The target bone '{target_name}' is not mapped to a source bone."))
        self._snap(resolved, add_roll=add_roll, add_correction=add_correction)

    def _dependency_levels(self, view_layer):
        """Target bones grouped in levels: a bone depends only on bones of lower levels.

        A bone reads the evaluated matrices of the bones it depends on, and only a scene update refreshes them:
        snapping level by level, with an update in between, gives every bone its final input, so one sweep is
        exact. Dependencies are found by turning each target bone in turn and looking at which other target
        bones move: they go through the hierarchy, but also through constraints (Rigify's FK controls follow
        their parent control through ORG and MCH bones), which the hierarchy alone doesn't show."""
        bones = [r.tgt_pose_bone for r in self.order]
        saved = [pb.matrix_basis.copy() for pb in bones]
        view_layer.update()
        rest = [pb.matrix.copy() for pb in bones]
        depends = [set() for _ in bones]
        turn = Matrix.Rotation(0.5, 4, 'X')
        for j, pb in enumerate(bones):
            pb.matrix_basis = saved[j] @ turn
            view_layer.update()
            for i, other in enumerate(bones):
                if i != j and not _same_matrix(other.matrix, rest[i]):
                    depends[i].add(j)
            pb.matrix_basis = saved[j]
        view_layer.update()

        # Longest chain of dependencies above each bone. Bones depending on each other (a cycle through
        # constraints) can't be ordered: they share a level and need more sweeps.
        level = [0] * len(bones)
        for _round in range(len(bones)):
            changed = False
            for i, deps in enumerate(depends):
                wanted = max((level[j] + 1 for j in deps if i not in depends[j]), default=0)
                if wanted > level[i] and wanted < len(bones):
                    level[i] = wanted
                    changed = True
            if not changed:
                break
        levels = [[] for _ in range(max(level, default=-1) + 1)]
        for i, resolved in enumerate(self.order):
            levels[level[i]].append(resolved)
        return [group for group in levels if group]

    def levels(self, view_layer):
        """The snapping levels (computed once, see _dependency_levels)"""
        if self._levels is None:
            self._levels = self._dependency_levels(view_layer)
        return self._levels

    def snap_pose(self, view_layer, add_roll=True, add_correction=True, repetitions=1, final_update=True):
        """Snap every mapped target bone at the current frame, one dependency level at a time (see
        _dependency_levels): one sweep is exact. repetitions: number of sweeps, only useful for bones that
        depend on each other. final_update: refresh the scene after the last level (not needed to key)."""
        levels = self.levels(view_layer)
        for sweep in range(repetitions):
            for index, level in enumerate(levels):
                for resolved in level:
                    self._snap(resolved, add_roll=add_roll, add_correction=add_correction)
                if final_update or sweep < repetitions - 1 or index < len(levels) - 1:
                    view_layer.update()

    def bake(self, scene, view_layer, frames, keytype='KEYFRAME', repetitions=1, previous_rotations=None):
        """Snap and key the mapped target bones on each of the given frames (Blender frame numbers).
        Rotations are keyed in each bone's own rotation mode (quaternions with continuous signs); locations only
        on the bones flagged "Use Translation". The current frame is restored at the end. Returns the number of frames baked.
        previous_rotations: {bone name: Quaternion keyed on the previous frame}, to bake in several calls with
        continuous quaternion signs (pass the same dict to each call)."""
        frames = sorted(set(int(f) for f in frames))
        keyed = [(r.tgt_pose_bone, r.pair.use_translation, r.rotation_mode == 'QUATERNION') for r in self.order]
        original_frame = scene.frame_current
        if previous_rotations is None:
            previous_rotations = {}

        try:
            for frame in frames:
                scene.frame_set(frame)
                self.snap_pose(view_layer, repetitions=repetitions, final_update=False)

                for bone, use_translation, quaternion in keyed:
                    if quaternion:
                        keep_quaternion_continuous(bone, previous_rotations)
                    if use_translation:
                        bone.keyframe_insert(data_path="location", frame=frame, keytype=keytype)
                    bone.keyframe_insert(data_path=rotation_data_path(bone), frame=frame, keytype=keytype)
        finally:
            scene.frame_set(original_frame)

        return len(frames)


def snap_pose(context, source_obj, target_obj, pairs, translation_scale=1.0, add_roll=True, repetitions=1):
    """Snap the target armature onto the source at the current frame. Returns the set of error messages."""
    retargeter = Retargeter(source_obj, target_obj, pairs, translation_scale)
    retargeter.snap_pose(context.view_layer, add_roll=add_roll, repetitions=repetitions)
    return retargeter.errors


def bake(context, source_obj, target_obj, pairs, frames, translation_scale=1.0, keytype='KEYFRAME', repetitions=1):
    """Snap and key the target armature on the given frames. Returns the set of error messages."""
    retargeter = Retargeter(source_obj, target_obj, pairs, translation_scale)
    retargeter.bake(context.scene, context.view_layer, frames, keytype=keytype, repetitions=repetitions)
    return retargeter.errors
