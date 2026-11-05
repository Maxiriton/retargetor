"""A fake backend worker for the protocol tests (tests/unit/test_protocol.py).

Its behaviour depends on the request's prompt:
    "crash": the process exits; "fail": raises an error; "slow": progresses slowly until cancelled;
    "print": prints junk on stdout (from Python and from C) before answering; anything else: a motion in
    two chunks, rotating the second joint around Z.
"""
import ctypes
import math
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from backends import protocol  # noqa: E402
from core.skeleton import Joint, Skeleton  # noqa: E402


class FakeHandler:
    def skeleton(self):
        return Skeleton([Joint("root", None, (0, 0, 1), (0, 0, 1.2)), Joint("arm", "root", (0, 0, 1.2), (0.3, 0, 1.2))],
                        root="root")

    def load(self, context):
        context.progress(0.5, "loading")

    def generate(self, request, context):
        if request.prompt == "crash":
            os._exit(3)
        if request.prompt == "fail":
            raise RuntimeError("the model failed")
        if request.prompt == "slow":
            for step in range(1000):
                context.progress(step / 1000, "denoising")
                time.sleep(0.01)
        if request.prompt == "print":
            print("junk from Python")
            if sys.platform == "win32":
                ctypes.cdll.msvcrt.printf(b"junk from C\n")
                ctypes.cdll.msvcrt.fflush(None)
        frames = list(range(request.start_frame, request.end_frame + 1))
        half = len(frames) // 2
        for chunk in (frames[:half], frames[half:]):
            rotations, roots = [], []
            for frame in chunk:
                angle = 0.1 * (frame - request.start_frame)
                rotations.append([(1, 0, 0, 0), (math.cos(angle / 2), 0, 0, math.sin(angle / 2))])
                roots.append((0.0, 0.01 * frame, 1.0))
            context.progress(chunk[-1] / frames[-1])
            context.send_frames(chunk[0], request.fps, rotations, roots)


if __name__ == "__main__":
    protocol.WorkerLoop("fake", FakeHandler()).run()
