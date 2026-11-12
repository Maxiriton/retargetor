"""A rig's pose computed with as few evaluations as possible, to write many frames fast.

Writing a motion onto a rig sets the controls one after the other, and each one depends on the ones before it
(Rigify's FK controls follow their parent control through ORG and MCH bones): read through Blender, that takes a
scene update after each level of controls, several evaluations of the whole rig per frame (3 ms each on Rigify,
20 on a character with its meshes). On most rigs, though, those dependencies are rigid: a control's frame (where
its basis puts it) is the pose of one control upstream times a constant; a bone that is only read follows one
control the same way. RigModel finds those relations once, by turning the controls and looking at what moves
(`probe`), checks them on random poses, then gives the poses of the bones it tracks from the controls' current
basis values:

    frame(bone) = axes: axes(pose(axes anchor)) @ Q, origin: pose(origin anchor) @ p
    pose(bone)  = frame(bone) @ basis(bone)        for a written bone
    pose(bone)  = frame(bone)                      for a bone only read

A part with no anchor (it depends on no written control: the root, a limb's follow) is measured on the rig as
Blender evaluated it, once per frame (`begin_frame`, after `scene.frame_set`). A written bone whose frame isn't
rigid (Rigify's neck follows the torso and the chest half and half) is measured too, after a scene update once the
controls it depends on are set: the written bones come in `levels`, and the writer updates the scene between two
levels (`measure`). A rig where a bone only read isn't rigid, or where the model doesn't give Blender's poses,
fails the check: `probe` raises RigModelError, and the caller writes through Blender's evaluation instead.

Used through a "poser": matrix(name) and set_matrix(pose_bone, matrix), like pose_bone.matrix read and set.
BlenderPoser is the same through Blender's evaluation.
"""
import random

from mathutils import Matrix, Quaternion, Vector

# Probing: a bone moved further than this (relative to the rig's size, or radians) by a turned control depends on
# it. The controls are turned by 0.3 radians; Blender's pose matrices are in single precision.
MOVED = 1e-4
# Checking: the model's poses must match Blender's within these
LOCATION_TOLERANCE = 1e-5  # relative to the rig's size
ROTATION_TOLERANCE = 1e-5  # on the axes' components (about radians)
# Random poses the relations are checked on
CHECKS = 3


class RigModelError(Exception):
    """The rig doesn't fit the model: write through Blender's evaluation"""


class BlenderPoser:
    """The rig's poses as Blender evaluated them (pose_bone.matrix): needs a scene update after each change"""

    def __init__(self, rig):
        self.pose_bones = rig.pose.bones

    def matrix(self, name):
        return self.pose_bones[name].matrix

    def set_matrix(self, pose_bone, matrix):
        pose_bone.matrix = matrix


def _axes_gap(a, b):
    """How far apart two 3x3 matrices are (rotation and scale; shear kept)"""
    return max(abs(x - y) for row_a, row_b in zip(a, b) for x, y in zip(row_a, row_b))


def _with_origin(axes, origin):
    matrix = axes.to_4x4()
    matrix.translation = origin
    return matrix


def _location_axes(pose_bone):
    """How a bone's location is turned into its frame: None when it is in the bone's own axes; else (Local
    Location off: in its parent's axes, as Rigify's IK controls) the rotation from the bone's rest axes to them"""
    bone = pose_bone.bone
    if bone.use_local_location:
        return None
    offset = bone.parent.matrix_local.inverted() @ bone.matrix_local if bone.parent else bone.matrix_local
    return offset.to_3x3().normalized().inverted()


def _compose(frame, basis, axes):
    """The pose a frame and a basis give (Blender: rotation and scale from the frame, the location through the
    location axes)"""
    if axes is None:
        return frame @ basis
    rotscale = frame.to_3x3()
    matrix = (rotscale @ basis.to_3x3()).to_4x4()
    matrix.translation = frame.translation + rotscale @ axes @ basis.translation
    return matrix


