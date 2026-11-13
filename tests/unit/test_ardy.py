"""The ARDY backend's parts that don't need ARDY: its checkpoints, joint maps and window constraints. No Blender.

ARDY itself is tested in tests/blender/test_generate_ardy.py (ARDY installed by the add-on, a CUDA GPU).
"""
import os
import sys
import unittest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from backends.ardy import install, models  # noqa: E402
from backends.ardy.worker import window_constraints  # noqa: E402
from backends.setup.spec import Gpu, Machine  # noqa: E402
from core.roles import ROLES_BY_ID  # noqa: E402

# ARDY's skeletons (ardy/skeleton/definitions.py at the pinned commit)
CORE_JOINTS = ["Hips", "Spine", "Spine1", "Spine2", "Spine3", "Neck", "Head", "RightShoulder", "RightArm",
               "RightForeArm", "RightHand", "RightHandEnd", "RightHandThumb1", "LeftShoulder", "LeftArm",
               "LeftForeArm", "LeftHand", "LeftHandEnd", "LeftHandThumb1", "RightUpLeg", "RightLeg", "RightFoot",
               "RightToeBase", "LeftUpLeg", "LeftLeg", "LeftFoot", "LeftToeBase"]
SOMA30_JOINTS = ["Hips", "Spine1", "Spine2", "Chest", "Neck1", "Neck2", "Head", "Jaw", "LeftEye", "RightEye",
                 "LeftShoulder", "LeftArm", "LeftForeArm", "LeftHand", "LeftHandThumbEnd", "LeftHandMiddleEnd",
                 "RightShoulder", "RightArm", "RightForeArm", "RightHand", "RightHandThumbEnd", "RightHandMiddleEnd",
                 "LeftLeg", "LeftShin", "LeftFoot", "LeftToeBase", "RightLeg", "RightShin", "RightFoot",
                 "RightToeBase"]


class TestCheckpoints(unittest.TestCase):
    def test_joint_maps(self):
        for name, joints in ((models.CHECKPOINTS["ARDY-Core-RP-20FPS-Horizon40"], CORE_JOINTS),
                             (models.CHECKPOINTS["ARDY-SOMA-RP-30FPS-Horizon60"], SOMA30_JOINTS)):
            joint_map = name.joint_map
            self.assertTrue(set(joint_map) <= set(ROLES_BY_ID), set(joint_map) - set(ROLES_BY_ID))
            self.assertTrue(set(joint_map.values()) <= set(joints), set(joint_map.values()) - set(joints))
            self.assertEqual(len(set(joint_map.values())), len(joint_map))
            for kind, chain in name.end_effectors.items():
                self.assertTrue(chain <= set(joints), (kind, chain - set(joints)))
        # Core's "Leg" is the shin, SOMA's the thigh
        self.assertEqual(models.checkpoint("ARDY-Core-RP-20FPS-Horizon40").joint_map["shin.L"], "LeftLeg")
        self.assertEqual(models.checkpoint("ARDY-SOMA-RP-30FPS-Horizon60").joint_map["thigh.L"], "LeftLeg")

    def test_windows(self):
        soma = models.checkpoint("ARDY-SOMA-RP-30FPS-Horizon60")
        core = models.checkpoint("ARDY-Core-RP-20FPS-Horizon40")
        self.assertEqual((soma.history_frames, soma.window_frames), (60, 300))
        self.assertEqual((core.history_frames, core.window_frames), (40, 200))
        self.assertEqual(models.checkpoint("unknown"), soma)

    def test_requirements(self):
        machine = Machine("windows", "x86_64", (Gpu("RTX 3090", 24576, (8, 6)),), cpp_compiler=True, git=True)
        req = install.requirements(machine, "ARDY-Core-RP-20FPS-Horizon40")
        self.assertEqual([w.repo_id for w in req.weights][0], "nvidia/ARDY-Core-RP-20FPS-Horizon40")
        self.assertEqual(req.packages[1].env, ())
        self.assertIn("cu126", req.packages[0].index_url)
        # The 8-bit text encoder by default: one repository, not gated, bitsandbytes imported, 9.5 GB of video memory
        self.assertEqual([w.repo_id for w in req.weights][1:], ["voxta/Llama-3-8B-LLM2Vec-ARDY-INT8"])
        self.assertFalse(any(w.gated for w in req.weights))
        self.assertTrue(req.weights[1].revision)
        self.assertIn("bitsandbytes", req.imports)
        self.assertEqual(req.min_vram_gb, 9.5)
        # bitsandbytes in a step of its own, keeping PyTorch's build
        self.assertEqual(req.packages[2].requirements[0], "bitsandbytes==0.50.2")
        self.assertIn("torch==2.7.1", req.packages[2].requirements)
        # The full one: Meta's repository, its weights only (the tokenizer comes from LLM2Vec's)
        full = install.requirements(machine, "ARDY-Core-RP-20FPS-Horizon40", "FULL")
        llama = [w for w in full.weights if w.gated]
        self.assertEqual([w.repo_id for w in llama], ["meta-llama/Meta-Llama-3-8B-Instruct"])
        self.assertNotIn("tokenizer.json", llama[0].required_files)
        self.assertEqual(len(full.weights), 4)
        self.assertNotIn("bitsandbytes", full.imports)
        self.assertEqual(full.min_vram_gb, 16.5)
        nf4 = install.requirements(machine, "ARDY-Core-RP-20FPS-Horizon40", "NF4")
        self.assertEqual(nf4.weights[1].repo_id, "voxta/Llama-3-8B-LLM2Vec-ARDY-NF4")
        self.assertEqual(models.text_encoder("unknown"), models.TEXT_ENCODERS["INT8"])
        # Without a compiler: no post-processing, said before installing
        bare = install.requirements(Machine("linux", "x86_64", (Gpu("RTX 5090", 32607, (12, 0)),)))
        self.assertEqual(bare.packages[1].env, (("ARDY_SKIP_MOTION_CORRECTION", "1"),))
        self.assertIn("cu128", bare.packages[0].index_url)
        self.assertTrue(any("compiler" in note for note in bare.notes))


class TestWindowConstraints(unittest.TestCase):
    def test_frames_picked_and_moved(self):
        constraints = [
            {"type": "fullbody", "frame_indices": [0, 30, 90], "local_joints_rot": ["a", "b", "c"],
             "root_positions": ["ra", "rb", "rc"]},
            {"type": "end-effector", "frame_indices": [45], "local_joints_rot": ["d"], "root_positions": ["rd"],
             "joint_names": ["Hips"]},
        ]
        window = window_constraints(constraints, 20, 100, offset=8)
        self.assertEqual(window[0]["frame_indices"], [18, 78])
        self.assertEqual(window[0]["local_joints_rot"], ["b", "c"])
        self.assertEqual(window[0]["root_positions"], ["rb", "rc"])
        self.assertEqual((window[1]["frame_indices"], window[1]["joint_names"]), ([33], ["Hips"]))
        self.assertEqual(window_constraints(constraints, 91, 120), [])
        # The request's list is untouched
        self.assertEqual(constraints[0]["frame_indices"], [0, 30, 90])


if __name__ == "__main__":
    unittest.main()
