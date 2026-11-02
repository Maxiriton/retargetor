"""Conversions between the add-on's neutral data (Blender conventions) and Kimodo's. numpy only: no bpy, no
torch, so they can be tested without the model.

Kimodo (checked in spikes/phase0 and phase1):
- Y-up: Blender (x, y, z) -> Kimodo (x, z, -y). Meters.
- Rest pose: the SOMA standard T-pose, so a joint's global rotation is its rotation from rest.
- Constraints: local rotations as axis-angle, for the 30 joints the model works on, each relative to its
  parent in the 77-joint skeleton (not in the 30-joint one: it matters for the hand end joints).
- Canonical frame: the motion starts at XZ = (0, 0) facing +Z (heading 0, from the hips). The request's origin
  (the character on the first frame) is moved there (translation and rotation around Y), the key poses with it,
  and the result is moved back.
- 30 fps. Key frames go to the nearest model frame; between key poses (and the ends of the range) the time is
  stretched linearly so every key pose lands exactly on its model frame, then the result is resampled to the
  scene's frame rate.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from core import quat
from core.skeleton import Joint, Skeleton

# Blender -> Kimodo axes: v_kimodo = B_TO_K @ v_blender (a rotation, so its inverse is its transpose)
B_TO_K = np.array([[1.0, 0.0, 0.0], [0.0, 0.0, 1.0], [0.0, -1.0, 0.0]])

# Height of the hips in the rest pose (the 77-joint neutral joints are relative to the hips). Same as Kimodo's
# BVH export, so the armature is the one Phase 0 imported.
HIPS_HEIGHT = 1.0
# Length given to end joints (no child), along the up axis, as Blender's BVH importer does
END_LENGTH = 0.001


def to_kimodo(v):
    return np.asarray(v, dtype=np.float64) @ B_TO_K.T


def to_blender(v):
    return np.asarray(v, dtype=np.float64) @ B_TO_K


def quat_to_kimodo(q):
    """A rotation expressed in Blender's axes -> the same rotation in Kimodo's axes"""
    q = np.asarray(q, dtype=np.float64)
    return np.concatenate((q[..., :1], to_kimodo(q[..., 1:])), axis=-1)


def quat_to_blender(q):
    q = np.asarray(q, dtype=np.float64)
    return np.concatenate((q[..., :1], to_blender(q[..., 1:])), axis=-1)


### Skeleton

def soma_skeleton(names, parents, neutral_joints):
    """The 77-joint SOMA skeleton in Blender conventions, from Kimodo's joint names, parent indices (-1 for
    the root) and neutral joints (Y-up, relative to the hips). Tails follow Blender's BVH importer: the child's
    head, the mean of the children's heads, or a short bone pointing up for end joints."""
    heads = to_blender(neutral_joints) + np.array((0.0, 0.0, HIPS_HEIGHT))
    children = {i: [] for i in range(len(names))}
    for i, p in enumerate(parents):
        if p >= 0:
            children[p].append(i)
    joints = []
    root = ""
    for i, name in enumerate(names):
        kids = children[i]
        if kids:
            tail = heads[kids].mean(axis=0)
        else:
            tail = heads[i] + np.array((0.0, 0.0, END_LENGTH))
        if np.linalg.norm(tail - heads[i]) < 1e-6:
            tail = heads[i] + np.array((0.0, 0.0, END_LENGTH))
        parent = names[parents[i]] if parents[i] >= 0 else None
        if parent is None:
            root = name
        joints.append(Joint(name, parent, tuple(heads[i].tolist()), tuple(tail.tolist())))
    return Skeleton(joints, root=root)


### Frame rates

def model_key_indices(key_frames, fps, model_fps, start=None):
    """Model frame of each key frame (sorted Blender frames at `fps`): the nearest one in time, counted from the
    Blender frame `start` (default: the first key frame). Raises ValueError if two key poses fall on the same
    model frame."""
    if start is None:
        start = key_frames[0]
    indices = [int(round((frame - start) / fps * model_fps)) for frame in key_frames]
    for a, b, fa, fb in zip(indices, indices[1:], key_frames, key_frames[1:]):
        if b <= a:
            raise ValueError(f"The key poses on frames {fa} and {fb} are too close for the model's "
                             f"{model_fps:g} fps.")
    return indices


