"""Neutral types exchanged between Blender and the motion model backends. No bpy.

Blender conventions everywhere: Z-up, meters, quaternions (w, x, y, z), Blender frame numbers, scene fps.
Each backend adapter converts to and from its model's own conventions.

Joint rotations are expressed relative to the joint's rest orientation, in world space: the rotation that
takes the joint from its rest orientation to its posed orientation. This doesn't depend on bone rolls, so
it can be read from one armature and written to another one with the same joints. For a generation, "world"
is the model armature's own space (the character's space, see generation.place_model).
"""
from __future__ import annotations

from dataclasses import dataclass, field

Quat = tuple[float, float, float, float]
Vec3 = tuple[float, float, float]


def _quat(values, what):
    if len(values) != 4:
        raise ValueError(f"{what} must be a quaternion (w, x, y, z).")
    return tuple(float(v) for v in values)


def _vec3(values, what):
    if len(values) != 3:
        raise ValueError(f"{what} must have 3 values (x, y, z).")
    return tuple(float(v) for v in values)


@dataclass
class Pose:
    """A full or partial pose of a skeleton.

    rotations: {joint name: rotation from rest, world space}. A partial pose only lists some joints.
    root_position: world position of the root joint's head, in meters, or None if not constrained.
    """
    rotations: dict[str, Quat] = field(default_factory=dict)
    root_position: Vec3 | None = None

    def to_dict(self):
        return {
            "rotations": {name: list(q) for name, q in self.rotations.items()},
            "root_position": list(self.root_position) if self.root_position is not None else None,
        }

    @classmethod
    def from_dict(cls, data):
        root = data.get("root_position")
        return cls(
            rotations={name: _quat(q, f"The rotation of '{name}'") for name, q in data.get("rotations", {}).items()},
            root_position=_vec3(root, "The root position") if root is not None else None,
        )


@dataclass
class Motion:
    """A pose on every frame, from start_frame, at the given fps (Blender frame numbers)."""
    fps: float
    start_frame: int
    poses: list[Pose] = field(default_factory=list)

    @property
    def end_frame(self):
        """Last frame with a pose (start_frame - 1 if the motion is empty)."""
        return self.start_frame + len(self.poses) - 1

    @property
    def frames(self):
        return range(self.start_frame, self.start_frame + len(self.poses))

    def pose_at(self, frame):
        """The pose on a Blender frame. Raises KeyError outside the motion."""
        index = frame - self.start_frame
        if not 0 <= index < len(self.poses):
            raise KeyError(f"Frame {frame} is outside the motion ({self.start_frame}-{self.end_frame}).")
        return self.poses[index]

    def to_dict(self):
        return {"fps": self.fps, "start_frame": self.start_frame, "poses": [p.to_dict() for p in self.poses]}

    @classmethod
    def from_dict(cls, data):
        return cls(fps=float(data["fps"]), start_frame=int(data["start_frame"]),
                   poses=[Pose.from_dict(p) for p in data.get("poses", [])])


@dataclass
class GenerationRequest:
    """What a backend is asked to generate: a motion from start_frame to end_frame that hits the key poses.

    key_poses: {Blender frame: Pose}, in the model's skeleton (its joint names). May be empty (prompt only).
    origin: the character's pose on start_frame (a key pose there, or wherever the character stands), in the
    model's skeleton. Not a constraint: it tells where the motion starts and which way the character faces.
    """
    start_frame: int
    end_frame: int
    fps: float
    key_poses: dict[int, Pose] = field(default_factory=dict)
    prompt: str = ""
    seed: int | None = None
    origin: Pose | None = None

    def __post_init__(self):
        if self.end_frame < self.start_frame:
            raise ValueError(f"The end frame ({self.end_frame}) is before the start frame ({self.start_frame}).")
        if self.fps <= 0:
            raise ValueError("The frame rate must be positive.")
        outside = sorted(f for f in self.key_poses if not self.start_frame <= f <= self.end_frame)
        if outside:
            raise ValueError(f"Key poses outside the range {self.start_frame}-{self.end_frame}: {outside}")

    @property
    def duration(self):
        """Duration in seconds, from the first to the last frame included."""
        return (self.end_frame - self.start_frame + 1) / self.fps

    def to_dict(self):
        return {
            "start_frame": self.start_frame,
            "end_frame": self.end_frame,
            "fps": self.fps,
            "key_poses": {str(frame): pose.to_dict() for frame, pose in sorted(self.key_poses.items())},
            "prompt": self.prompt,
            "seed": self.seed,
            "origin": self.origin.to_dict() if self.origin is not None else None,
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            start_frame=int(data["start_frame"]),
            end_frame=int(data["end_frame"]),
            fps=float(data["fps"]),
            key_poses={int(frame): Pose.from_dict(p) for frame, p in data.get("key_poses", {}).items()},
            prompt=data.get("prompt", ""),
            seed=data.get("seed"),
            origin=Pose.from_dict(data["origin"]) if data.get("origin") is not None else None,
        )
