"""Unit tests for the parts of the core that don't need Blender.

Run from the repository root with Blender's Python (tests/run_tests.py does it), or any Python 3.11+ with numpy:
    <blender>/5.2/python/bin/python.exe -I -m unittest discover -s tests/unit
"""
import json
import os
import sys
import unittest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from backends.kimodo.joints import JOINT_MAP  # noqa: E402
from core import motion, profile, roles  # noqa: E402
from core.retarget.pairs import BonePair, target_map  # noqa: E402

PRESETS = os.path.join(REPO, "presets")


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class TestPairs(unittest.TestCase):
    def test_target_map_skips_incomplete_pairs(self):
        pairs = [BonePair("a", "A"), BonePair("b", ""), BonePair("", "C")]
        self.assertEqual(list(target_map(pairs)), ["A"])

    def test_duplicate_targets_raise(self):
        with self.assertRaisesRegex(ValueError, "same target bone: A"):
            target_map([BonePair("a", "A"), BonePair("b", "A")])

    def test_invalid_values_raise(self):
        with self.assertRaises(ValueError):
            BonePair("a", "A", offset_mode="TWIST")
        with self.assertRaises(ValueError):
            BonePair("a", "A", correction=(1.0, 0.0, 0.0))


class TestRoles(unittest.TestCase):
    def test_default_offset_modes(self):
        # Phase 1 finding: limbs copy the direction (ROLL), the spine copies the rotation from rest
        for role in roles.ROLES:
            expected = "REST_OFFSET" if role.group == roles.SPINE else "ROLL"
            self.assertEqual(role.default_offset_mode, expected, role.id)

    def test_only_hips_carry_translation_by_default(self):
        self.assertEqual([r.id for r in roles.ROLES if r.default_use_translation], ["hips"])

    def test_sides_are_symmetric(self):
        ids = {r.id for r in roles.ROLES}
        for role_id in ids:
            if role_id.endswith(".L"):
                self.assertIn(role_id[:-1] + "R", ids)

    def test_unknown_role(self):
        with self.assertRaisesRegex(KeyError, "Unknown humanoid role"):
            roles.get_role("tail")


