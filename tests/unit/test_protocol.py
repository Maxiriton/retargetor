"""The worker protocol and process, with a fake worker (tests/fixtures/fake_worker.py). No Blender.

Run with Blender's Python (tests/run_tests.py does it), from the repository root:
    <blender>/5.2/python/bin/python.exe -I -m unittest discover -s tests/unit
"""
import math
import os
import sys
import time
import unittest

import numpy as np

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from backends import process, protocol  # noqa: E402
from core.motion import GenerationRequest, Pose  # noqa: E402
from core.skeleton import Skeleton  # noqa: E402

FAKE_WORKER = os.path.join(REPO, "tests", "fixtures", "fake_worker.py")


def request(prompt="", start=1, end=10):
    pose = Pose({"root": (1.0, 0.0, 0.0, 0.0)}, (0.0, 0.0, 1.0))
    return GenerationRequest(start, end, 24.0, {start: pose, end: pose}, prompt=prompt, seed=1).to_dict()


class TestEncoding(unittest.TestCase):
    def test_array_round_trip(self):
        values = np.random.default_rng(0).normal(size=(5, 3, 4))
        again = protocol.decode_array(protocol.encode_array(values))
        np.testing.assert_allclose(again, values, atol=1e-6)
        self.assertEqual(protocol.decode_array(protocol.encode_array(values, "f64")).tolist(), values.tolist())
        with self.assertRaisesRegex(ValueError, "Malformed"):
            protocol.decode_array({"dtype": "f32", "shape": [2, 2], "data": ""})

    def test_compact(self):
        # 77 joints, 300 frames: the size of a 10 s Kimodo motion
        message = protocol.frames_message(1, 1, 30.0, np.zeros((300, 77, 4)), np.zeros((300, 3)))
        self.assertLess(len(protocol.dumps(message)), 500_000)

    def test_motion_from_frames(self):
        names = ["a", "b"]
        rot = np.tile((1.0, 0.0, 0.0, 0.0), (4, 2, 1))
        chunks = [protocol.frames_message(1, 3, 30.0, rot[2:], np.ones((2, 3))),
                  protocol.frames_message(1, 1, 30.0, rot[:2], np.zeros((2, 3)))]
        motion = protocol.motion_from_frames(chunks, names)
        self.assertEqual((motion.start_frame, motion.end_frame, motion.fps), (1, 4, 30.0))
        self.assertEqual(motion.pose_at(3).root_position, (1.0, 1.0, 1.0))
        self.assertEqual(set(motion.pose_at(1).rotations), {"a", "b"})
        with self.assertRaisesRegex(ValueError, "not contiguous"):
            protocol.motion_from_frames(chunks[:1] + [protocol.frames_message(1, 6, 30.0, rot[:1], np.zeros((1, 3)))], names)
        with self.assertRaisesRegex(ValueError, "don't match"):
            protocol.motion_from_frames(chunks, ["a"])


class TestWorker(unittest.TestCase):
    def setUp(self):
        self.worker = process.Worker([sys.executable, "-I", "-u", FAKE_WORKER])

    def tearDown(self):
        self.worker.stop()

    def test_requests(self):
        worker = self.worker
        skeleton = worker.wait(worker.submit("skeleton"), timeout=30)
        self.assertEqual(worker.state, process.READY)
        self.assertEqual(worker.backend_id, "fake")
        self.assertTrue(skeleton.finished_ok, skeleton.error)
        names = Skeleton.from_dict(skeleton.result).names
        self.assertEqual(names, ["root", "arm"])

        load = worker.wait(worker.submit("load"), timeout=30)
        self.assertTrue(load.finished_ok)

        job = worker.wait(worker.submit("generate", request=request()), timeout=30)
        self.assertTrue(job.finished_ok, job.error)
        self.assertEqual(len(job.frames), 2)
        motion = protocol.motion_from_frames(job.frames, names)
        self.assertEqual((motion.start_frame, motion.end_frame, motion.fps), (1, 10, 24.0))
        q = motion.pose_at(4).rotations["arm"]
        self.assertAlmostEqual(q[3], math.sin(0.15), places=6)
        self.assertAlmostEqual(motion.pose_at(10).root_position[1], 0.1, places=6)

    def test_error_keeps_the_worker(self):
        job = self.worker.wait(self.worker.submit("generate", request=request("fail")), timeout=30)
        self.assertEqual(job.state, process.FAILED)
        self.assertIn("the model failed", job.error)
        job = self.worker.wait(self.worker.submit("generate", request=request()), timeout=30)
        self.assertTrue(job.finished_ok, job.error)

    def test_junk_on_stdout_does_not_break_the_protocol(self):
        job = self.worker.wait(self.worker.submit("generate", request=request("print")), timeout=30)
        self.assertTrue(job.finished_ok, job.error)
        self.assertIn("junk from Python", self.worker.stderr_tail())

    def test_cancel(self):
        worker = self.worker
        job = worker.submit("generate", request=request("slow"))
        start = time.perf_counter()
        while job.fraction <= 0.0 and time.perf_counter() - start < 30:
            worker.pump()
            time.sleep(0.01)
        self.assertGreater(job.fraction, 0.0)
        worker.cancel(job)
        worker.wait(job, timeout=30)
        self.assertEqual(job.state, process.CANCELLED)
        self.assertLess(job.fraction, 0.5)
        job = worker.wait(worker.submit("generate", request=request()), timeout=30)
        self.assertTrue(job.finished_ok, "the worker still answers after a cancel")

    def test_crash(self):
        job = self.worker.wait(self.worker.submit("generate", request=request("crash")), timeout=30)
        self.assertEqual(job.state, process.FAILED)
        self.assertIn("exit code 3", job.error)
        self.assertEqual(self.worker.state, process.STOPPED)
        # Restarted on the next request
        job = self.worker.wait(self.worker.submit("skeleton"), timeout=30)
        self.assertTrue(job.finished_ok)

    def test_missing_executable(self):
        worker = process.Worker([os.path.join(REPO, "no_such_python.exe")])
        with self.assertRaisesRegex(process.WorkerError, "Unable to start"):
            worker.submit("skeleton")

    def test_round_trip_latency(self):
        worker = self.worker
        worker.wait(worker.submit("skeleton"), timeout=30)
        start = time.perf_counter()
        for _ in range(20):
            worker.wait(worker.submit("load"), timeout=30, poll=0.0005)
        latency = (time.perf_counter() - start) / 20
        print(f"\nFINDING protocol round trip: {latency * 1000:.1f} ms", file=sys.stderr)
        self.assertLess(latency, 0.05)


if __name__ == "__main__":
    unittest.main()
