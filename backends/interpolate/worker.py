"""The interpolation backend's worker, run with Blender's Python (python -I worker.py)."""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from backends import protocol  # noqa: E402
from backends.interpolate.generate import segments  # noqa: E402
from backends.interpolate.skeleton import skeleton  # noqa: E402

BACKEND_ID = "interpolate"


class InterpolateHandler:
    def __init__(self):
        self._skeleton = skeleton()

    def skeleton(self):
        return self._skeleton

    def generate(self, request, context):
        total = request.end_frame - request.start_frame + 1
        done = 0
        for first, rotations, roots in segments(request, self._skeleton.names):
            context.send_frames(first, request.fps, rotations, roots)
            done += len(rotations)
            context.progress(done / total)


if __name__ == "__main__":
    protocol.WorkerLoop(BACKEND_ID, InterpolateHandler()).run()
