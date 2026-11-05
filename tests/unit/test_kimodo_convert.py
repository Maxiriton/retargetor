"""Kimodo conversions that don't need Kimodo: axes, frame rates, canonical frame and heading. No Blender.

The comparisons with Kimodo's own outputs (Phase 0 references) are in tests/kimodo/, run with the Kimodo venv.
"""
import math
import os
import sys
import unittest

import numpy as np

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from backends.kimodo import convert  # noqa: E402
from core import quat  # noqa: E402
from core.motion import GenerationRequest, Pose  # noqa: E402


def small_layout():
    """A tiny SOMA-like skeleton: hips, two legs and a spine (Kimodo axes, facing +Z, right side at -X)"""
    names = ["Hips", "RightLeg", "LeftLeg", "Spine1", "RightShin"]
    parents = [-1, 0, 0, 0, 1]
    neutral = np.array([(0, 0, 0), (-0.1, -0.05, 0), (0.1, -0.05, 0), (0, 0.1, 0), (-0.1, -0.5, 0)], dtype=float)
    return convert.SomaLayout(names77=names, parents77=parents, names30=["Hips", "RightLeg", "LeftLeg", "Spine1"],
                              root="Hips", right_hip="RightLeg", left_hip="LeftLeg", neutral77=neutral)


def turn_z(angle):
    """Rotation around Blender's vertical axis"""
    return np.array((math.cos(angle / 2), 0.0, 0.0, math.sin(angle / 2)))


def make_request(turn=0.0, offset=(0.0, 0.0), fps=30.0, frames=(1, 31, 61)):
    """Key poses walking along -Y (Blender), the whole thing turned by `turn` around Z and moved by `offset`"""
    rng = np.random.default_rng(4)
    poses = {}
    for k, frame in enumerate(frames):
        local = quat.normalize(np.array([1.0, 0, 0, 0]) + 0.2 * rng.normal(size=(5, 4)))
        root = np.array((0.0, -0.5 * k, 0.95))
        rotations = quat.multiply(turn_z(turn), local)
        root = quat.rotate(turn_z(turn), root) + np.array((offset[0], offset[1], 0.0))
        names = small_layout().names77
        poses[frame] = Pose({n: tuple(rotations[j]) for j, n in enumerate(names)}, tuple(root))
    return GenerationRequest(frames[0], frames[-1], fps, poses)


class TestAxes(unittest.TestCase):
    def test_axes(self):
        np.testing.assert_allclose(convert.to_kimodo((0.0, 1.0, 0.0)), (0.0, 0.0, -1.0))
        np.testing.assert_allclose(convert.to_kimodo((0.0, 0.0, 1.0)), (0.0, 1.0, 0.0))
        q = quat.normalize(np.random.default_rng(0).normal(size=(10, 4)))
        np.testing.assert_allclose(convert.quat_to_blender(convert.quat_to_kimodo(q)), q)
        # The same rotation in both bases: rotating a converted vector = converting the rotated vector
        v = np.random.default_rng(1).normal(size=(10, 3))
        np.testing.assert_allclose(quat.rotate(convert.quat_to_kimodo(q), convert.to_kimodo(v)),
                                   convert.to_kimodo(quat.rotate(q, v)), atol=1e-12)


