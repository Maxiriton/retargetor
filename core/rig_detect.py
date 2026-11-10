"""Find the bones of each humanoid role on a skeleton, from their names and the hierarchy. No bpy.

Works on the skeletons animated directly (Mixamo, Unreal's mannequin, SMPL, VRM, Daz, Character Creator, a BVH
import...): the role's bone is read and written. Controller rigs (Rigify, Auto-Rig Pro, CloudRig) read one bone
and write another: they come with a preset, see presets/.

How:
- Names are normalized: a namespace ("mixamorig1:") and a few known prefixes ("CC_Base_", "J_Bip_", "m_avg_",
  "DEF-") are removed, then the side is found ("LeftArm", "upper_arm.L", "hand_l", "L_Hip", "lShldrBend"...).
- Each limb is a chain of bones on its side, from the spine to the hand or foot. The roles are matched along it in
  order (shoulder, upper arm, forearm, hand), each one with the first bone after the previous role that has one of
  its names. So a "Shoulder" is the collar bone in Mixamo ("LeftShoulder", "LeftArm") and the upper arm in SMPL
  ("L_Collar", "L_Shoulder"). A role whose name isn't found is filled from the hierarchy when it can be (the bone
  between the two roles around it), and reported.
- The hips are the bone the legs and the spine have in common, whatever their name (Daz and Character Creator
  have a "pelvis" under the hips, only on the legs' side).
- The spine bones between the hips and the neck are spread over spine, chest and upper chest; upper chest is
  the one the shoulders hang from. The neck bones over neck and upper neck.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .profile import RigProfile, RoleBinding
from .roles import ROLES, missing_required


@dataclass(frozen=True)
class BoneInfo:
    """A bone as detection sees it. head and tail: rest positions in the armature's space. Heights are measured
    along the hips -> head axis, so an armature whose bones are Y-up (an FBX import, the object turned 90 degrees)
    is read the same way."""
    name: str
    parent: str | None = None
    head: tuple[float, float, float] = (0.0, 0.0, 0.0)
    tail: tuple[float, float, float] = (0.0, 0.0, 0.0)


def body_axes(up, left):
    """The rig's body frame at rest, rounded to its armature's axes: (left, back, up) as unit axis vectors in the
    armature's space. Blender's convention is left = +X, back = +Y (the character faces -Y), up = +Z; an FBX import
    has its bones Y-up, an SMPL skeleton faces +Y. up: from the hips to the head; left: from the right limbs to the
    left ones. Raises ValueError if they are parallel."""
    def nearest(vector, exclude=None):
        best = None
        for axis in range(3):
            if exclude is not None and axis == exclude:
                continue
            if best is None or abs(vector[axis]) > abs(vector[best]):
                best = axis
        unit = [0.0, 0.0, 0.0]
        unit[best] = 1.0 if vector[best] >= 0.0 else -1.0
        return best, tuple(unit)

    up_axis, up_unit = nearest(up)
    _left_axis, left_unit = nearest(left, exclude=up_axis)
    if not any(left) or not any(up):
        raise ValueError("The rig's up and left directions can't be measured.")
    back = (up_unit[1] * left_unit[2] - up_unit[2] * left_unit[1],
            up_unit[2] * left_unit[0] - up_unit[0] * left_unit[2],
            up_unit[0] * left_unit[1] - up_unit[1] * left_unit[0])
    return left_unit, back, up_unit


# How a role was found (RoleMatch.how)
BY_NAME = "NAME"
BY_HIERARCHY = "HIERARCHY"


@dataclass(frozen=True)
class RoleMatch:
    role: str
    bone: str
    how: str


@dataclass
class Detection:
    """What was found. matches: {role id: RoleMatch}. missing: the required roles not found (see
    roles.missing_required). notes: what the user should know (roles filled from the hierarchy...)."""
    matches: dict[str, RoleMatch] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def complete(self):
        return not self.missing

    def profile(self):
        """A rig profile reading and writing the found bones, roles in the order of ROLES"""
        return RigProfile(roles=[RoleBinding(role=role.id, read_bone=self.matches[role.id].bone,
                                             write_bone=self.matches[role.id].bone)
                                 for role in ROLES if role.id in self.matches])


# --- Names

_NAMESPACE = re.compile(r"^.*[:|]")
_PREFIXES = re.compile(r"^(CC_Base_|J_Bip_|m_avg_|DEF[-_.]|Bip0*1[ _])", re.IGNORECASE)
# (pattern, flags): the side is group "side", the rest of the name "base" (and "pre" for an infix side)
_SIDE_PATTERNS = [
    (r"^(?P<base>.+?)[._\- ](?P<side>left|right)(?P<num>[._]\d+)?$", re.IGNORECASE),
    (r"^(?P<base>.+?)[._\- ](?P<side>[LR])(?P<num>[._]\d+)?$", re.IGNORECASE),
    (r"^(?P<side>left|right)[._\- ]?(?P<base>.+)$", re.IGNORECASE),
    (r"^(?P<side>[LR])[._\- ](?P<base>.+)$", re.IGNORECASE),
    (r"^(?P<pre>.+?)[._\- ](?P<side>[LR])[._\- ](?P<base>.+)$", re.IGNORECASE),
    (r"^(?P<side>[lr])(?P<base>[A-Z].*)$", 0),        # Daz: lShldrBend
    (r"^(?P<base>.*[a-z])(?P<side>[LR])$", 0),        # ArmL
]
_SIDE_PATTERNS = [re.compile(pattern, flags) for pattern, flags in _SIDE_PATTERNS]
_CENTER = re.compile(r"^[C][._\- ](?P<base>.+)$")     # VRM: J_Bip_C_Hips


def split_side(name):
    """(side "L", "R" or "", base name) of a bone name, namespace and known prefixes removed.
    >>> split_side("mixamorig1:LeftForeArm")
    ('L', 'ForeArm')"""
    name = _PREFIXES.sub("", _NAMESPACE.sub("", name))
    center = _CENTER.match(name)
    if center:
        return "", center.group("base")
    for pattern in _SIDE_PATTERNS:
        match = pattern.match(name)
        if match is None:
            continue
        side = match.group("side")[0].upper()
        groups = match.groupdict()
        base = (groups.get("pre") or "") + match.group("base") + (groups.get("num") or "")
        return side, base
    return "", name


def compact(base):
    """Lower case, letters and digits only: 'Upper_Arm' -> 'upperarm'"""
    return re.sub(r"[^a-z0-9]", "", base.lower())


# Names of each role, matched against the whole compact base name (side removed). Trailing digits are allowed.
_ROLE_NAMES = {
    "hips": r"hips?|pelvis|root?hips",
    "spine_any": r"spine\w*|abdomen\w*|chest\w*|waist|torso|back|upperchest|lowerback|stomach|belly|ribcage",
    "neck": r"neck\w*",
    "head": r"head",
    "shoulder": r"shoulder|clavicle|clav|collar\w*|collarbone",
    "upper_arm": r"upperarm\w*|uparm|arm|armtop|shldr\w*|shoulder|humerus|arm01|bicep",
    "forearm": r"forearm\w*|lowerarm\w*|loarm|elbow|armbot|ulna",
    "hand": r"hand|wrist|palm",
    "thigh": r"thigh\w*|upleg|upperleg\w*|legupper|hip|femur",
    "shin": r"shin\w*|calf|knee|lowerleg\w*|leg|loleg|leglower|tibia",
    "foot": r"foot|ankle",
    "toes": r"toes?|toebase|toe0|ball|foot",
}
_ROLE_NAMES = {key: re.compile(rf"(?:{pattern})\d*") for key, pattern in _ROLE_NAMES.items()}


def _is(key, base):
    return _ROLE_NAMES[key].fullmatch(compact(base)) is not None


# --- Hierarchy


class _Tree:
    def __init__(self, bones):
        self.bones = {b.name: b for b in bones}
        self.order = [b.name for b in bones]
        self.children = {b.name: [] for b in bones}
        for b in bones:
            if b.parent in self.children:
                self.children[b.parent].append(b.name)
        self.sides = {b.name: split_side(b.name) for b in bones}

    def parent(self, name):
        parent = self.bones[name].parent
        return parent if parent in self.bones else None

    def ancestors(self, name):
        """Parents of a bone, nearest first"""
        result = []
        parent = self.parent(name)
        while parent is not None and parent not in result:
            result.append(parent)
            parent = self.parent(parent)
        return result

    def depth(self, name):
        return len(self.ancestors(name))

    def side(self, name):
        return self.sides[name][0]

    def base(self, name):
        return self.sides[name][1]

    def descendants(self, name):
        """Children first (breadth first)"""
        result, queue = [], list(self.children[name])
        while queue:
            child = queue.pop(0)
            result.append(child)
            queue.extend(self.children[child])
        return result


def _first_named(tree, names, key):
    """The first of `names` with a name of `key`, or None"""
    for name in names:
        if _is(key, tree.base(name)):
            return name
    return None


def _limb_end(tree, side, key):
    """The bone ending a limb (hand, foot): the highest in the hierarchy among the bones of that side named
    like `key`. SMPL has a "Wrist" above its "Hand", an "Ankle" above its "Foot"."""
    found = [name for name in tree.order if tree.side(name) == side and _is(key, tree.base(name))]
    if not found:
        return None
    return min(found, key=lambda name: (tree.depth(name), tree.order.index(name)))


def _limb_chain(tree, end):
    """The bones of the limb ending with `end`, from the first one on its side (its parent is not) to `end`"""
    chain = [end]
    for parent in tree.ancestors(end):
        if tree.side(parent) != tree.side(end):
            break
        chain.append(parent)
    return list(reversed(chain))


def _match_chain(tree, chain, roles):
    """[(role, bone or None)] for `roles` (in order, the keys of _ROLE_NAMES) along `chain`: each role takes the
    first bone after the previous role's with one of its names. An optional first role (shoulder) that would take
    the bone a required one needs is skipped."""
    def assign(start, remaining):
        if not remaining:
            return []
        role = remaining[0]
        for i in range(start, len(chain)):
            if _is(role, tree.base(chain[i])):
                return [(role, chain[i])] + assign(i + 1, remaining[1:])
        return [(role, None)] + assign(start, remaining[1:])

    result = assign(0, roles)
    if roles[0] == "shoulder" and result[0][1] is not None and result[1][1] is None:
        # "Shoulder" was the upper arm: no collar bone
        alone = assign(0, roles[1:])
        if alone[0][1] is not None:
            result = [("shoulder", None)] + alone
    return result


def _fill_between(tree, chain, matched, notes):
    """A role with no bone of its name, between two roles that have one, takes the bone between them when there is
    exactly one (a forearm named "Bone.003")"""
    for i, (role, bone) in enumerate(matched):
        if bone is not None or i == 0 or i == len(matched) - 1:
            continue
        before, after = matched[i - 1][1], matched[i + 1][1]
        if before is None or after is None:
            continue
        between = chain[chain.index(before) + 1:chain.index(after)]
        if len(between) == 1:
            matched[i] = (role, between[0])
            notes.append(f"{role}: '{between[0]}' (between '{before}' and '{after}', its name says nothing)")
    return matched


def _height(tree, name, up):
    """Height of a bone's head along `up` = (origin, unit direction)"""
    origin, direction = up
    return sum((h - o) * d for h, o, d in zip(tree.bones[name].head, origin, direction))