class TestProfile(unittest.TestCase):
    def setUp(self):
        self.rigify = profile.RigProfile.from_dict(load_json(os.path.join(PRESETS, "rigify_human.json")))
        self.soma = dict(JOINT_MAP)

    def test_binding_defaults_come_from_the_role(self):
        b = profile.RoleBinding("upper_arm.L", read_bone="x")
        self.assertEqual((b.offset_mode, b.use_translation), ("ROLL", False))
        b = profile.RoleBinding("hips")
        self.assertEqual((b.offset_mode, b.use_translation), ("REST_OFFSET", True))

    def test_round_trip(self):
        self.rigify.binding("hand.L").corrections["test"] = (0.0, 1.0, 0.0, 0.0)
        again = profile.RigProfile.from_dict(json.loads(json.dumps(self.rigify.to_dict())))
        self.assertEqual(again, self.rigify)

    def test_wrong_format(self):
        with self.assertRaisesRegex(ValueError, "Not a rig profile"):
            profile.RigProfile.from_dict([{"src_name": "a"}])
        with self.assertRaisesRegex(ValueError, "Unknown humanoid role"):
            profile.RigProfile.from_dict({"format": profile.PROFILE_FORMAT, "roles": [{"role": "tail"}]})
        with self.assertRaisesRegex(ValueError, "listed twice"):
            profile.RigProfile.from_dict({"format": profile.PROFILE_FORMAT,
                                          "roles": [{"role": "head"}, {"role": "head"}]})

    def test_compose_to_model_reads_every_role(self):
        pairs = profile.compose(self.rigify, self.soma, profile.TO_MODEL)
        by_source = {p.source: p for p in pairs}
        self.assertEqual(len(pairs), 23)
        self.assertEqual(by_source["ORG-upper_arm.L"].target, "LeftArm")
        self.assertEqual(by_source["ORG-upper_arm.L"].offset_mode, "ROLL")
        self.assertEqual(by_source["ORG-spine.001"].offset_mode, "REST_OFFSET")
        self.assertEqual([p.source for p in pairs if p.use_translation], ["ORG-spine"])

    def test_compose_from_model_writes_only_controls(self):
        self.rigify.binding("hand.L").corrections["soma_test"] = (0.0, 0.0, 1.0, 0.0)
        pairs = profile.compose(self.rigify, self.soma, profile.FROM_MODEL, backend="soma_test")
        by_target = {p.target: p for p in pairs}
        # Spine1, Spine2 and Neck2 have no control to write on a Rigify rig
        self.assertEqual(len(pairs), 20)
        self.assertEqual(by_target["torso"].source, "Hips")
        self.assertTrue(by_target["torso"].use_translation)
        # The model's hips match the rig's ORG-spine, not the torso control: the translation pivots on it
        self.assertEqual(by_target["torso"].pivot, "ORG-spine")
        self.assertEqual(by_target["hand_fk.L"].pivot, "")
        self.assertEqual(by_target["chest"].source, "Chest")
        self.assertEqual(by_target["hand_fk.L"].correction, (0.0, 0.0, 1.0, 0.0))
        self.assertIsNone(by_target["hand_fk.R"].correction)
        target_map(pairs)  # no duplicates

    def test_compose_skips_unknown_roles(self):
        pairs = profile.compose(self.rigify, {"head": "Head"}, profile.FROM_MODEL)
        self.assertEqual(pairs, [BonePair("Head", "head", "REST_OFFSET", False)])

    def test_rigify_limbs(self):
        self.assertEqual(len(self.rigify.limbs), 4)
        leg = next(limb for limb in self.rigify.limbs if limb.name == "leg.L")
        self.assertEqual((leg.switch_bone, leg.switch_property, leg.fk_value), ("thigh_parent.L", "IK_FK", 1.0))
        self.assertEqual([p.fk_control for p in leg.controls], ["thigh_fk.L", "shin_fk.L", "foot_fk.L", "toe_fk.L"])


class TestMotion(unittest.TestCase):
    def test_round_trip(self):
        pose = motion.Pose({"a": (1.0, 0.0, 0.0, 0.0)}, (0.0, 1.0, 0.9), constrained_joints=["a"])
        request = motion.GenerationRequest(1, 120, 30.0, {1: pose, 61: motion.Pose({"a": (0.0, 1.0, 0.0, 0.0)})},
                                           prompt="walk", seed=1, origin=pose)
        again = motion.GenerationRequest.from_dict(json.loads(json.dumps(request.to_dict())))
        self.assertEqual(again, request)
        self.assertAlmostEqual(request.duration, 4.0)

        clip = motion.Motion(30.0, 10, [pose, pose])
        self.assertEqual(motion.Motion.from_dict(json.loads(json.dumps(clip.to_dict()))), clip)
        self.assertEqual((clip.end_frame, list(clip.frames)), (11, [10, 11]))
        with self.assertRaises(KeyError):
            clip.pose_at(12)

    def test_backend_range(self):
        from backends.base import Backend, Capabilities

        class Prompted(Backend):
            label = "Prompted"
            capabilities = Capabilities(max_duration=10.0, min_key_poses=0)

        backend = Prompted()
        self.assertEqual(backend.range_problem(1, 300, 30.0, 0), "")
        self.assertIn("at most 10 s", backend.range_problem(1, 301, 30.0, 3))
        self.assertIn("at least 2 key poses", Backend().range_problem(1, 30, 30.0, 1))
        with self.assertRaisesRegex(ValueError, "at most"):
            backend.check_request(motion.GenerationRequest(1, 400, 30.0))

    def test_request_checks(self):
        with self.assertRaisesRegex(ValueError, "outside the range"):
            motion.GenerationRequest(1, 10, 30.0, {11: motion.Pose()})
        with self.assertRaises(ValueError):
            motion.GenerationRequest(10, 1, 30.0)
        with self.assertRaises(ValueError):
            motion.Pose.from_dict({"rotations": {"a": [1.0, 0.0]}})


if __name__ == "__main__":
    unittest.main()
