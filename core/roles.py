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
    # Limbs copy the direction of the bone (ROLL). The spine copies the rotation from rest (REST_OFFSET):
    # both rigs stand upright at rest, and spine bones are laid out differently from rig to rig.
    default_offset_mode: str
    # Bones that carry the root motion
    default_use_translation: bool = False


def _side_roles(base_id, label, group):
    return [Role(f"{base_id}.{side}", f"{label} ({side})", group, "ROLL") for side in ("L", "R")]


ROLES = (
    [
        Role("hips", "Hips", SPINE, "REST_OFFSET", default_use_translation=True),
        Role("spine", "Spine", SPINE, "REST_OFFSET"),
        Role("chest", "Chest", SPINE, "REST_OFFSET"),
        Role("upper_chest", "Upper Chest", SPINE, "REST_OFFSET"),
        Role("neck", "Neck", SPINE, "REST_OFFSET"),
        Role("upper_neck", "Upper Neck", SPINE, "REST_OFFSET"),
        Role("head", "Head", SPINE, "REST_OFFSET"),
    ]
    + _side_roles("shoulder", "Shoulder", ARM)
    + _side_roles("upper_arm", "Upper Arm", ARM)
    + _side_roles("forearm", "Forearm", ARM)
    + _side_roles("hand", "Hand", ARM)
    + _side_roles("thigh", "Thigh", LEG)
    + _side_roles("shin", "Shin", LEG)
    + _side_roles("foot", "Foot", LEG)
    + _side_roles("toes", "Toes", LEG)
)

ROLES_BY_ID = {role.id: role for role in ROLES}


def get_role(role_id):
    """Return the Role with this id. Raises KeyError with an explicit message if it doesn't exist."""
    role = ROLES_BY_ID.get(role_id)
    if role is None:
        raise KeyError(f"Unknown humanoid role '{role_id}'.")
    return role