def model_times(frames, key_frames, key_indices):
    """Fractional model frame of each Blender frame: piecewise linear between the key poses, so each key
    frame lands exactly on its model frame. Frames outside the key poses are clamped."""
    frames = np.asarray(frames, dtype=np.float64)
    return np.interp(frames, np.asarray(key_frames, dtype=np.float64), np.asarray(key_indices, dtype=np.float64))


@dataclass
class Timing:
    """Where a request's Blender frames fall among the model's frames.
    key_indices: model frame of each key pose. count: number of model frames to generate.
    anchors / anchor_indices: Blender frames (range start, key poses, range end) and their model frames, for
    model_times."""
    key_indices: list
    count: int
    anchors: list
    anchor_indices: list


def model_timing(start, end, key_frames, fps, model_fps):
    """The Timing of a range of Blender frames (start to end at `fps`) holding the sorted key_frames"""
    key_indices = model_key_indices(key_frames, fps, model_fps, start) if key_frames else []
    count = int(round((end - start) / fps * model_fps)) + 1
    if key_indices:
        count = max(count, key_indices[-1] + 1)
    indices = {start: 0, end: count - 1}
    indices.update(zip(key_frames, key_indices))
    anchors = sorted(indices)
    return Timing(key_indices, count, anchors, [indices[f] for f in anchors])


def resample(rotations, positions, times):
    """Rotations (T, J, 4) and positions (T, 3) at fractional frame times (slerp, lerp)"""
    last = len(rotations) - 1
    i0 = np.clip(np.floor(times).astype(int), 0, last)
    i1 = np.minimum(i0 + 1, last)
    u = np.clip(times - i0, 0.0, 1.0)
    rot = quat.slerp(rotations[i0], rotations[i1], u[:, None, None])
    pos = positions[i0] + u[:, None] * (positions[i1] - positions[i0])
    return rot, pos


### Canonical frame

def rotation_y(angle):
    return np.array((math.cos(angle / 2), 0.0, math.sin(angle / 2), 0.0))


def heading_angle(hips_rotation, right_hip_rest, left_hip_rest):
    """Kimodo's heading of a pose (its compute_heading_angle): from the vector between the hip joints,
    0 when the body faces +Z. hips_rotation: global rotation of the hips (Kimodo axes); *_rest: rest positions
    of the right and left hip joints (Kimodo axes)."""
    d = quat.rotate(hips_rotation, np.asarray(right_hip_rest) - np.asarray(left_hip_rest))
    return math.atan2(d[2], -d[0])


@dataclass
class Canonical:
    """The move bringing the first key pose to Kimodo's canonical frame: translate by -origin, then rotate
    by `rotation` around Y."""
    origin: np.ndarray
    rotation: np.ndarray

    @property
    def heading(self):
        return -2.0 * math.atan2(self.rotation[2], self.rotation[0])

    def apply(self, rotations, positions):
        """Global rotations (..., 4) and positions (..., 3), Kimodo axes, into the canonical frame"""
        return quat.multiply(self.rotation, rotations), quat.rotate(self.rotation, positions - self.origin)

    def undo(self, rotations, positions):
        inverse = quat.conjugate(self.rotation)
        return quat.multiply(inverse, rotations), quat.rotate(inverse, positions) + self.origin


### Request and result

@dataclass
class SomaLayout:
    """What the conversions need to know about the SOMA skeletons"""
    names77: list
    parents77: list          # parent index in the 77-joint skeleton, -1 for the root
    names30: list            # joints the model works on (constraints)
    root: str
    right_hip: str
    left_hip: str
    neutral77: np.ndarray    # rest positions, Kimodo axes, relative to the hips

    def index(self, name):
        return self.names77.index(name)