class TestFrameRates(unittest.TestCase):
    def test_key_indices(self):
        self.assertEqual(convert.model_key_indices([1, 61, 120], 30.0, 30.0), [0, 60, 119])
        # 24 fps: same times as the 30 fps key poses above
        self.assertEqual(convert.model_key_indices([1, 49, 96], 24.0, 30.0), [0, 60, 119])
        # 60 fps: frame 2 is 1/60 s after frame 1, half a model frame: too close
        with self.assertRaisesRegex(ValueError, "too close"):
            convert.model_key_indices([1, 2, 30], 60.0, 30.0)

    def test_times_hit_the_keys(self):
        keys, indices = [1, 49, 96], [0, 60, 119]
        times = convert.model_times(np.arange(1, 97), keys, indices)
        self.assertEqual([times[0], times[48], times[95]], [0.0, 60.0, 119.0])
        self.assertAlmostEqual(times[1], 1.25)
        self.assertTrue(np.all(np.diff(times) > 0))

    def test_timing_of_a_custom_range(self):
        # Key poses inside a longer range: counted from the range's start, the range's ends anchor the time map
        timing = convert.model_timing(1, 150, [31, 91], 30.0, 30.0)
        self.assertEqual((timing.key_indices, timing.count), ([30, 90], 150))
        self.assertEqual((timing.anchors, timing.anchor_indices), ([1, 31, 91, 150], [0, 30, 90, 149]))
        # No key pose: the range alone (24 fps, 4 s -> 120 model frames)
        timing = convert.model_timing(10, 105, [], 24.0, 30.0)
        self.assertEqual((timing.key_indices, timing.count, timing.anchors), ([], 120, [10, 105]))
        # A key pose on the last frame keeps its own model frame
        timing = convert.model_timing(1, 96, [1, 96], 24.0, 30.0)
        self.assertEqual((timing.key_indices, timing.count, timing.anchor_indices), ([0, 119], 120, [0, 119]))

    def test_resample(self):
        rotations = np.stack([np.tile(turn_z(0.1 * i), (2, 1)) for i in range(5)])
        positions = np.arange(15, dtype=float).reshape(5, 3)
        rot, pos = convert.resample(rotations, positions, np.array([0.0, 1.5, 4.0]))
        np.testing.assert_allclose(rot[1, 0], turn_z(0.15), atol=1e-12)
        np.testing.assert_allclose(pos, [positions[0], (positions[1] + positions[2]) / 2, positions[4]])


