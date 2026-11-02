"""The JSON lines protocol between the add-on and a backend's worker process. No bpy.

Imported on both sides: by the add-on (backends.process) and by the workers, which run in their own Python
(Blender's for the interpolation backend, the model's venv for Kimodo). Needs numpy, which both have.

One JSON object per line, UTF-8. Every message has a "type". Requests carry an "id"; the worker's answers
carry the id of the request they answer.

Add-on -> worker:
    {"type": "skeleton", "id": 1}                      describe the skeleton
    {"type": "load", "id": 2}                          load the model (slow models are kept loaded afterwards)
    {"type": "generate", "id": 3, "request": {...}}    core.motion.GenerationRequest.to_dict()
    {"type": "cancel", "id": 3}                        cancel a running generation
    {"type": "shutdown"}

Worker -> add-on:
    {"type": "hello", "protocol": 1, "backend": "<id>"}            first line, as soon as the worker runs
    {"type": "skeleton", "id": 1, "skeleton": {...}}               core.skeleton.Skeleton.to_dict()
    {"type": "ready", "id": 2}                                     the model is loaded
    {"type": "progress", "id": 3, "fraction": 0.4, "message": ""}
    {"type": "frames", "id": 3, "start_frame": 1, "fps": 30.0,     a chunk of the generated motion; a model
     "rotations": <array>, "root_positions": <array>}               may send many (streaming) or one
    {"type": "done", "id": 3}                                      last message of a request without other answer
    {"type": "error", "id": 3, "message": "...", "cancelled": false}

Bulk data are arrays: {"dtype": "f32", "shape": [...], "data": <base64 of the little-endian bytes>}.
In "frames": rotations (frames, joints, 4) are rotations from rest in world space (w, x, y, z), for every joint
of the skeleton in its order; root_positions (frames, 3) are the root joint's head in meters. Blender
conventions (Z-up, Blender frame numbers, the request's fps).
"""
import base64
import json
import os
import queue
import sys
import threading
import traceback

import numpy as np

# Inside the add-on this module is <add-on>.backends.protocol; in a worker, backends.protocol with the add-on's
# folder on sys.path
try:
    from ..core.motion import GenerationRequest, Motion, Pose
except ImportError:
    from core.motion import GenerationRequest, Motion, Pose

PROTOCOL_VERSION = 1

_DTYPES = {"f32": "<f4", "f64": "<f8"}


def encode_array(values, dtype="f32"):
    array = np.ascontiguousarray(values, dtype=_DTYPES[dtype])
    return {"dtype": dtype, "shape": list(array.shape), "data": base64.b64encode(array.tobytes()).decode("ascii")}


def decode_array(data):
    """Raises ValueError on a malformed array."""
    try:
        dtype = _DTYPES[data["dtype"]]
        array = np.frombuffer(base64.b64decode(data["data"]), dtype=dtype)
        return array.reshape(data["shape"]).astype(np.float64)
    except (KeyError, TypeError, ValueError) as e:
        raise ValueError(f"Malformed array in a worker message: {e}") from e


def dumps(message):
    return json.dumps(message, separators=(",", ":")) + "\n"


def loads(line):
    """Raises ValueError if the line isn't a JSON object with a type."""
    message = json.loads(line)
    if not isinstance(message, dict) or "type" not in message:
        raise ValueError(f"Not a protocol message: {line[:200]!r}")
    return message


def frames_message(request_id, start_frame, fps, rotations, root_positions):
    """A "frames" message. rotations: (frames, joints, 4), root_positions: (frames, 3)."""
    return {"type": "frames", "id": request_id, "start_frame": int(start_frame), "fps": float(fps),
            "rotations": encode_array(rotations), "root_positions": encode_array(root_positions)}


