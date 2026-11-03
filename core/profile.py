"""Rig profile: how a rig maps to the humanoid roles, and how its IK limbs are snapped to FK. No bpy.

In Blender the profile is stored on the Armature data (see properties.py); this module is its neutral form,
used for the JSON files and to compose bone pairs with a backend's role -> joint map.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .retarget.pairs import BonePair, OFFSET_MODES
from .roles import get_role

PROFILE_FORMAT = "retargetor.rig_profile"
PROFILE_VERSION = 1

# Directions of compose()
TO_MODEL = "TO_MODEL"      # read the rig, write the model's skeleton
FROM_MODEL = "FROM_MODEL"  # read the model's skeleton, write the rig


@dataclass
class RoleBinding:
    """The rig bones playing one humanoid role.

    read_bone: the bone whose pose is read (e.g. Rigify "ORG-upper_arm.L", the result of FK and IK).
    write_bone: the control that receives the generated motion (e.g. Rigify "upper_arm_fk.L"). Empty: not written.
    corrections: {backend id: quaternion (w, x, y, z)} applied on the write bone, when writing from that backend.
    """
    role: str
    read_bone: str = ""
    write_bone: str = ""
    offset_mode: str = ""
    use_translation: bool | None = None
    corrections: dict[str, tuple[float, float, float, float]] = field(default_factory=dict)

    def __post_init__(self):
        role = get_role(self.role)
        if not self.offset_mode:
            self.offset_mode = role.default_offset_mode
        if self.offset_mode not in OFFSET_MODES:
            raise ValueError(f"Unknown offset mode '{self.offset_mode}' for the role '{self.role}'.")
        if self.use_translation is None:
            self.use_translation = role.default_use_translation


@dataclass
class FkPair:
    """An FK control and the bone whose orientation it takes when snapped (e.g. "upper_arm_fk.L", "ORG-upper_arm.L")."""
    fk_control: str
    followed_bone: str


# How an IK control is snapped to the limb's FK pose (IkSnap.mode)
IK_FOLLOW = "FOLLOW"  # takes the followed bone's transform, with the offset their rest poses have
IK_POLE = "POLE"      # a pole target, in the plane of the followed bone and its parent
IK_REST = "REST"      # reset to its rest pose
IK_SNAP_MODES = (IK_FOLLOW, IK_POLE, IK_REST)


@dataclass
class IkSnap:
    """How one IK control is snapped to its limb's FK pose (after a generation, so the limb plays in IK).

    FOLLOW: the control takes the followed bone's transform, with the offset their rest poses have (Rigify:
    "hand_ik.L" follows "ORG-hand.L"). Locked channels stay as they are.
    POLE: a pole target, placed in the plane of the followed bone and its parent, on the side the joint bends, at
    the distance it has at rest from the followed bone's head (Rigify: "upper_arm_ik_target.L", "ORG-forearm.L").
    REST: the control is reset to its rest pose (Rigify: "foot_heel_ik.L"); no followed bone.
    """
    ik_control: str
    followed_bone: str = ""
    mode: str = IK_FOLLOW

    def __post_init__(self):
        if self.mode not in IK_SNAP_MODES:
            raise ValueError(f"Unknown IK snap mode '{self.mode}' for '{self.ik_control}' "
                             f"(expected one of {', '.join(IK_SNAP_MODES)}).")


@dataclass
class LimbSnap:
    """How to snap one limb's FK controls to its current (IK) pose and switch it to FK, and back.

    switch_bone / switch_property: the custom property that switches IK/FK (Rigify: "upper_arm_parent.L", "IK_FK").
    fk_value: the value of that property in FK (Rigify: 1.0).
    controls: the FK controls, parents first.
    ik_controls: the controls posing the limb in IK (Rigify: "hand_ik.L", "upper_arm_ik_target.L"...): a user key
    on one of them makes a key pose, like a key on a write control.
    ik_snap: how the IK controls are snapped to the FK pose, in order (a control placed after the ones it depends
    on). Empty: the limb isn't snapped back to IK, it plays in FK after a generation.
    """
    name: str
    switch_bone: str = ""
    switch_property: str = ""
    fk_value: float = 1.0
    controls: list[FkPair] = field(default_factory=list)
    ik_controls: list[str] = field(default_factory=list)
    ik_snap: list[IkSnap] = field(default_factory=list)


@dataclass
class RigProfile:
    roles: list[RoleBinding] = field(default_factory=list)
    limbs: list[LimbSnap] = field(default_factory=list)

    def binding(self, role_id):
        """The RoleBinding of a role, or None."""
        for binding in self.roles:
            if binding.role == role_id:
                return binding
        return None

    def to_dict(self):
        return {
            "format": PROFILE_FORMAT,
            "version": PROFILE_VERSION,
            "roles": [
                {
                    "role": b.role,
                    "read_bone": b.read_bone,
                    "write_bone": b.write_bone,
                    "offset_mode": b.offset_mode,
                    "use_translation": b.use_translation,
                    "corrections": {backend: list(q) for backend, q in b.corrections.items()},
                }
                for b in self.roles
            ],
            "limbs": [
                {
                    "name": limb.name,
                    "switch_bone": limb.switch_bone,
                    "switch_property": limb.switch_property,
                    "fk_value": limb.fk_value,
                    "controls": [[p.fk_control, p.followed_bone] for p in limb.controls],
                    "ik_controls": list(limb.ik_controls),
                    "ik_snap": [[s.ik_control, s.followed_bone, s.mode] for s in limb.ik_snap],
                }
                for limb in self.limbs
            ],
        }

    @classmethod
    def from_dict(cls, data):
        """Build a profile from the dict written by to_dict. Raises ValueError on a wrong format or unknown role."""
        if not isinstance(data, dict) or data.get("format") != PROFILE_FORMAT:
            raise ValueError(f"Not a rig profile: the JSON must be an object with \"format\": \"{PROFILE_FORMAT}\".")
        if data.get("version", 0) > PROFILE_VERSION:
            raise ValueError(f"The rig profile was written by a newer version (format version {data['version']}).")

        profile = cls()
        seen = set()
        for entry in data.get("roles", []):
            role_id = entry.get("role", "")
            if role_id in seen:
                raise ValueError(f"The role '{role_id}' is listed twice in the rig profile.")
            seen.add(role_id)
            corrections = {}
            for backend, q in entry.get("corrections", {}).items():
                if len(q) != 4:
                    raise ValueError(f"The correction of the role '{role_id}' for '{backend}' must have 4 values.")
                corrections[backend] = tuple(float(v) for v in q)
            try:
                profile.roles.append(RoleBinding(
                    role=role_id,
                    read_bone=entry.get("read_bone", ""),
                    write_bone=entry.get("write_bone", ""),
                    offset_mode=entry.get("offset_mode", ""),
                    use_translation=entry.get("use_translation"),
                    corrections=corrections,
                ))
            except KeyError as e:
                raise ValueError(str(e.args[0])) from e

        for entry in data.get("limbs", []):
            ik_snap = []
            for item in entry.get("ik_snap", []):
                if not isinstance(item, (list, tuple)) or len(item) != 3:
                    raise ValueError(f"An IK snap entry of the limb '{entry.get('name', '')}' must be "
                                     "[IK control, followed bone, mode].")
                ik_snap.append(IkSnap(str(item[0]), str(item[1]), str(item[2])))
            profile.limbs.append(LimbSnap(
                name=entry.get("name", ""),
                switch_bone=entry.get("switch_bone", ""),
                switch_property=entry.get("switch_property", ""),
                fk_value=float(entry.get("fk_value", 1.0)),
                controls=[FkPair(fk, followed) for fk, followed in entry.get("controls", [])],
                ik_controls=[str(name) for name in entry.get("ik_controls", [])],
                ik_snap=ik_snap,
            ))
        return profile


def compose(profile, joint_map, direction, backend=None):
    """Bone pairs for one direction, from a rig profile and a backend's {role id: joint name} map.

    TO_MODEL: rig read bone -> model joint. FROM_MODEL: model joint -> rig write bone, with the
    corrections recorded for `backend`, and the read bone as pivot of the translated roles. Roles without a bone on the rig side, or unknown to the backend,
    are skipped. Offset mode and Use Translation come from the profile in both directions.
    """
    if direction not in (TO_MODEL, FROM_MODEL):
        raise ValueError(f"Unknown direction '{direction}' (expected {TO_MODEL} or {FROM_MODEL}).")

    pairs = []
    for binding in profile.roles:
        joint = joint_map.get(binding.role)
        if not joint:
            continue
        if direction == TO_MODEL:
            if binding.read_bone:
                pairs.append(BonePair(binding.read_bone, joint, binding.offset_mode, binding.use_translation))
        elif binding.write_bone:
            correction = binding.corrections.get(backend) if backend else None
            # The joint's head matches the read bone's head on the rig, not necessarily the control's
            pivot = binding.read_bone if binding.use_translation and binding.read_bone != binding.write_bone else ""
            pairs.append(BonePair(joint, binding.write_bone, binding.offset_mode, binding.use_translation,
                                  correction, pivot))
    return pairs
