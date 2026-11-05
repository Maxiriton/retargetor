"""Interpolation between key poses: slerp of the rotations from rest, lerp of the root position. No bpy."""
import numpy as np

from core import quat


def key_arrays(request, joint_names):
    """(sorted key frames, rotations (keys, joints, 4), root positions (keys, 3)) of a GenerationRequest.
    Joints missing from a key pose stay at rest; a missing root position keeps the previous one (0 at first)."""
    frames = sorted(request.key_poses)
    rotations = np.tile((1.0, 0.0, 0.0, 0.0), (len(frames), len(joint_names), 1))
    roots = np.zeros((len(frames), 3))
    for k, frame in enumerate(frames):
        pose = request.key_poses[frame]
        for j, name in enumerate(joint_names):
            if name in pose.rotations:
                rotations[k, j] = pose.rotations[name]
        if pose.root_position is not None:
            roots[k] = pose.root_position
        elif k > 0:
            roots[k] = roots[k - 1]
    return frames, rotations, roots


def segments(request, joint_names):
    """Yield (first frame, rotations (frames, joints, 4), root positions (frames, 3)) for each segment between
    two key poses, covering request.start_frame to request.end_frame once. Before the first key pose and after
    the last one, the nearest key pose is held."""
    frames, rotations, roots = key_arrays(request, joint_names)
    if frames[0] > request.start_frame:
        count = frames[0] - request.start_frame
        yield request.start_frame, np.repeat(rotations[:1], count, 0), np.repeat(roots[:1], count, 0)
    for k in range(len(frames) - 1):
        a, b = frames[k], frames[k + 1]
        # The segment's own frames: a included, b excluded (it starts the next segment)
        t = (np.arange(a, b) - a) / (b - a)
        rot = quat.slerp(rotations[k][None], rotations[k + 1][None], t[:, None, None])
        root = roots[k][None] + t[:, None] * (roots[k + 1] - roots[k])[None]
        yield a, rot, root
    count = request.end_frame - frames[-1] + 1
    yield frames[-1], np.repeat(rotations[-1:], count, 0), np.repeat(roots[-1:], count, 0)