def _basis(frame, pose, axes):
    """The basis giving the pose in the frame (the inverse of _compose)"""
    if axes is None:
        return frame.inverted() @ pose
    rotscale = frame.to_3x3()
    basis = (rotscale.inverted() @ pose.to_3x3()).to_4x4()
    basis.translation = (rotscale @ axes).inverted() @ (pose.translation - frame.translation)
    return basis


def _frame_of(pose, basis, axes):
    """The frame a pose has for its basis (_compose solved for the frame)"""
    if axes is None:
        return pose @ basis.inverted()
    rotscale = pose.to_3x3() @ basis.to_3x3().inverted()
    frame = rotscale.to_4x4()
    frame.translation = pose.translation - rotscale @ axes @ basis.translation
    return frame


class _Track:
    """How the model gives one bone's frame"""
    __slots__ = ("name", "written", "rigid", "solved", "depends", "loc_anchor", "rot_anchor", "point", "axes",
                 "origin_now", "axes_now")

    def __init__(self, name, written):
        self.name = name
        self.written = written
        self.rigid = True
        # A written bone whose own constraints (an IK chain's) make its pose depend on its own basis in ways the
        # model can't follow: set as Blender sets pose_bone.matrix, after a scene update; its pose isn't modelled
        self.solved = False
        self.depends = set()  # the written bones moving its frame
        # The written bones its frame's origin and axes follow (rot_anchor: its axes, rotation and scale)
        self.loc_anchor = self.rot_anchor = None
        self.point = self.axes = None  # the constants, in the anchors' spaces
        # Measured on the rig: the parts without anchor, or the whole frame of a bone that isn't rigid
        self.origin_now = self.axes_now = None


