"""The interpolation backend, through its real worker process. No Blender.

Run with Blender's Python (tests/run_tests.py does it), from the repository root:
    <blender>/5.2/python/bin/python.exe -I -m unittest discover -s tests/unit
"""
import math
import os
import sys
import unittest

import numpy as np

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from backends import process, protocol  # noqa: E402
from backends.interpolate.generate import segments  # noqa: E402
from backends.interpolate.skeleton import skeleton  # noqa: E402
from core import roles  # noqa: E402
from core.motion import GenerationRequest, Motion, Pose  # noqa: E402
from core.skeleton import Skeleton  # noqa: E402

WORKER = os.path.join(REPO, "backends", "interpolate", "worker.py")


def turn(angle):
    """Rotation around Z"""
    return (math.cos(angle / 2), 0.0, 0.0, math.sin(angle / 2))


def make_request(start=1, end=21):
    keys = {5: Pose({"head": turn(0.0)}, (0.0, 0.0, 1.0)),
            15: Pose({"head": turn(1.0)}, (0.0, -1.0, 1.0)),
            19: Pose({"head": turn(0.5)}, (0.0, -1.0, 1.0))}
    return GenerationRequest(start, end, 24.0, keys, seed=None)


class TestInterpolation(unittest.TestCase):
    def test_skeleton_has_one_joint_per_role(self):
        sk = skeleton()
        self.assertEqual(sorted(sk.names), sorted(r.id for r in roles.ROLES))
        self.assertEqual(sk.root, "hips")
        left, right = sk.joint("hand.L"), sk.joint("hand.R")
        self.assertEqual((left.head[0], left.parent), (-right.head[0], "forearm.L"))
        self.assertEqual(right.parent, "forearm.R")

    def test_segments(self):
        names = skeleton().names
        request = make_request()
        chunks = list(segments(request, names))
        frames = [first + i for first, rot, _ in chunks for i in range(len(rot))]
        self.assertEqual(frames, list(range(1, 22)))
        poses = {f: (rot[i], root[i]) for first, rot, root in chunks for i, f in enumerate(range(first, first + len(rot)))}
        head = names.index("head")
        np.testing.assert_allclose(poses[15][0][head], turn(1.0), atol=1e-12)
        np.testing.assert_allclose(poses[10][0][head], turn(0.5), atol=1e-12)  # halfway between 5 and 15
        np.testing.assert_allclose(poses[10][1], (0.0, -0.5, 1.0), atol=1e-12)
        np.testing.assert_allclose(poses[1][0][head], turn(0.0), atol=1e-12)  # held before the first key
        np.testing.assert_allclose(poses[21][0][head], turn(0.5), atol=1e-12)  # held after the last key
        np.testing.assert_allclose(poses[10][0][names.index("hand.L")], (1.0, 0.0, 0.0, 0.0))  # not in the poses

    def test_context(self):
        """The motion around the range is interpolated from, never returned"""
        names = skeleton().names
        before = Motion(24.0, 3, [Pose({"head": turn(0.3)}, (0.0, 0.0, 1.0)), Pose({"head": turn(0.0)}, (0.0, 0.0, 1.0))])
        after = Motion(24.0, 16, [Pose({"head": turn(1.1)}, (0.0, -1.1, 1.0))])
        request = GenerationRequest(5, 15, 24.0, {}, context_before=before, context_after=after)
        chunks = list(segments(request, names))
        frames = [first + i for first, rot, _ in chunks for i in range(len(rot))]
        self.assertEqual(frames, list(range(5, 16)))
        poses = {f: (rot[i], root[i]) for first, rot, root in chunks for i, f in enumerate(range(first, first + len(rot)))}
        head = names.index("head")
        # Halfway from frame 4 (the last one before) to frame 16 (the first one after)
        np.testing.assert_allclose(poses[10][0][head], turn(0.55), atol=1e-12)
        np.testing.assert_allclose(poses[10][1], (0.0, -0.55, 1.0), atol=1e-12)

    def test_worker(self):
        worker = process.Worker([sys.executable, "-I", "-u", WORKER])
        try:
            job = worker.wait(worker.submit("skeleton"), timeout=30)
            self.assertTrue(job.finished_ok, job.error)
            names = Skeleton.from_dict(job.result).names
            job = worker.wait(worker.submit("generate", request=make_request().to_dict()), timeout=30)
            self.assertTrue(job.finished_ok, job.error)
            self.assertEqual(len(job.frames), 4, "one chunk per segment")
            motion = protocol.motion_from_frames(job.frames, names)
            self.assertEqual((motion.start_frame, motion.end_frame, motion.fps), (1, 21, 24.0))
            np.testing.assert_allclose(motion.pose_at(10).rotations["head"], turn(0.5), atol=1e-6)
        finally:
            worker.stop()


if __name__ == "__main__":
    unittest.main()
