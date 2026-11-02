"""Unit tests for the quaternion helpers and the neutral skeleton (no Blender).

Run with Blender's Python (it has numpy), from the repository root:
    <blender>/5.2/python/bin/python.exe -I -m unittest discover -s tests/unit
"""
import json
import math
import os
import sys
import unittest

import numpy as np

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from core import quat  # noqa: E402
from core.skeleton import Joint, Skeleton  # noqa: E402


def random_quaternions(count, seed=0):
    return quat.normalize(np.random.default_rng(seed).normal(size=(count, 4)))


def same_rotation(a, b):
    """Largest angle (radians) between two arrays of rotations"""
    dots = np.abs(np.sum(quat.normalize(a) * quat.normalize(b), axis=-1))
    return float(np.max(2.0 * np.arccos(np.clip(dots, -1.0, 1.0))))


class TestQuat(unittest.TestCase):
    def test_multiply_composes_rotations(self):
        a, b = random_quaternions(50, 1), random_quaternions(50, 2)
        v = np.random.default_rng(3).normal(size=(50, 3))
        np.testing.assert_allclose(quat.rotate(quat.multiply(a, b), v), quat.rotate(a, quat.rotate(b, v)), atol=1e-12)
        np.testing.assert_allclose(quat.multiply(a, quat.conjugate(a)), np.tile((1.0, 0, 0, 0), (50, 1)), atol=1e-12)

    def test_matrix_round_trip(self):
        q = random_quaternions(200)
        m = quat.to_matrix(q)
        np.testing.assert_allclose(m @ np.swapaxes(m, -1, -2), np.tile(np.eye(3), (200, 1, 1)), atol=1e-12)
        self.assertLess(same_rotation(quat.from_matrix(m), q), 1e-7)
        # Close to 180 degrees, where the trace is -1
        flips = quat.normalize(np.array([[1e-9, 1.0, 0.0, 0.0], [0.0, 0.6, 0.8, 0.0], [1e-6, 0.0, 0.0, 1.0]]))
        self.assertLess(same_rotation(quat.from_matrix(quat.to_matrix(flips)), flips), 1e-7)

    def test_axis_angle_round_trip(self):
        q = random_quaternions(100)
        v = quat.to_axis_angle(q)
        self.assertTrue(np.all(np.linalg.norm(v, axis=-1) <= math.pi + 1e-12))
        self.assertLess(same_rotation(quat.from_axis_angle(v), q), 1e-7)
        np.testing.assert_allclose(quat.from_axis_angle(np.zeros(3)), (1.0, 0.0, 0.0, 0.0))
        np.testing.assert_allclose(quat.to_axis_angle((1.0, 0.0, 0.0, 0.0)), (0.0, 0.0, 0.0))

    def test_slerp(self):
        a = np.array((1.0, 0.0, 0.0, 0.0))
        b = np.array((math.cos(0.5), 0.0, 0.0, math.sin(0.5)))  # 1 radian around Z
        mid = quat.slerp(a, b, 0.25)
        np.testing.assert_allclose(mid, (math.cos(0.125), 0.0, 0.0, math.sin(0.125)), atol=1e-12)
        # Short way: -b is the same rotation
        np.testing.assert_allclose(quat.slerp(a, -b, 0.25), mid, atol=1e-12)
        ts = np.linspace(0.0, 1.0, 5)[:, None]
        np.testing.assert_allclose(quat.slerp(a, b, ts)[[0, -1]], [a, b], atol=1e-12)
        np.testing.assert_allclose(quat.slerp(a, a, 0.3), a, atol=1e-12)

    def test_make_continuous(self):
        q = random_quaternions(1)[0]
        frames = np.array([q, -q, q, -q, -q])
        fixed = quat.make_continuous(frames)
        np.testing.assert_allclose(fixed, np.tile(q, (5, 1)))
        # Several joints at once, frames on axis 0
        joints = np.stack([frames, -frames], axis=1)
        self.assertTrue(np.all(np.sum(np.diff(quat.make_continuous(joints), axis=0) ** 2, axis=-1) < 1e-20))


class TestSkeleton(unittest.TestCase):
    def skeleton(self):
        return Skeleton([Joint("Hips", None, (0, 0, 1), (0, 0, 1.1)),
                         Joint("Spine", "Hips", (0, 0, 1.1), (0, 0, 1.4), roll=0.5)], root="Hips")

    def test_round_trip(self):
        skeleton = self.skeleton()
        self.assertEqual(Skeleton.from_dict(json.loads(json.dumps(skeleton.to_dict()))), skeleton)
        self.assertEqual(skeleton.names, ["Hips", "Spine"])

    def test_checks(self):
        with self.assertRaisesRegex(ValueError, "listed before"):
            Skeleton([Joint("Spine", "Hips", (0, 0, 0), (0, 0, 1)), Joint("Hips", None, (0, 0, 0), (0, 0, 1))], "Hips")
        with self.assertRaisesRegex(ValueError, "twice"):
            Skeleton([Joint("Hips", None, (0, 0, 0), (0, 0, 1))] * 2, "Hips")
        with self.assertRaisesRegex(ValueError, "without parent"):
            Skeleton([Joint("Hips", None, (0, 0, 0), (0, 0, 1)), Joint("Spine", "Hips", (0, 0, 1), (0, 0, 2))], "Spine")
        with self.assertRaisesRegex(ValueError, "Not a skeleton"):
            Skeleton.from_dict({"joints": []})


if __name__ == "__main__":
    unittest.main()