class TestCanonical(unittest.TestCase):
    def test_heading(self):
        layout = small_layout()
        right, left = layout.neutral77[1], layout.neutral77[2]
        self.assertAlmostEqual(convert.heading_angle((1.0, 0, 0, 0), right, left), 0.0)
        for angle in (0.5, -2.0, 3.0):
            self.assertAlmostEqual(convert.heading_angle(convert.rotation_y(angle), right, left), angle)

    def test_apply_undo(self):
        layout = small_layout()
        _frames, rotations, roots = convert.key_poses_to_kimodo(make_request(turn=1.2, offset=(3.0, -2.0)), layout)
        canonical = convert.canonical_from(rotations, roots, layout)
        rot, pos = canonical.apply(rotations, roots)
        np.testing.assert_allclose(pos[0, [0, 2]], (0.0, 0.0), atol=1e-12)
        self.assertAlmostEqual(pos[0, 1], roots[0, 1])  # the height is kept
        self.assertAlmostEqual(convert.heading_angle(rot[0, 0], layout.neutral77[1], layout.neutral77[2]), 0.0)
        back_rot, back_pos = canonical.undo(rot, pos)
        np.testing.assert_allclose(back_pos, roots, atol=1e-12)
        self.assertLess(np.max(np.abs(np.abs(np.sum(back_rot * rotations, -1)) - 1.0)), 1e-12)

    def test_turned_character_gives_the_same_constraints(self):
        """Heading canonicalization: the same key poses turned 90 degrees and moved elsewhere give the same
        model inputs, so the model generates the same motion (turned back afterwards)."""
        layout = small_layout()
        reference, _c, timing = convert.request_to_constraints(make_request(), layout, 30.0)
        turned, canonical, _t = convert.request_to_constraints(
            make_request(turn=math.pi / 2, offset=(4.0, 1.0)), layout, 30.0)
        self.assertEqual((timing.key_indices, timing.count), ([0, 30, 60], 61))
        a, b = reference[0], turned[0]
        np.testing.assert_allclose(b["root_positions"], a["root_positions"], atol=1e-9)
        qa = quat.from_axis_angle(np.array(a["local_joints_rot"]))
        qb = quat.from_axis_angle(np.array(b["local_joints_rot"]))
        self.assertLess(np.max(1.0 - np.abs(np.sum(qa * qb, -1))), 1e-12)
        self.assertAlmostEqual(canonical.heading - _c.heading, math.pi / 2)

    def test_output_comes_back_turned(self):
        """A model output in the canonical frame goes back to the character's place and heading"""
        layout = small_layout()
        request = make_request(turn=math.pi / 2, offset=(4.0, 1.0))
        _cons, canonical, timing = convert.request_to_constraints(request, layout, 30.0)
        indices, count = timing.key_indices, timing.count
        frames, rotations, roots = convert.key_poses_to_kimodo(request, layout)
        rot_c, pos_c = canonical.apply(rotations, roots)
        # A fake model output holding the canonical key poses on their frames
        out_rot = np.tile(quat.to_matrix(rot_c[0]), (count, 1, 1, 1))
        out_pos = np.tile(pos_c[0], (count, 1))
        for k, index in enumerate(indices):
            out_rot[index] = quat.to_matrix(rot_c[k])
            out_pos[index] = pos_c[k]
        rot_b, pos_b = convert.output_to_blender(out_rot, out_pos, canonical, request, timing)
        self.assertEqual(len(rot_b), 61)
        for frame in frames:
            pose = request.key_poses[frame]
            np.testing.assert_allclose(pos_b[frame - 1], pose.root_position, atol=1e-9)
            expected = np.array([pose.rotations[n] for n in layout.names77])
            self.assertLess(np.max(1.0 - np.abs(np.sum(rot_b[frame - 1] * expected, -1))), 1e-12)


    def test_partial_poses(self):
        """Key poses keying a hand alone become end-effector constraints; whole ones, or keying the spine, the
        whole body"""
        layout = small_layout()
        effectors = {"end-effector": {"Hips"}, "right-foot": {"RightLeg", "RightShin"}}
        self.assertIsNone(convert.end_effectors(None, effectors))
        self.assertEqual(convert.end_effectors(["RightShin", "RightLeg"], effectors), ["right-foot"])
        self.assertEqual(convert.end_effectors(["Hips", "RightShin"], effectors), ["end-effector", "right-foot"])
        self.assertIsNone(convert.end_effectors(["Spine1", "RightShin"], effectors))
        request = make_request(frames=(1, 31, 61, 91))
        request.key_poses[31].constrained_joints = ["RightShin"]
        request.key_poses[61].constrained_joints = ["Spine1"]
        request.key_poses[91].constrained_joints = ["RightLeg", "Hips"]
        constraints, _canonical, timing = convert.request_to_constraints(request, layout, 30.0, effectors)
        self.assertEqual([(c["type"], c["frame_indices"], c.get("joint_names")) for c in constraints],
                         [("fullbody", [0, 60], None), ("end-effector", [90], ["Hips"]),
                          ("right-foot", [30, 90], None)])
        _full, _hips, partial = constraints
        reference, _c, _t = convert.request_to_constraints(request, layout, 30.0)
        self.assertEqual(len(reference), 1)  # without effectors, every key pose is whole
        np.testing.assert_allclose(partial["root_positions"], np.array(reference[0]["root_positions"])[[1, 3]])

    def test_origin_places_the_motion(self):
        """Without key pose, the canonical frame comes from the origin: the character's place and heading"""
        layout = small_layout()
        posed = make_request(turn=1.0, offset=(2.0, 3.0))
        origin = posed.key_poses[1]
        request = GenerationRequest(1, 90, 30.0, {}, prompt="walk", origin=origin)
        constraints, canonical, timing = convert.request_to_constraints(request, layout, 30.0)
        self.assertEqual((constraints, timing.count), ([], 90))
        _cons, from_key, _t = convert.request_to_constraints(posed, layout, 30.0)
        np.testing.assert_allclose(canonical.origin, from_key.origin, atol=1e-12)
        self.assertAlmostEqual(canonical.heading, from_key.heading)
        # A motion standing at the canonical origin, facing +Z, comes back where the character stands
        count = timing.count
        rot_b, pos_b = convert.output_to_blender(np.tile(np.eye(3), (count, 5, 1, 1)),
                                                 np.tile((0.0, 0.95, 0.0), (count, 1)), canonical, request, timing)
        np.testing.assert_allclose(pos_b[0, :2], origin.root_position[:2], atol=1e-9)
        with self.assertRaisesRegex(ValueError, "origin"):
            convert.request_to_constraints(GenerationRequest(1, 90, 30.0), layout, 30.0)


if __name__ == "__main__":
    unittest.main()
