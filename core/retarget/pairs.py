"""Bone pairs: which source bone is copied onto which target bone, and how. No bpy."""
from __future__ import annotations

from dataclasses import dataclass

OFFSET_MODES = ("ROLL", "REST_OFFSET")
IDENTITY_QUATERNION = (1.0, 0.0, 0.0, 0.0)


@dataclass(frozen=True)
class BonePair:
    """One source bone copied onto one target bone.

    offset_mode: how the rest pose difference is compensated.
        ROLL copies the direction of the source bone and only corrects the twist around the target's Y axis
        (right for limbs). REST_OFFSET applies the full rotation difference between the two rest poses.
    use_translation: the target also copies the source's movement (root motion), scaled.
    correction: extra rotation (w, x, y, z) applied in the target bone's local space, or None.
    pivot: for a translated pair, the target-side bone whose head matches the source bone's head, when it
        isn't the target itself (a rig's hips are read from one bone and written to another control: Rigify's
        ORG-spine and torso). The source's movement is applied to the pivot, and the target keeps its offset
        to the pivot, turned with the source. Empty: the target's own head.
    """
    source: str
    target: str
    offset_mode: str = "ROLL"
    use_translation: bool = False
    correction: tuple[float, float, float, float] | None = None
    pivot: str = ""

    def __post_init__(self):
        if self.offset_mode not in OFFSET_MODES:
            raise ValueError(f"Unknown offset mode '{self.offset_mode}' (expected one of {', '.join(OFFSET_MODES)}).")
        if self.correction is not None and len(self.correction) != 4:
            raise ValueError(f"The correction of '{self.target}' must be a quaternion (4 values).")


def target_map(pairs):
    """Return {target bone name: BonePair} for the pairs that have both a source and a target.
    Raises ValueError if several pairs write to the same target bone."""
    mapping = {}
    duplicates = set()
    for pair in pairs:
        if not pair.source or not pair.target:
            continue
        if pair.target in mapping:
            duplicates.add(pair.target)
        mapping[pair.target] = pair

    if duplicates:
        raise ValueError(
            "Several source bones point to the same target bone: " + ", ".join(sorted(duplicates))
        )
    return mapping