def _pose_arrays(pose, layout, what):
    """Global rotations (77, 4) and root position (3,) of a Pose, Blender axes. Joints missing from the pose
    stay at rest relative to their parent."""
    if pose.root_position is None:
        raise ValueError(f"{what} has no root position.")
    rotations = np.empty((len(layout.names77), 4))
    for j, name in enumerate(layout.names77):
        given = pose.rotations.get(name)
        if given is not None:
            rotations[j] = given
        else:
            parent = layout.parents77[j]
            rotations[j] = rotations[parent] if parent >= 0 else (1.0, 0.0, 0.0, 0.0)
    return rotations, np.asarray(pose.root_position, dtype=np.float64)


def key_poses_to_kimodo(request, layout):
    """Global rotations (keys, 77, 4) and root positions (keys, 3) of the request's key poses, in Kimodo's
    axes. Joints missing from a pose stay at rest relative to their parent."""
    frames = sorted(request.key_poses)
    rotations = np.empty((len(frames), len(layout.names77), 4))
    roots = np.empty((len(frames), 3))
    for k, frame in enumerate(frames):
        rotations[k], roots[k] = _pose_arrays(request.key_poses[frame], layout, f"The key pose on frame {frame}")
    return frames, quat_to_kimodo(rotations), to_kimodo(roots)


def canonical_from(rotations, roots, layout):
    """The Canonical move of the first pose of rotations (poses, 77, 4) and roots (poses, 3), Kimodo axes"""
    hips = rotations[0, layout.index(layout.root)]
    angle = heading_angle(hips, layout.neutral77[layout.index(layout.right_hip)],
                          layout.neutral77[layout.index(layout.left_hip)])
    origin = np.array((roots[0, 0], 0.0, roots[0, 2]))
    return Canonical(origin=origin, rotation=rotation_y(-angle))


def request_to_constraints(request, layout, model_fps):
    """Kimodo's inputs for a GenerationRequest.
    The canonical frame comes from the request's origin (the character on the first frame), or from the first
    key pose without one. Returns (constraints list for kimodo.constraints.load_constraints_lst, Canonical,
    Timing). Without key poses, the constraints list is empty (prompt only).
    Raises ValueError if there is neither key pose nor origin."""
    frames, rotations, roots = key_poses_to_kimodo(request, layout)
    timing = model_timing(request.start_frame, request.end_frame, frames, request.fps, model_fps)
    if request.origin is not None:
        origin_rotation, origin_root = _pose_arrays(request.origin, layout, "The origin")
        canonical = canonical_from(quat_to_kimodo(origin_rotation)[None], to_kimodo(origin_root)[None], layout)
    elif frames:
        canonical = canonical_from(rotations, roots, layout)
    else:
        raise ValueError("A request without key pose needs an origin.")
    if not frames:
        return [], canonical, timing
    rotations, roots = canonical.apply(rotations, roots)

    local = []
    for name in layout.names30:
        j = layout.index(name)
        parent = layout.parents77[j]
        q = rotations[:, j] if parent < 0 else quat.multiply(quat.conjugate(rotations[:, parent]), rotations[:, j])
        local.append(quat.to_axis_angle(q))
    local = np.stack(local, axis=1)  # (keys, 30, 3)
    constraints = [{
        "type": "fullbody",
        "frame_indices": timing.key_indices,
        "local_joints_rot": local.tolist(),
        "root_positions": roots.tolist(),
    }]
    return constraints, canonical, timing


def output_to_blender(global_rot_mats, root_positions, canonical, request, timing):
    """Kimodo's output -> (rotations from rest (frames, 77, 4), root positions (frames, 3)) in Blender
    conventions, on every Blender frame from request.start_frame to request.end_frame at request.fps.
    global_rot_mats: (T, 77, 3, 3); root_positions: (T, 3), in the canonical frame. timing: from
    request_to_constraints."""
    rotations = quat.from_matrix(global_rot_mats)
    rotations, positions = canonical.undo(rotations, np.asarray(root_positions, dtype=np.float64))
    frames = np.arange(request.start_frame, request.end_frame + 1)
    times = model_times(frames, timing.anchors, timing.anchor_indices)
    rotations, positions = resample(rotations, positions, times)
    return quat_to_blender(rotations), to_blender(positions)
