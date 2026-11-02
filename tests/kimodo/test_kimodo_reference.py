"""The Kimodo conversions against Kimodo itself and the Phase 0 references. Run with the Kimodo venv's Python:

    <kimodo-venv>/Scripts/python.exe -I tests/kimodo/test_kimodo_reference.py <folder with phase0/out>

(tests/run_tests.py runs it when given --kimodo-python). No GPU: only Kimodo's skeleton and constraint code.
"""
import json
import math
import os
import sys
import unittest

import numpy as np

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO)

from backends.kimodo import convert, joints  # noqa: E402
from backends.kimodo.worker import KimodoHandler  # noqa: E402
from core import quat  # noqa: E402
from core.motion import GenerationRequest, Pose  # noqa: E402

SPIKES = os.environ.get("RETARGETOR_SPIKES", os.path.join(REPO, "spikes"))
PHASE0 = os.path.join(SPIKES, "phase0", "out")
# Kimodo frames of the Phase 0 round trip (Blender frames 80 and 135)
ROUNDTRIP_FRAMES = [79, 134]


def angles_deg(a, b):
    """Angles (degrees) between two arrays of rotations"""
    dots = np.abs(np.sum(quat.normalize(a) * quat.normalize(b), axis=-1))
    return np.degrees(2.0 * np.arccos(np.clip(dots, -1.0, 1.0)))


class TestKimodoReference(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.handler = KimodoHandler(joints.DEFAULT_MODEL)
        cls.layout = cls.handler._soma()
        cls.skeleton = cls.handler.skeleton()
        cls.npz = np.load(os.path.join(PHASE0, "fullbody_test.npz"))
        with open(os.path.join(PHASE0, "roundtrip_constraints.json")) as f:
            cls.reference = json.load(f)[0]
        with open(os.path.join(PHASE0, "soma_skeleton.json")) as f:
            cls.soma_json = json.load(f)

    def request_from_npz(self, fps=30.0):
        """The Phase 0 motion's poses on ROUNDTRIP_FRAMES as a request in Blender conventions"""
        layout = self.layout
        rot = self.npz["global_rot_mats"]
        pos = self.npz["posed_joints"]
        root = layout.index(layout.root)
        poses = {}
        for k in ROUNDTRIP_FRAMES:
            rotations = convert.quat_to_blender(quat.from_matrix(rot[k]))
            poses[k + 1] = Pose({n: tuple(rotations[j]) for j, n in enumerate(layout.names77)},
                                tuple(convert.to_blender(pos[k, root])))
        return GenerationRequest(ROUNDTRIP_FRAMES[0] + 1, ROUNDTRIP_FRAMES[-1] + 1, fps, poses)

    def test_skeleton(self):
        names = [j.name for j in self.skeleton.joints]
        self.assertEqual(names, self.soma_json["joints77"])
        parents = [j.parent for j in self.skeleton.joints]
        self.assertEqual(parents, self.soma_json["parents77"])
        self.assertEqual(self.skeleton.root, joints.ROOT_JOINT)
        self.assertEqual(self.layout.names30, self.soma_json["joints30"])
        for name in joints.JOINT_MAP.values():
            self.assertIn(name, names)

    def test_constraints_match_phase0(self):
        """Constraints built from Blender-convention poses = those Phase 0 rebuilt from the Blender armature"""
        request = self.request_from_npz()
        constraints, canonical, indices, count = convert.request_to_constraints(request, self.layout, 30.0)
        self.assertEqual((indices, count), ([0, 55], 56))
        ours = constraints[0]
        mine = quat.from_axis_angle(np.array(ours["local_joints_rot"]))
        theirs = quat.from_axis_angle(np.array(self.reference["local_joints_rot"]))
        # The canonical move only changes the root joint's rotation (index 0): compare the others directly
        self.assertLess(float(np.max(angles_deg(mine[:, 1:], theirs[:, 1:]))), 0.1)
        # Root rotation and positions, moved back out of the canonical frame
        undone_rot, undone_pos = canonical.undo(mine[:, 0], np.array(ours["root_positions"]))
        self.assertLess(float(np.max(angles_deg(undone_rot, theirs[:, 0]))), 0.1)
        np.testing.assert_allclose(undone_pos, self.reference["root_positions"], atol=1e-5)

    def test_kimodo_fk_of_the_constraints(self):
        """Kimodo's own FK of our constraints gives the Phase 0 joint positions, moved to the canonical frame,
        facing +Z (heading 0)"""
        from kimodo.constraints import load_constraints_lst
        from kimodo.motion_rep.feature_utils import compute_heading_angle
        from kimodo.skeleton import SOMASkeleton30
        import torch

        skel30 = SOMASkeleton30()
        request = self.request_from_npz()
        constraints, canonical, _i, _n = convert.request_to_constraints(request, self.layout, 30.0)
        constraint = load_constraints_lst(constraints, skel30)[0]
        positions = constraint.global_joints_positions.detach().cpu().numpy()  # (2, 30, 3)
        index30 = [self.layout.index(n) for n in self.layout.names30]
        expected = self.npz["posed_joints"][ROUNDTRIP_FRAMES][:, index30]
        expected = quat.rotate(canonical.rotation, expected - canonical.origin)
        # The hand end joints hang from the hand in the 30-joint skeleton, from the last finger bone in the
        # 77-joint one: their positions differ when the fingers are bent. Their rotations are checked above.
        bodies = [i for i, n in enumerate(self.layout.names30) if not n.endswith(("ThumbEnd", "MiddleEnd"))]
        self.assertEqual(len(bodies), 26)
        errors = np.linalg.norm(positions - expected, axis=-1)[:, bodies]
        self.assertLess(float(np.max(errors)), 1e-4)
        heading = compute_heading_angle(torch.tensor(positions[None]), skel30)[0, 0].item()
        self.assertAlmostEqual(heading, 0.0, places=5)
        self.assertGreater(abs(canonical.heading), 0.01, "the Phase 0 pose doesn't face +Z: the test turns it")

    def test_output_back_to_blender(self):
        """Kimodo's output, converted, gives back the Phase 0 global rotations and root positions"""
        request = self.request_from_npz()
        _cons, _canonical, indices, _count = convert.request_to_constraints(request, self.layout, 30.0)
        identity = convert.Canonical(origin=np.zeros(3), rotation=np.array((1.0, 0.0, 0.0, 0.0)))
        start, end = ROUNDTRIP_FRAMES
        rot = self.npz["global_rot_mats"][start:end + 1]
        root = self.npz["posed_joints"][start:end + 1, self.layout.index(self.layout.root)]
        rotations, positions = convert.output_to_blender(rot, root, identity, request, indices)
        self.assertEqual(rotations.shape, (end - start + 1, 77, 4))
        back = quat.from_matrix(quat.to_matrix(convert.quat_to_kimodo(rotations)))
        self.assertLess(float(np.max(angles_deg(back, quat.from_matrix(rot)))), 1e-4)
        np.testing.assert_allclose(convert.to_kimodo(positions), root, atol=1e-9)


if __name__ == "__main__":
    unittest.main(argv=sys.argv[:1])
