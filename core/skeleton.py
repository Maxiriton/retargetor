"""A motion model's skeleton, described by its backend in Blender conventions. No bpy.

The add-on builds the model's armature from it (core.skeleton_io). Heads and tails are in meters, Z-up,
in the armature's space; the rest pose is the model's own rest pose (rotations from rest are relative to it).
"""
from __future__ import annotations

from dataclasses import dataclass, field

SKELETON_FORMAT = "retargetor.skeleton"
SKELETON_VERSION = 1


def _vec3(values, what):
    if len(values) != 3:
        raise ValueError(f"{what} must have 3 values (x, y, z).")
    return tuple(float(v) for v in values)


@dataclass
class Joint:
    name: str
    parent: str | None
    head: tuple[float, float, float]
    tail: tuple[float, float, float]
    roll: float = 0.0


@dataclass
class Skeleton:
    """Joints listed parents first. root: the joint carrying the root motion (a joint without parent)."""
    joints: list[Joint] = field(default_factory=list)
    root: str = ""

    def __post_init__(self):
        seen = set()
        for joint in self.joints:
            if not joint.name:
                raise ValueError("A joint of the skeleton has no name.")
            if joint.name in seen:
                raise ValueError(f"The joint '{joint.name}' is listed twice in the skeleton.")
            if joint.parent is not None and joint.parent not in seen:
                raise ValueError(f"The parent '{joint.parent}' of the joint '{joint.name}' must be listed before it.")
            seen.add(joint.name)
        root = self.joint(self.root) if self.joints else None
        if root is None or root.parent is not None:
            raise ValueError(f"The root joint '{self.root}' must be a joint of the skeleton without parent.")

    @property
    def names(self):
        return [joint.name for joint in self.joints]

    def joint(self, name):
        """The Joint with this name, or None."""
        for joint in self.joints:
            if joint.name == name:
                return joint
        return None

    def to_dict(self):
        return {
            "format": SKELETON_FORMAT,
            "version": SKELETON_VERSION,
            "root": self.root,
            "joints": [{"name": j.name, "parent": j.parent, "head": list(j.head), "tail": list(j.tail), "roll": j.roll}
                       for j in self.joints],
        }

    @classmethod
    def from_dict(cls, data):
        """Raises ValueError on a wrong format."""
        if not isinstance(data, dict) or data.get("format") != SKELETON_FORMAT:
            raise ValueError(f"Not a skeleton: the JSON must be an object with \"format\": \"{SKELETON_FORMAT}\".")
        if data.get("version", 0) > SKELETON_VERSION:
            raise ValueError(f"The skeleton was written by a newer version (format version {data['version']}).")
        joints = [Joint(name=j["name"], parent=j.get("parent"),
                        head=_vec3(j["head"], f"The head of '{j['name']}'"),
                        tail=_vec3(j["tail"], f"The tail of '{j['name']}'"),
                        roll=float(j.get("roll", 0.0)))
                  for j in data.get("joints", [])]
        return cls(joints=joints, root=data.get("root", ""))