def motion_from_frames(messages, joint_names):
    """Join "frames" messages (in any order, contiguous) into a core.motion.Motion.
    Raises ValueError if they leave a gap, overlap or don't match the joints."""
    if not messages:
        raise ValueError("The backend returned no frames.")
    chunks = sorted(messages, key=lambda m: m["start_frame"])
    fps = chunks[0]["fps"]
    poses = []
    expected = chunks[0]["start_frame"]
    for chunk in chunks:
        if chunk["start_frame"] != expected:
            raise ValueError(f"The backend's frames are not contiguous (frame {chunk['start_frame']}, "
                             f"expected {expected}).")
        rotations = decode_array(chunk["rotations"])
        positions = decode_array(chunk["root_positions"])
        if rotations.ndim != 3 or rotations.shape[1:] != (len(joint_names), 4) or positions.shape != (len(rotations), 3):
            raise ValueError(f"The backend's frames don't match its skeleton ({len(joint_names)} joints): "
                             f"rotations {list(rotations.shape)}, root positions {list(positions.shape)}.")
        for q, p in zip(rotations.tolist(), positions.tolist()):
            poses.append(Pose(dict(zip(joint_names, map(tuple, q))), tuple(p)))
        expected += len(rotations)
    return Motion(fps=fps, start_frame=chunks[0]["start_frame"], poses=poses)


class Cancelled(Exception):
    """Raised inside a worker's generate() when the add-on cancels the request."""


class WorkerContext:
    """What a worker's handler gets for one request: progress, frames, cancellation."""

    def __init__(self, loop, request_id):
        self._loop = loop
        self.id = request_id

    @property
    def cancelled(self):
        return self.id in self._loop.cancelled

    def check_cancelled(self):
        """Raise Cancelled if the add-on cancelled this request."""
        if self.cancelled:
            raise Cancelled()

    def progress(self, fraction, message=""):
        self.check_cancelled()
        self._loop.send({"type": "progress", "id": self.id, "fraction": float(fraction), "message": message})

    def send_frames(self, start_frame, fps, rotations, root_positions):
        self._loop.send(frames_message(self.id, start_frame, fps, rotations, root_positions))


class WorkerLoop:
    """The worker side of the protocol. The handler implements:
        skeleton() -> core.skeleton.Skeleton
        load(context)                       load the model (optional: default does nothing)
        generate(request, context)          GenerationRequest; sends frames with context.send_frames
    stdin is read by a thread, so a "cancel" arrives while a generation runs; requests are handled one at a
    time, in order. The protocol uses a copy of the real stdout: anything else printed (by the model's
    libraries, even from C code) goes to stderr, so it can't break the protocol.
    """

    def __init__(self, backend_id, handler):
        self.backend_id = backend_id
        self.handler = handler
        self.cancelled = set()
        self._requests = queue.Queue()
        self._lock = threading.Lock()
        sys.stdout.flush()
        self._out = os.fdopen(os.dup(1), "w", encoding="utf-8", newline="\n")
        os.dup2(2, 1)
        sys.stdout = sys.stderr

    def send(self, message):
        with self._lock:
            self._out.write(dumps(message))
            self._out.flush()

    def _read_stdin(self):
        for raw in sys.stdin.buffer:
            line = raw.decode("utf-8").strip()
            if not line:
                continue
            try:
                message = loads(line)
            except ValueError as e:
                self.send({"type": "error", "id": None, "message": str(e), "cancelled": False})
                continue
            if message["type"] == "cancel":
                self.cancelled.add(message.get("id"))
            else:
                self._requests.put(message)
            if message["type"] == "shutdown":
                return
        self._requests.put({"type": "shutdown"})

    def run(self):
        self.send({"type": "hello", "protocol": PROTOCOL_VERSION, "backend": self.backend_id})
        threading.Thread(target=self._read_stdin, daemon=True).start()
        while True:
            message = self._requests.get()
            kind, request_id = message["type"], message.get("id")
            if kind == "shutdown":
                return
            context = WorkerContext(self, request_id)
            try:
                if kind == "skeleton":
                    self.send({"type": "skeleton", "id": request_id, "skeleton": self.handler.skeleton().to_dict()})
                elif kind == "load":
                    load = getattr(self.handler, "load", None)
                    if load is not None:
                        load(context)
                    self.send({"type": "ready", "id": request_id})
                elif kind == "generate":
                    self.handler.generate(GenerationRequest.from_dict(message["request"]), context)
                    context.check_cancelled()
                    self.send({"type": "done", "id": request_id})
                else:
                    raise ValueError(f"Unknown request type '{kind}'.")
            except Cancelled:
                self.send({"type": "error", "id": request_id, "message": "Cancelled.", "cancelled": True})
            except Exception as e:  # noqa: BLE001 - reported to the add-on, the worker keeps running
                traceback.print_exc()
                self.send({"type": "error", "id": request_id, "message": f"{type(e).__name__}: {e}",
                           "cancelled": False})
            finally:
                self.cancelled.discard(request_id)