class RigModel:
    """The poses of a rig's tracked bones from the basis of the written ones (see the module's docstring).

    rig: the armature object. written: bones whose basis the writer sets. read: bones whose pose it reads (the
    written ones are read too), or {bone: the written bone it is read for}: such a bone needn't follow one control
    rigidly, it is measured before that control is set (Rigify's ORG-spine, read for the torso, follows the hips
    control the user animates). translated: the written bones whose location the writer sets (the others are
    only turned: their location stays as it is, Auto-Rig Pro's FK arm takes its from a constraint). probe() first,
    with the rig as it will be while writing (limbs switched...).
    Then on each frame: scene.frame_set(), begin_frame(); for each of `levels`, after the first one:
    view_layer.update() and measure(level) when needs_update(level); set its bones with set_matrix() (or their
    basis directly), reading poses with matrix()."""

    def __init__(self, rig, written, read=(), translated=()):
        self.rig = rig
        self.pose_bones = rig.pose.bones
        missing = [name for name in list(written) + list(read) if self.pose_bones.get(name) is None]
        if missing:
            raise KeyError(f"The bones {missing} do not exist in '{rig.name}'.")
        self.written = list(dict.fromkeys(written))
        readers = read if isinstance(read, dict) else {}
        self.read = [name for name in dict.fromkeys(read) if name not in self.written]
        self.reader = {name: readers.get(name) for name in self.read}
        self.tracks = {name: _Track(name, True) for name in self.written}
        self.tracks.update({name: _Track(name, False) for name in self.read})
        self.translated = set(translated)
        # Solved bones the writer found it can't place closer than setting their matrix does (kept by the writer)
        self.unreachable = set()
        self.levels = [list(self.written)]
        self.axes = {name: _location_axes(self.pose_bones[name]) for name in self.written}
        scale = max(rig.matrix_world.to_scale())
        self.size = max(max(rig.dimensions) / max(scale, 1e-9), 1e-3)

    @property
    def updates(self):
        """Scene updates per frame besides frame_set"""
        return sum(1 for level in self.levels[1:] if self.needs_update(level))

    def needs_update(self, level):
        return (any(not self.tracks[name].rigid for name in level)
                or any(self.tracks[name].depends - {self.reader[name]} for name in self._reads_for(level)))

    def _reads_for(self, names):
        """The bones read for these written ones that aren't rigid (measured with them)"""
        names = set(names)
        return [name for name in self.read if self.reader[name] in names and not self.tracks[name].rigid]

    # The model

    def _frame_now(self, name):
        """The bone's frame as Blender evaluated it (its pose without its own basis)"""
        pose_bone = self.pose_bones[name]
        if self.tracks[name].written:
            return _frame_of(pose_bone.matrix, pose_bone.matrix_basis, self.axes[name])
        return pose_bone.matrix.copy()

    def _measure(self, track):
        frame = self._frame_now(track.name)
        track.origin_now, track.axes_now = frame.translation, frame.to_3x3()

    def begin_frame(self):
        """Measure the parts without anchor, and the frames that aren't rigid, on the rig as Blender just
        evaluated it (after scene.frame_set)"""
        for track in self.tracks.values():
            self._measure(track)

    def measure(self, names):
        """Measure again the frames of the bones that aren't rigid, after a scene update"""
        for name in list(names) + self._reads_for(names):
            track = self.tracks[name]
            if not track.rigid:
                self._measure(track)

    def _frame(self, track, pose=None):
        if not track.rigid:
            return _with_origin(track.axes_now, track.origin_now)
        pose = pose or self.matrix
        origin = track.origin_now if track.loc_anchor is None else pose(track.loc_anchor) @ track.point
        axes = track.axes_now if track.rot_anchor is None else pose(track.rot_anchor).to_3x3() @ track.axes
        return _with_origin(axes, origin)

    def matrix(self, name):
        """The bone's pose (armature space), as pose_bone.matrix would be once evaluated"""
        track = self.tracks[name]
        if track.solved:
            return self.pose_bones[name].matrix
        frame = self._frame(track)
        if track.written:
            return _compose(frame, self.pose_bones[name].matrix_basis, self.axes[name])
        return frame

    def set_matrix(self, pose_bone, matrix):
        """Give the written bone the basis putting it on `matrix`, as setting pose_bone.matrix does"""
        name = pose_bone.name
        if self.tracks[name].solved:
            pose_bone.matrix = matrix
            return
        basis = _basis(self._frame(self.tracks[name]), matrix, self.axes[name])
        location, rotation, scale = basis.decompose()
        pose_bone.location = location
        if pose_bone.rotation_mode == 'QUATERNION':
            pose_bone.rotation_quaternion = rotation
        elif pose_bone.rotation_mode == 'AXIS_ANGLE':
            axis, angle = rotation.to_axis_angle()
            pose_bone.rotation_axis_angle = (angle, axis.x, axis.y, axis.z)
        else:
            pose_bone.rotation_euler = rotation.to_euler(pose_bone.rotation_mode, pose_bone.rotation_euler)
        pose_bone.scale = scale

    # Finding the relations

    def probe(self, view_layer, scene=None, frames=(), prepare=None, seed=0):
        """Find each tracked bone's anchors by turning the written bones one at a time, check them on random
        poses, and sort the written bones in levels. The rig's pose is put back. Raises RigModelError when the
        rig doesn't fit the model.
        The rig must be as its animation makes it on the current frame (scene.frame_set() just before): a basis
        its F-curves don't give (keys just removed) is put back to theirs by Blender at the next evaluation of the
        animation, a change of one bone then seeming to move others.
        frames: other frames of the scene the relations are checked on as the rig's animation makes it there (a
        bone the writer doesn't set, animated, may change them: Rigify's hips control, between the torso and
        ORG-spine). prepare(): called after each change of frame, returns True if it changed the rig (the
        writer's own settings for every frame: the REST controls at rest)."""
        saved = {name: self.pose_bones[name].matrix_basis.copy() for name in self.written}
        rng = random.Random(seed)
        try:
            self._find_anchors(view_layer, saved)
            self._check_relations(view_layer, saved, rng)
            if scene is not None:
                self._check_frames(scene, view_layer, frames, prepare)
            self.levels = self._sorted()
            unfit = [name for name in self.read if not self.tracks[name].rigid and self.reader[name] is None]
            if unfit:
                raise RigModelError(f"The bones read {unfit} don't follow one control rigidly")
            self._check_writing(view_layer, saved, rng)
        finally:
            for name, basis in saved.items():
                self.pose_bones[name].matrix_basis = basis
            view_layer.update()

    def _find_anchors(self, view_layer, saved):
        view_layer.update()
        names = list(self.tracks)
        frames = {name: self._frame_now(name) for name in names}
        poses = {name: self.pose_bones[name].matrix.copy() for name in names}
        moves_loc = {name: set() for name in names}  # {bone: written bones moving its frame's location}
        moves_rot = {name: set() for name in names}
        turn = Quaternion(Vector((1.0, 1.0, 1.0)).normalized(), 0.3)
        for moved in self.written:
            shift = Vector((0.03, 0.02, 0.01)) * self.size if moved in self.translated else None
            self.pose_bones[moved].matrix_basis = saved[moved] @ Matrix.LocRotScale(shift, turn, None)
            view_layer.update()
            for name in names:
                before, after = frames[name], self._frame_now(name)
                origin_moved = (before.translation - after.translation).length > MOVED * self.size
                axes_moved = _axes_gap(before.to_3x3(), after.to_3x3()) > MOVED
                if name == moved:
                    if origin_moved or axes_moved:
                        self.tracks[name].solved = True
                    continue
                if origin_moved:
                    moves_loc[name].add(moved)
                if axes_moved:
                    moves_rot[name].add(moved)
            self.pose_bones[moved].matrix_basis = saved[moved]
        view_layer.update()

        # {written bone: written bones moving its pose}: its frame's, and itself
        moves_pose = {name: moves_loc[name] | moves_rot[name] | {name} for name in self.written}
        for name in names:
            track = self.tracks[name]
            track.depends = moves_loc[name] | moves_rot[name]
            if track.solved:
                track.rigid = False
                continue
            try:
                track.loc_anchor = self._anchor(moves_loc[name], moves_pose)
                track.rot_anchor = self._anchor(moves_rot[name], moves_pose)
            except RigModelError:
                track.rigid = False
                continue
            frame = frames[name]
            if track.loc_anchor is not None:
                track.point = poses[track.loc_anchor].inverted() @ frame.translation
            if track.rot_anchor is not None:
                track.axes = poses[track.rot_anchor].to_3x3().inverted() @ frame.to_3x3()

    @staticmethod
    def _anchor(moving, moves_pose):
        """The written bone, among those moving this part, that all the others move too: the part follows them
        through it. None when nothing moves it."""
        if not moving:
            return None
        for candidate in moving:
            if moving <= moves_pose[candidate]:
                return candidate
        raise RigModelError("follows several controls apart")

    def _close(self, a, b):
        return ((a.translation - b.translation).length / self.size <= LOCATION_TOLERANCE
                and _axes_gap(a.to_3x3(), b.to_3x3()) <= ROTATION_TOLERANCE)

    def _randomize(self, names, saved, rng):
        for name in names:
            axis = Vector((rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1)))
            if axis.length < 1e-3:
                axis = Vector((0.0, 0.0, 1.0))
            offset = None
            if name in self.translated:
                offset = Vector((rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1))) * 0.03 * self.size
            self.pose_bones[name].matrix_basis = saved[name] @ Matrix.LocRotScale(
                offset, Quaternion(axis.normalized(), rng.uniform(-0.5, 0.5)), None)

    def _check_relations(self, view_layer, saved, rng):
        """On random poses of the written bones, each frame is where its relation puts it from the anchors'
        actual poses (the parts without anchor measured before the change): a bone that isn't is measured
        instead, once the controls it depends on are set"""
        view_layer.update()
        for _ in range(CHECKS):
            self.begin_frame()
            self._randomize(self.written, saved, rng)
            view_layer.update()
            actual = {name: self.pose_bones[name].matrix.copy() for name in self.tracks}
            for track in self.tracks.values():
                if track.rigid and not self._close(self._frame(track, actual.get), self._frame_now(track.name)):
                    track.rigid = False
            for name, basis in saved.items():
                self.pose_bones[name].matrix_basis = basis
            view_layer.update()

    def _check_frames(self, scene, view_layer, frames, prepare):
        """On other frames, as the animation makes them, each frame is where its relation puts it"""
        original = scene.frame_current

        def go(frame):
            scene.frame_set(frame)
            if prepare is not None and prepare():
                view_layer.update()

        try:
            for frame in frames:
                if frame == original:
                    continue
                go(frame)
                self.begin_frame()
                actual = {name: self.pose_bones[name].matrix.copy() for name in self.tracks}
                for track in self.tracks.values():
                    if track.rigid and not self._close(self._frame(track, actual.get),
                                                       self._frame_now(track.name)):
                        track.rigid = False
        finally:
            go(original)

    def _sorted(self):
        """The written bones in levels: a bone comes after its anchors, and a bone that isn't rigid in a level
        after every control it depends on (it is measured after a scene update)"""
        for track in self.tracks.values():
            # A solved bone's pose isn't modelled: what follows it is measured once it is set
            if track.rigid and any(a is not None and self.tracks[a].solved
                                   for a in (track.loc_anchor, track.rot_anchor)):
                track.rigid = False
        level = {}

        def level_of(name, path):
            if name in level:
                return level[name]
            if name in path:
                details = "; ".join(f"{n}: {'rigid' if self.tracks[n].rigid else 'measured'}, anchors "
                                    f"{self.tracks[n].loc_anchor} {self.tracks[n].rot_anchor}, depends on "
                                    f"{sorted(self.tracks[n].depends)}" for n in sorted(path))
                raise RigModelError(f"'{name}' depends on itself through other controls ({details})")
            track = self.tracks[name]
            if track.rigid:
                anchors = [a for a in (track.loc_anchor, track.rot_anchor) if a is not None]
                value = max((level_of(a, path | {name}) for a in anchors), default=0)
            else:
                value = max((level_of(d, path | {name}) + 1 for d in track.depends), default=0)
            # A bone read for this one, measured with it: after what it depends on but this one
            for read in self._reads_for([name]):
                value = max([value] + [level_of(d, path | {name}) + 1
                                       for d in self.tracks[read].depends - {name}])
            level[name] = value
            return value

        for name in self.written:
            level_of(name, frozenset())
        levels = [[] for _ in range(max(level.values(), default=0) + 1)]
        # Within a level, anchors first
        placed = set()

        def place(name):
            if name in placed:
                return
            track = self.tracks[name]
            if track.rigid:
                for anchor in (track.loc_anchor, track.rot_anchor):
                    if anchor is not None and level[anchor] == level[name]:
                        place(anchor)
            placed.add(name)
            levels[level[name]].append(name)

        for name in self.written:
            place(name)
        return [names for names in levels if names]

    def _check_writing(self, view_layer, saved, rng):
        """The poses the model gives while writing, level by level as the writer does, are Blender's"""
        for _ in range(2):
            view_layer.update()
            self.begin_frame()
            for index, level in enumerate(self.levels):
                if index and self.needs_update(level):
                    view_layer.update()
                    self.measure(level)
                self._randomize(level, saved, rng)
            # A bone read for a written one is only measured until that one is set
            predicted = {name: self.matrix(name) for name, track in self.tracks.items()
                         if not track.solved and (track.written or track.rigid)}
            view_layer.update()
            for name, matrix in predicted.items():
                actual = self.pose_bones[name].matrix
                if not self._close(matrix, actual):
                    track = self.tracks[name]
                    raise RigModelError(f"'{name}' isn't where the model puts it "
                                        f"({(matrix.translation - actual.translation).length:.2g} away, axes "
                                        f"{_axes_gap(matrix.to_3x3(), actual.to_3x3()):.2g} apart; rigid "
                                        f"{track.rigid}, anchors {track.loc_anchor} {track.rot_anchor}, depends on "
                                        f"{sorted(track.depends)})")
            for name, basis in saved.items():
                self.pose_bones[name].matrix_basis = basis
