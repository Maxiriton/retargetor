"""Humanoid roles. No bpy.

The user maps their rig once, to roles (hips, upper arm, shin...). Each motion model backend maps the roles
to its own joints. Composing both gives direct bone pairs (see core.profile.compose).

Side roles end with ".L" or ".R", like Blender's bone names.
"""
from __future__ import annotations

from dataclasses import dataclass

# Groups, used for the default offset mode and to sort roles in the UI
SPINE = "SPINE"
ARM = "ARM"
LEG = "LEG"


@dataclass(frozen=True)
class Role:
    id: str
    label: str
    group: str
    # Limbs copy the direction of the bone (ROLL). The spine and the feet copy the rotation from rest (REST_OFFSET):
    # both rigs stand upright at rest, and those bones are laid out differently from rig to rig.
    default_offset_mode: str
    # Bones that carry the root motion
    default_use_translation: bool = False
    # A rig must map it for the motion to make sense: the rig check refuses to generate without it. The spine
    # roles are optional one by one, but at least one of them is needed (SPINE_BODY).
    required: bool = False


def _side_roles(base_id, label, group, required=False, offset_mode="ROLL"):
    return [Role(f"{base_id}.{side}", f"{label} ({side})", group, offset_mode, required=required)
            for side in ("L", "R")]


ROLES = (
    [
        Role("hips", "Hips", SPINE, "REST_OFFSET", default_use_translation=True, required=True),
        Role("spine", "Spine", SPINE, "REST_OFFSET"),
        Role("chest", "Chest", SPINE, "REST_OFFSET"),
        Role("upper_chest", "Upper Chest", SPINE, "REST_OFFSET"),
        Role("neck", "Neck", SPINE, "REST_OFFSET"),
        Role("upper_neck", "Upper Neck", SPINE, "REST_OFFSET"),
        Role("head", "Head", SPINE, "REST_OFFSET", required=True),
    ]
    + _side_roles("shoulder", "Shoulder", ARM)
    + _side_roles("upper_arm", "Upper Arm", ARM, required=True)
    + _side_roles("forearm", "Forearm", ARM, required=True)
    + _side_roles("hand", "Hand", ARM, required=True)
    + _side_roles("thigh", "Thigh", LEG, required=True)
    + _side_roles("shin", "Shin", LEG, required=True)
    # Feet copy the rotation from rest, like the spine: both rigs stand with their feet flat at rest, but a foot bone
    # goes from the ankle to the ball on one rig, to the toes or straight forward on another (Phase 6: copying the
    # direction put Auto-Rig Pro's and CloudRig's characters on tiptoe)
    + _side_roles("foot", "Foot", LEG, required=True, offset_mode="REST_OFFSET")
    + _side_roles("toes", "Toes", LEG, offset_mode="REST_OFFSET")
)

ROLES_BY_ID = {role.id: role for role in ROLES}

# Between the hips and the neck: a rig maps at least one of them
SPINE_BODY = ("spine", "chest", "upper_chest")


def missing_required(role_ids):
    """The required roles missing from `role_ids` (role ids), in the order of ROLES. The spine counts as one
    entry, "spine", when none of SPINE_BODY is there."""
    present = set(role_ids)
    missing = [role.id for role in ROLES if role.required and role.id not in present]
    if not present.intersection(SPINE_BODY):
        missing.insert(1 if "hips" in missing else 0, "spine")
    return missing


def get_role(role_id):
    """Return the Role with this id. Raises KeyError with an explicit message if it doesn't exist."""
    role = ROLES_BY_ID.get(role_id)
    if role is None:
        raise KeyError(f"Unknown humanoid role '{role_id}'.")
    return role