def _up(tree, hips, head):
    """(origin, unit direction) from the hips' head to the head's head, or Z when they coincide"""
    origin, top = tree.bones[hips].head, tree.bones[head].head
    axis = [t - o for t, o in zip(top, origin)]
    length = sum(v * v for v in axis) ** 0.5
    return origin, tuple(v / length for v in axis) if length > 1e-9 else (0.0, 0.0, 1.0)


def detect(bones):
    """Detection on a list of BoneInfo (any order, parents named by `parent`)"""
    tree = _Tree(bones)
    result = Detection()
    found = {}   # role id -> (bone, how)

    # Limbs, from their ends
    limbs = {}
    for side in ("L", "R"):
        for end_key, keys in (("hand", ["shoulder", "upper_arm", "forearm", "hand"]),
                              ("foot", ["thigh", "shin", "foot"])):
            end = _limb_end(tree, side, end_key)
            if end is None:
                continue
            chain = _limb_chain(tree, end)
            matched = _fill_between(tree, chain, _match_chain(tree, chain, keys), result.notes)
            limbs[(side, end_key)] = chain
            for key, bone in matched:
                if bone is not None:
                    how = BY_NAME if _is(key, tree.base(bone)) else BY_HIERARCHY
                    found[f"{key}.{side}"] = (bone, how)
            if end_key == "foot":
                toes = _first_named(tree, tree.descendants(end), "toes")
                if toes is not None and tree.side(toes) == side:
                    found[f"toes.{side}"] = (toes, BY_NAME)

    # Hips: the bone the legs and the head have in common
    head = None
    heads = [name for name in tree.order if not tree.side(name) and _is("head", tree.base(name))]
    if heads:
        head = min(heads, key=lambda name: (tree.depth(name), tree.order.index(name)))
        found["head"] = (head, BY_NAME)
    legs = [found[f"thigh.{side}"][0] for side in ("L", "R") if f"thigh.{side}" in found]
    hips = None
    if legs and head is not None:
        common = [name for name in tree.ancestors(legs[0]) if name in tree.ancestors(head)]
        for leg in legs[1:]:
            common = [name for name in common if name in tree.ancestors(leg)]
        if common:
            hips = common[0]
            how = BY_NAME if _is("hips", tree.base(hips)) else BY_HIERARCHY
            found["hips"] = (hips, how)
            if how == BY_HIERARCHY:
                result.notes.append(f"hips: '{hips}' (the bone the legs and the spine have in common)")

    # Spine and neck, between the hips and the head
    if hips is not None and head is not None:
        path = list(reversed(tree.ancestors(head)))
        path = path[path.index(hips) + 1:]   # above the hips, up to the head's parent
        necks = [name for name in path if _is("neck", tree.base(name))]
        first_neck = path.index(necks[0]) if necks else len(path)
        body = path[:first_neck]
        if necks:
            found["neck"] = (necks[0], BY_NAME)
            if len(necks) > 1:
                found["upper_neck"] = (necks[-1], BY_NAME)
        # Upper chest: where the shoulders hang from (the parent of an arm chain), else the top of the spine
        attach = None
        for side in ("L", "R"):
            chain = limbs.get((side, "hand"))
            if chain and tree.parent(chain[0]) in body:
                attach = tree.parent(chain[0])
                break
        if body:
            upper = attach if attach is not None else body[-1]
            below = body[:body.index(upper)]
            found["upper_chest"] = (upper, BY_HIERARCHY)
            if below:
                found["spine"] = (below[0], BY_HIERARCHY)
            if len(below) > 1:
                up = _up(tree, hips, head)
                middle = (_height(tree, below[0], up) + _height(tree, upper, up)) / 2
                found["chest"] = (min(below[1:], key=lambda name: abs(_height(tree, name, up) - middle)),
                                  BY_HIERARCHY)
        else:
            result.notes.append("No bone between the hips and the neck: the spine is not mapped")

    # A bone plays one role only (the first one found keeps it)
    used = {}
    for role in ROLES:
        if role.id not in found:
            continue
        bone, how = found[role.id]
        if bone in used:
            result.notes.append(f"{role.id}: '{bone}' already plays {used[bone]}")
            continue
        used[bone] = role.id
        result.matches[role.id] = RoleMatch(role.id, bone, how)

    result.missing = missing_required(result.matches)
    heads = {role: tree.bones[match.bone].head for role, match in result.matches.items()}
    tails = {role: tree.bones[match.bone].tail for role, match in result.matches.items()}
    if sides_swapped(heads, tails):
        result.notes.append("The bones named left are on the character's right (its feet point the other way): "
                            "its sides may be swapped")
    return result


def _sub(a, b):
    return tuple(x - y for x, y in zip(a, b))


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def sides_swapped(heads, tails):
    """Whether the bones named left are on the character's right, from {role id: head} and {role id: tail} of
    the rest pose (any space): the toes are in front of the feet, so left = up x forward. True as soon as the arms
    or the legs disagree; False when it can't be told (no toes: a foot bone may point anywhere, Proog's IK foot
    control points back)."""
    if "hips" not in heads or "head" not in heads:
        return False
    up = _sub(heads["head"], heads["hips"])
    forward = (0.0, 0.0, 0.0)
    for side in ("L", "R"):
        foot, toes = f"foot.{side}", f"toes.{side}"
        if foot in heads and toes in heads:
            forward = tuple(f + d for f, d in zip(forward, _sub(heads[toes], heads[foot])))
    if not any(forward):
        return False
    side = _cross(up, forward)
    return any(_dot(side, _sub(heads[f"{role}.L"], heads[f"{role}.R"])) < 0.0
               for role in ("upper_arm", "thigh") if f"{role}.L" in heads and f"{role}.R" in heads)

