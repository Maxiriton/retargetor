"""Role detection on synthetic skeletons named like common rigs (tests/fixtures/humanoids.py). No bpy."""
import os
import sys
import unittest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
for path in (REPO, os.path.join(REPO, "tests", "fixtures")):
    if path not in sys.path:
        sys.path.insert(0, path)

import humanoids  # noqa: E402
from core import rig_detect, roles  # noqa: E402
from core.rig_detect import BoneInfo, detect, split_side  # noqa: E402


def bone_infos(bones):
    return [BoneInfo(name, parent, head, tail) for name, parent, head, tail in bones]


def found(detection):
    return {role: match.bone for role, match in detection.matches.items()}


class TestSides(unittest.TestCase):
    def test_conventions(self):
        cases = {
            "mixamorig1:LeftForeArm": ("L", "ForeArm"), "RightUpLeg": ("R", "UpLeg"), "upper_arm.L": ("L", "upper_arm"),
            "DEF-upper_arm.L.001": ("L", "upper_arm.001"), "hand_r": ("R", "hand"), "m_avg_L_Hip": ("L", "Hip"),
            "CC_Base_R_Upperarm": ("R", "Upperarm"), "J_Bip_C_Hips": ("", "Hips"), "J_Bip_L_LowerArm": ("L", "LowerArm"),
            "lShldrBend": ("L", "ShldrBend"), "L_armtop": ("L", "armtop"), "Bip01 L Forearm": ("L", "Forearm"),
            "spine.001": ("", "spine.001"), "Hips": ("", "Hips"), "lowerarm": ("", "lowerarm"), "arm_left": ("L", "arm"),
        }
        for name, side in cases.items():
            self.assertEqual(split_side(name), side, name)


class TestSchemes(unittest.TestCase):
    def check_scheme(self, scheme, prefix=""):
        detection = detect(bone_infos(humanoids.skeleton(scheme, prefix)))
        self.assertEqual(found(detection), humanoids.expected(scheme, prefix), scheme)
        self.assertEqual(detection.missing, [], scheme)
        return detection

    def test_mixamo(self):
        for prefix in ("", "mixamorig:", "mixamorig1:"):
            self.check_scheme("mixamo", prefix)

    def test_other_conventions(self):
        for scheme in ("ue5", "smpl", "vrm", "daz", "cc"):
            detection = self.check_scheme(scheme)
            self.assertTrue(all(match.how == rig_detect.BY_NAME for role, match in detection.matches.items()
                                if roles.get_role(role).group != roles.SPINE), scheme)

    def test_y_up_armature(self):
        """An FBX import: bones Y-up in the armature's space (the object turned 90 degrees)"""
        bones = [(name, parent, (h[0], h[2], -h[1]), (t[0], t[2], -t[1]))
                 for name, parent, h, t in humanoids.skeleton("ue5")]
        self.assertEqual(found(detect(bone_infos(bones))), humanoids.expected("ue5"))

    def test_unnamed_forearm_filled_from_hierarchy(self):
        detection = self.check_scheme("blender")
        self.assertEqual(detection.matches["forearm.L"].how, rig_detect.BY_HIERARCHY)
        self.assertTrue(any("Bone.L" in note for note in detection.notes))

    def test_profile_reads_and_writes_the_bones(self):
        profile = detect(bone_infos(humanoids.skeleton("mixamo"))).profile()
        hips = profile.binding("hips")
        self.assertEqual((hips.read_bone, hips.write_bone, hips.use_translation), ("Hips", "Hips", True))
        self.assertEqual(profile.binding("forearm.L").offset_mode, "ROLL")
        self.assertEqual([b.role for b in profile.roles], [r.id for r in roles.ROLES if profile.binding(r.id)])


class TestBodyAxes(unittest.TestCase):
    def test_frames(self):
        # (up, left) -> (left, back, up)
        self.assertEqual(rig_detect.body_axes((0.02, 0.1, 0.7), (0.35, 0.03, -0.02)),
                         ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)))   # Blender's convention, a bent spine
        self.assertEqual(rig_detect.body_axes((0.0, 0.7, 0.0), (0.35, 0.0, 0.0)),
                         ((1.0, 0.0, 0.0), (0.0, 0.0, -1.0), (0.0, 1.0, 0.0)))  # FBX: bones Y-up
        self.assertEqual(rig_detect.body_axes((0.0, 0.0, 0.7), (-0.35, 0.0, 0.0)),
                         ((-1.0, 0.0, 0.0), (0.0, -1.0, 0.0), (0.0, 0.0, 1.0)))  # facing +Y (SMPL)
        with self.assertRaises(ValueError):
            rig_detect.body_axes((0.0, 0.0, 0.0), (1.0, 0.0, 0.0))


class TestIncomplete(unittest.TestCase):
    def test_missing_arm_is_reported(self):
        bones = [b for b in humanoids.skeleton("mixamo") if "Right" not in b[0] or "Leg" in b[0] or "Foot" in b[0]
                 or "Toe" in b[0]]
        detection = detect(bone_infos(bones))
        self.assertEqual(detection.missing, ["upper_arm.R", "forearm.R", "hand.R"])
        self.assertFalse(detection.complete)

    def test_nothing_humanoid(self):
        detection = detect(bone_infos([("Bone", None, (0, 0, 0), (0, 0, 1)), ("Bone.001", "Bone", (0, 0, 1), (0, 0, 2))]))
        self.assertEqual(detection.matches, {})
        self.assertIn("hips", detection.missing)

    def test_swapped_sides_noted(self):
        bones = [(name, parent, (-h[0], h[1], h[2]), (-t[0], t[1], t[2]))
                 for name, parent, h, t in humanoids.skeleton("mixamo")]
        detection = detect(bone_infos(bones))
        self.assertEqual(sum("swapped" in note for note in detection.notes), 1)

    def test_facing_plus_y_is_not_swapped(self):
        """SMPL faces +Y: turned half a turn, its sides are right"""
        bones = [(name, parent, (-h[0], -h[1], h[2]), (-t[0], -t[1], t[2]))
                 for name, parent, h, t in humanoids.skeleton("smpl")]
        detection = detect(bone_infos(bones))
        self.assertEqual(found(detection), humanoids.expected("smpl"))
        self.assertFalse(any("swapped" in note for note in detection.notes))

    def test_missing_required(self):
        self.assertEqual(roles.missing_required([]), ["hips", "spine", "head", "upper_arm.L", "upper_arm.R",
                                                      "forearm.L", "forearm.R", "hand.L", "hand.R", "thigh.L",
                                                      "thigh.R", "shin.L", "shin.R", "foot.L", "foot.R"])
        self.assertNotIn("spine", roles.missing_required(["chest"]))


if __name__ == "__main__":
    unittest.main()
